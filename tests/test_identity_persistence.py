from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import test_server
from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from blastradius.server.app import create_app
from blastradius.server.admin import assign_plan
from blastradius.server.auth import token_hash
from blastradius.server.models import Base, LoginSession, Membership, Organization, Project, User
from test_server import identity_client, login, project, submit, terminal

backend_client = test_server.backend_client
demo_results = test_server.demo_results
migration_database = test_server.migration_database
settings = test_server.settings


def test_signed_oidc_logout_relogin_identity_separation(
    migration_database, settings, demo_results, monkeypatch
):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    settings = replace(
        settings,
        auth_mode="oidc",
        public_url="https://app.example",
        oidc_issuer="https://issuer.example",
        oidc_client_id="local-client",
        oidc_client_secret="local-secret",
        database_url=migration_database.engine.url.render_as_string(hide_password=False),
    )
    signing_key = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "test"})
    authorization = {}
    identity = {"sub": "stable", "email": "first@example.test", "email_verified": True}
    calls = []

    def provider(request):
        calls.append(request.url.path)
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": settings.oidc_issuer,
                    "authorization_endpoint": settings.oidc_issuer + "/authorize",
                    "token_endpoint": settings.oidc_issuer + "/token",
                    "jwks_uri": settings.oidc_issuer + "/keys",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [signing_key.as_dict(is_private=False)]})
        assert request.url.path == "/token"
        assert len(parse_qs(request.content.decode())["code_verifier"][0]) >= 43
        claims = {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_client_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": authorization["nonce"][0],
            "name": "Local signed identity",
            **identity,
        }
        return httpx.Response(
            200,
            json={
                "access_token": "local-only-unused",
                "token_type": "Bearer",
                "id_token": jwt.encode(
                    {"alg": "RS256", "kid": "test"}, claims, signing_key
                ).decode(),
            },
        )

    def authenticate(client):
        response = client.get("/api/auth/login", follow_redirects=False)
        assert response.status_code == 302
        authorization.clear()
        authorization.update(parse_qs(urlsplit(response.headers["location"]).query))
        assert authorization["code_challenge_method"] == ["S256"]
        response = client.get(
            "/api/auth/callback",
            params={
                "code": "local-code",
                "state": authorization["state"][0],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        me = client.get("/api/me").json()
        client.headers.update({"X-CSRF-Token": me["csrf_token"], "Origin": settings.public_url})
        return me

    app = create_app(settings)
    app.state.oauth.create_client("oidc").client_kwargs["transport"] = httpx.MockTransport(provider)
    with TestClient(app, base_url=settings.public_url) as client:
        first = authenticate(client)
        old_cookie = client.cookies.get("br_session")
        response = client.post(
            "/api/projects",
            json={
                "name": "Persistent project",
                "organization_id": first["organizations"][0]["id"],
            },
        )
        assert response.status_code == 201
        project_id = response.json()["id"]
        assert client.post("/api/auth/logout").status_code == 200
        with app.state.db.session() as session:
            assert session.get(LoginSession, token_hash(old_cookie)) is None
        identity["email"] = "changed@example.test"
        second = authenticate(client)
        assert second["user"]["id"] == first["user"]["id"]
        assert second["organizations"][0]["id"] == first["organizations"][0]["id"]
        assert second["user"]["email"] == "changed@example.test"
        assert client.cookies.get("br_session") != old_cookie
        assert client.get(f"/api/projects/{project_id}").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        identity["sub"] = "distinct"
        third = authenticate(client)
        assert third["user"]["id"] != first["user"]["id"]
        assert third["organizations"][0]["id"] != first["organizations"][0]["id"]
        assert client.get(f"/api/projects/{project_id}").status_code == 404
        assert client.post("/api/auth/logout").status_code == 200
        identity.update(sub="stable", email_verified=False)
        fourth = authenticate(client)
        assert fourth["user"]["id"] == first["user"]["id"]
        assert fourth["user"]["email"] == "" and not fourth["user"]["email_verified"]
        assert client.get(f"/api/projects/{project_id}").status_code == 200
    settings = replace(settings, oidc_issuer="https://other-issuer.example")
    identity.update(sub="stable", email_verified=True)
    app = create_app(settings)
    app.state.oauth.create_client("oidc").client_kwargs["transport"] = httpx.MockTransport(provider)
    with TestClient(app, base_url=settings.public_url) as client:
        fifth = authenticate(client)
        assert fifth["user"]["id"] != first["user"]["id"]
        assert fifth["organizations"][0]["id"] != first["organizations"][0]["id"]
        assert client.get(f"/api/projects/{project_id}").status_code == 404
        with app.state.db.session() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 3
            assert session.scalar(select(func.count()).select_from(Organization)) == 3
        assert calls.count("/token") == 5


def test_concurrent_last_owner_demotion(backend_client):
    client, app = backend_client
    me = login(client)
    org_id = me["organizations"][0]["id"]
    assign_plan(app.state.db, org_id, "team")
    second, user_id = identity_client(app, org_id=org_id, role="owner")
    clients = [client, second]
    users = [me["user"]["id"], user_id]

    def demote(index):
        return (
            clients[index]
            .patch(
                f"/api/organizations/{org_id}/members/{users[index]}", json={"role": "developer"}
            )
            .status_code
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(demote, (0, 1))) == [200, 409]
    with app.state.db.session() as session:
        owners = session.scalars(
            select(Membership).where(
                Membership.organization_id == org_id, Membership.role == "owner"
            )
        ).all()
        assert len(owners) == 1
    second.close()


def test_all_workspace_evidence_survives_application_restart(
    migration_database, settings, demo_results, monkeypatch
):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    settings = replace(
        settings,
        database_url=migration_database.engine.url.render_as_string(hide_password=False),
    )
    tables = [
        Base.metadata.tables[name]
        for name in (
            "users",
            "sessions",
            "organizations",
            "memberships",
            "projects",
            "analyses",
            "findings",
            "attack_paths",
            "attack_path_hops",
            "analysis_artifacts",
            "usage",
            "audit_events",
        )
    ]

    def snapshot(database):
        with database.engine.connect() as connection:
            return {
                table.name: connection.execute(
                    select(
                        *[
                            column
                            for column in table.columns
                            if column.name not in ("token_hash", "csrf_token")
                        ]
                    ).order_by(*table.primary_key.columns)
                )
                .mappings()
                .all()
                for table in tables
            }

    app = create_app(settings)
    with TestClient(app) as client:
        me = login(client)
        org_id = me["organizations"][0]["id"]
        assign_plan(app.state.db, org_id, "team")
        proj = project(client, me)
        policy_urls = (
            f"/api/organizations/{org_id}/policy",
            f"/api/projects/{proj['id']}/policy",
        )
        for url in policy_urls:
            assert client.put(url, json={}).status_code == 200
        job = terminal(client, submit(client, proj["id"]).json()["id"])
        assert job["status"] == "succeeded" and job["decision"] == "BLOCK CHANGE"
        reports = {}
        for format in ("json", "markdown", "sarif"):
            response = client.get(f"/api/analyses/{job['id']}/report?format={format}")
            assert response.status_code == 200
            reports[format] = response.content
        policies = {url: client.get(url).json() for url in policy_urls}
        cookies = httpx.Cookies(client.cookies)
        saved = snapshot(app.state.db)
        assert all(saved.values())
        assert saved["organizations"][0]["plan"] == "team"
        assert saved["organizations"][0]["policy_version"] == 1
        assert saved["projects"][0]["policy_version"] == 1
        assert saved["analyses"][0]["policy_snapshot"] is not None
        assert saved["usage"][0]["analyses"] == 1
        assert saved["usage"][0]["exports"] == 3
        assert any(event["action"] == "plan.assigned" for event in saved["audit_events"])

    restarted = create_app(settings)
    with TestClient(restarted) as client:
        assert client.get("/health/ready").status_code == 200
        assert snapshot(restarted.state.db) == saved
        client.cookies.update(cookies)
        client.headers["X-CSRF-Token"] = me["csrf_token"]
        restored = client.get("/api/me").json()
        assert restored["user"] == me["user"]
        assert restored["organizations"][0]["id"] == org_id
        assert restored["organizations"][0]["role"] == "owner"
        assert client.get(f"/api/analyses/{job['id']}").json() == job
        for url, expected in policies.items():
            assert client.get(url).json() == expected
        for format, content in reports.items():
            assert (
                client.get(f"/api/analyses/{job['id']}/report?format={format}").content == content
            )
        assert (
            client.patch(f"/api/projects/{proj['id']}", json={"name": "After restart"}).status_code
            == 200
        )


def test_identity_uniqueness_and_foreign_keys_roll_back_atomically(migration_database):
    database = migration_database
    database.migrate()
    with database.session(write=True) as session:
        user = User(issuer="local-test", subject="stable")
        org = Organization(name="Preserved")
        session.add_all([user, org])
        session.flush()
        user_id, org_id = user.id, org.id
    for invalid in (
        User(issuer="local-test", subject="stable"),
        Project(organization_id="missing-organization", name="Invalid"),
        Membership(user_id=user_id, organization_id=org_id, role="invalid"),
    ):
        with pytest.raises(IntegrityError):
            with database.session(write=True) as session:
                session.get(Organization, org_id).name = "Must roll back"
                session.flush()
                session.add(invalid)
        with database.session() as session:
            assert session.get(Organization, org_id).name == "Preserved"
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert session.scalar(select(func.count()).select_from(Project)) == 0
            assert session.scalar(select(func.count()).select_from(Membership)) == 0
