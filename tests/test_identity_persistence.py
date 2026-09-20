from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import test_server
from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from blastradius.server.app import create_app
from blastradius.server.admin import assign_plan
from blastradius.server.auth import token_hash
from blastradius.server.models import LoginSession, Membership, Organization, User
from test_server import identity_client, login

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
