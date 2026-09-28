from __future__ import annotations

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import test_server
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from authlib.jose import JsonWebKey, jwt
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError

from blastradius.server.admin import main as admin_main
from blastradius.server.app import create_app
from blastradius.server.auth import create_session, provision, token_hash
from blastradius.server.beta import PRIVACY_VERSION, cleanup_commercial
from blastradius.server.config import Settings
from blastradius.server.db import Database, migration_config
from blastradius.server.events import EVENT_NAMES, event_summary, record_event
from blastradius.server.models import (
    Analysis,
    AnalysisFeedback,
    AuditEvent,
    Base,
    BetaInterest,
    CommercialLock,
    LoginSession,
    Membership,
    Organization,
    ProductEvent,
    Project,
    User,
)
from blastradius.server.operator import RESOURCES
from test_server import identity_client, login, project, submit, terminal

backend_client = test_server.backend_client
demo_results = test_server.demo_results
migration_database = test_server.migration_database
settings = test_server.settings

LEAD = {
    "name": "Synthetic tester",
    "email": "tester@example.test",
    "privacy_consent": True,
    "privacy_version": PRIVACY_VERSION,
}


def bootstrap(client):
    me = client.get("/api/me").json()
    client.headers.update({"Origin": "http://testserver", "X-CSRF-Token": me["csrf_token"]})
    return me


def seed_analysis(app, me, status="succeeded"):
    with app.state.db.session(write=True) as session:
        proj = Project(organization_id=me["organizations"][0]["id"], name="Synthetic project")
        session.add(proj)
        session.flush()
        job = Analysis(
            organization_id=proj.organization_id,
            project_id=proj.id,
            created_by=me["user"]["id"],
            base_label="baseline",
            candidate_label="candidate",
            status=status,
        )
        session.add(job)
        session.flush()
        return job.id


def event_counts(app):
    with app.state.db.session() as session:
        return event_summary(session)["counts"]


def issued_client(app, user_id, oidc=False):
    response = Response()
    with app.state.db.session(write=True) as session:
        create_session(response, session, app.state.settings, user_id, oidc_authenticated=oidc)
    client = TestClient(app)
    client.cookies.set("br_session", response.headers["set-cookie"].split(";")[0].split("=", 1)[1])
    bootstrap(client)
    return client


@pytest.fixture
def operator_client(migration_database, settings, demo_results, monkeypatch):
    migration_database.migrate()
    with migration_database.session(write=True) as session:
        user = provision(
            session,
            "https://issuer.example",
            "operator",
            "Private name",
            "operator@example.test",
            True,
        )
        user_id = user.id
    configured = replace(
        settings,
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="test",
        oidc_client_secret="test",
        web_admin_user_ids=(user_id,),
        database_url=migration_database.engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    app = create_app(configured)
    with TestClient(app):
        client = issued_client(app, user_id, True)
        try:
            yield client, app, user_id
        finally:
            client.close()


def test_public_lead_is_persisted_private_and_content_not_logged(backend_client, caplog):
    client, app = backend_client
    caplog.set_level(logging.INFO)
    me = bootstrap(client)
    assert not me["authenticated"] and not me["capabilities"]["platform_admin"]
    notice = client.get("/api/beta-interest/privacy").json()
    assert notice["version"] == PRIVACY_VERSION and notice["retention_days"] == 90
    assert "Terraform" in notice["notice"] and "email" in notice["notice"]
    payload = {
        **LEAD,
        "company": "Private-company",
        "role": "Platform",
        "team_size": 3,
        "repository_count": 7,
        "primary_cloud": "aws",
        "source_control": "github",
        "problem": "PRIVATE-FEEDBACK-TEST-CONTENT",
    }
    result = client.post("/api/beta-interest", json=payload)
    assert result.status_code == 201
    assert result.json() == {"status": "stored", "message": "Your beta interest has been saved."}
    assert result.headers["cache-control"] == "no-store"
    assert client.get("/api/beta-interest").status_code == 405
    for path in ("/api/beta-interest/list", "/api/feedback"):
        assert client.get(path).status_code == 404
    for resource in RESOURCES:
        assert client.get(f"/api/admin/{resource}").status_code == 401
    with app.state.db.session() as session:
        row = session.scalar(select(BetaInterest))
        assert row.name == LEAD["name"] and row.problem == payload["problem"]
        assert row.privacy_version == PRIVACY_VERSION and row.created_at > time.time() - 60
        event = session.scalar(select(ProductEvent))
        assert event.name == "beta_interest_submitted"
        assert (
            event.user_id is event.organization_id is event.project_id is event.analysis_id is None
        )
    for value in (payload["email"], payload["name"], payload["problem"], payload["company"]):
        assert value not in caplog.text


@pytest.mark.parametrize(
    "update",
    [
        {"name": ""},
        {"name": "a" * 101},
        {"name": "a\x00"},
        {"email": "invalid"},
        {"email": "x\n@y.test"},
        {"email": "a" * 321},
        {"privacy_consent": False},
        {"privacy_consent": "true"},
        {"privacy_consent": 1},
        {"privacy_version": "old"},
        {"company": "a" * 121},
        {"role": "a" * 81},
        {"team_size": 0},
        {"team_size": "3"},
        {"team_size": True},
        {"repository_count": -1},
        {"repository_count": 100001},
        {"primary_cloud": "untrusted"},
        {"source_control": "untrusted"},
        {"problem": "x" * 1001},
        {"before_files": {"secret.tf": "private"}},
        {"plan": "team"},
        {"user_id": "spoof"},
    ],
    ids=lambda value: next(iter(value)),
)
def test_lead_validation_rejects_unknown_and_unbounded_fields(backend_client, update):
    client, app = backend_client
    bootstrap(client)
    response = client.post("/api/beta-interest", json={**LEAD, **update})
    assert response.status_code == 422 and response.json() == {"detail": "invalid_request"}
    with app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(BetaInterest)) == 0
        assert session.scalar(select(func.count()).select_from(ProductEvent)) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "null"},
        {"Origin": "http://evil.test"},
        {"Origin": "http://testserver/"},
        {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
        {"Origin": "http://testserver", "X-CSRF-Token": "wrong"},
    ],
)
def test_lead_origin_and_csrf_fail_closed(backend_client, headers):
    client, _ = backend_client
    csrf = client.get("/api/me").json()["csrf_token"]
    response = client.post(
        "/api/beta-interest", json=LEAD, headers={"X-CSRF-Token": csrf, **headers}
    )
    assert response.status_code == 403


def test_dedicated_body_rate_and_storage_bounds(backend_client, monkeypatch):
    client, app = backend_client
    bootstrap(client)
    assert client.post("/api/beta-interest", content=b"x" * 8193).status_code == 413
    monkeypatch.setattr("blastradius.server.beta.LEAD_LIMIT", 1)
    assert client.post("/api/beta-interest", json=LEAD).status_code == 201
    assert client.post("/api/beta-interest", json=LEAD).status_code == 503
    assert event_counts(app)["beta_interest_submitted"] == 1
    assert client.post("/api/beta-interest", json=LEAD).status_code == 503
    assert client.post("/api/beta-interest", json=LEAD).status_code == 503
    assert client.post("/api/beta-interest", json=LEAD).status_code == 429
    assert client.get("/api/me").status_code == 200


def test_global_lead_rate_does_not_use_forwarded_ip(backend_client):
    _, app = backend_client
    for index in range(61):
        client = TestClient(app, client=(f"192.0.2.{index}", 1234))
        bootstrap(client)
        response = client.post("/api/beta-interest", json=LEAD)
        assert response.status_code == (201 if index < 60 else 429)
        client.close()


def test_lead_capacity_is_atomic(backend_client, monkeypatch):
    client, app = backend_client
    bootstrap(client)
    monkeypatch.setattr("blastradius.server.beta.LEAD_LIMIT", 1)
    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(
            pool.map(lambda _: client.post("/api/beta-interest", json=LEAD).status_code, range(5))
        )
    assert sorted(statuses) == [201, 503, 503, 503, 503]
    assert event_counts(app)["beta_interest_submitted"] == 1


@pytest.mark.parametrize("role", ["owner", "admin", "developer", "viewer"])
def test_feedback_authorized_roles_never_become_platform_admin(backend_client, role):
    client, app = backend_client
    owner = login(client)
    analysis_id = seed_analysis(app, owner)
    other, user_id = identity_client(app, org_id=owner["organizations"][0]["id"], role=role)
    bootstrap(other)
    path = f"/api/analyses/{analysis_id}/feedback"
    saved = other.put(path, json={"useful": False, "message": "Private observation"})
    assert saved.status_code == 200
    feedback = saved.json()["feedback"]
    assert feedback["user_id"] == user_id and feedback["analysis_id"] == analysis_id
    assert feedback["organization_id"] == owner["organizations"][0]["id"]
    assert other.get(path).json() == saved.json()
    assert client.get(path).json() == {"feedback": None}
    before = event_counts(app)
    assert before["feedback_submitted"] == 1
    second = other.put(path, json={"useful": True}).json()["feedback"]
    assert second["id"] == feedback["id"] and second["created_at"] == feedback["created_at"]
    assert second["updated_at"] >= feedback["updated_at"] and second["message"] == ""
    assert event_counts(app) == before
    assert other.get("/api/me").json()["capabilities"]["platform_admin"] is False
    for resource in RESOURCES:
        assert other.get(f"/api/admin/{resource}").status_code == 403
    with app.state.db.session() as session:
        assert session.get(Membership, (user_id, owner["organizations"][0]["id"])).role == role


def test_feedback_idor_expiration_csrf_and_terminal_gate(backend_client):
    client, app = backend_client
    me = login(client)
    bootstrap(client)
    analysis_id = seed_analysis(app, me, "queued")
    path = f"/api/analyses/{analysis_id}/feedback"
    assert client.put(path, json={"useful": True}).status_code == 409
    with app.state.db.session(write=True) as session:
        session.get(Analysis, analysis_id).status = "failed"
    assert client.put(path, json={"useful": True}, headers={"Origin": "null"}).status_code == 403
    assert (
        client.put(path, json={"useful": True}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    )
    assert client.put(path, json={"useful": True}).status_code == 200
    other, _ = identity_client(app)
    bootstrap(other)
    assert other.get(path).status_code == 404
    assert other.put(path, json={"useful": True}).status_code == 404
    assert client.put(path, json={"useful": True, "user_id": me["user"]["id"]}).status_code == 422
    assert client.put(path, json={"useful": "yes"}).status_code == 422
    assert client.put(path, json={"useful": True, "message": "a" * 1001}).status_code == 422
    with app.state.db.session(write=True) as session:
        session.get(Analysis, analysis_id).created_at = time.time() - 8 * 86400
    assert client.get(path).status_code == 404
    assert client.put(path, json={"useful": False}).status_code == 404
    missing = f"/api/analyses/{uuid.uuid4()}/feedback"
    assert client.get(missing).status_code == 404


def test_feedback_rate_capacity_and_duplicate_concurrency(backend_client, monkeypatch):
    client, app = backend_client
    me = login(client)
    bootstrap(client)
    one, two = seed_analysis(app, me), seed_analysis(app, me)
    path = f"/api/analyses/{one}/feedback"
    monkeypatch.setattr("blastradius.server.beta.FEEDBACK_LIMIT", 1)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: client.put(path, json={"useful": True}), range(6)))
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()["feedback"]["id"] for r in results}) == 1
    assert event_counts(app)["feedback_submitted"] == 1
    assert client.put(f"/api/analyses/{two}/feedback", json={"useful": False}).status_code == 503
    assert client.put(path, content=b"x" * 4097).status_code == 413
    for _ in range(22):
        assert client.put(path, json={"useful": False}).status_code == 200
    assert client.put(path, json={"useful": False}).status_code == 429


def test_platform_admin_surfaces_are_bounded_whitelisted_and_audited(operator_client):
    client, app, user_id = operator_client
    assert client.get("/api/me").json()["capabilities"]["platform_admin"] is True
    assert (
        client.post("/api/beta-interest", json={**LEAD, "problem": "Private lead"}).status_code
        == 201
    )
    me = client.get("/api/me").json()
    analysis_id = seed_analysis(app, me, "failed")
    assert (
        client.put(
            f"/api/analyses/{analysis_id}/feedback",
            json={"useful": False, "message": "Private feedback"},
        ).status_code
        == 200
    )
    for resource in RESOURCES:
        response = client.get(f"/api/admin/{resource}?limit=1")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        serialized = response.text
        for forbidden in (
            "operator@example.test",
            "Private name",
            "baseline",
            "candidate",
            "csrf_token",
            "token_hash",
            "policy_snapshot",
            "base_label",
            "result",
        ):
            assert forbidden not in serialized or forbidden == "result" and resource == "events"
        if resource not in ("beta-requests", "feedback"):
            assert "Private lead" not in serialized and "Private feedback" not in serialized
        if resource not in ("events", "plans"):
            assert len(response.json()["items"]) <= 1
        assert client.get(f"/api/admin/{resource}?limit=101").status_code == 422
        assert client.get(f"/api/admin/{resource}?offset=-1").status_code == 422
    assert client.post("/api/admin/assign-plan", json={"plan": "team"}).status_code == 404
    assert client.patch("/api/admin/organizations", json={"plan": "team"}).status_code == 405
    with app.state.db.session() as session:
        rows = list(
            session.scalars(select(AuditEvent).where(AuditEvent.action == "operator.inspect"))
        )
        assert len(rows) == len(RESOURCES)
        assert all(row.actor == user_id for row in rows)
        assert all(set(row.details) == {"limit", "offset"} for row in rows)


@pytest.mark.parametrize(
    "condition", ["unverified", "different_issuer", "unsigned", "expired", "revoked"]
)
def test_allowlist_requires_current_verified_oidc_session(operator_client, condition):
    client, app, user_id = operator_client
    with app.state.db.session(write=True) as session:
        user = session.get(User, user_id)
        login_session = session.get(LoginSession, token_hash(client.cookies.get("br_session")))
        if condition == "unverified":
            user.email_verified = False
        elif condition == "different_issuer":
            user.issuer = "https://other.example"
        elif condition == "unsigned":
            login_session.oidc_authenticated = False
        elif condition == "expired":
            login_session.expires_at = 0
        else:
            session.delete(login_session)
    assert client.get("/api/admin/users").status_code == (
        401 if condition in ("expired", "revoked") else 403
    )
    assert not client.get("/api/me").json()["capabilities"]["platform_admin"]


def test_cli_flag_alone_and_demo_allowlist_never_enable_web_admin(
    settings, demo_results, monkeypatch
):
    database = Database(settings)
    database.migrate()
    with database.session(write=True) as session:
        user = provision(session, "demo", "allowed", "", "operator@example.test", True)
        user_id = user.id
    database.engine.dispose()
    configured = replace(settings, admin_enabled=True, web_admin_user_ids=(user_id,))
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    app = create_app(configured)
    with TestClient(app):
        client = issued_client(app, user_id, True)
        me = client.get("/api/me").json()
        assert not me["capabilities"]["platform_admin"]
        assert client.get("/api/admin/users").status_code == 403


def test_signed_oidc_callback_is_required_for_operator_capability(operator_client):
    client, app, user_id = operator_client
    client.cookies.clear()
    configured = app.state.settings
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "test"})
    authorization = {}
    valid_signature = True

    def provider(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": configured.oidc_issuer,
                    "authorization_endpoint": configured.oidc_issuer + "/authorize",
                    "token_endpoint": configured.oidc_issuer + "/token",
                    "jwks_uri": configured.oidc_issuer + "/keys",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [key.as_dict(is_private=False)]})
        assert request.url.path == "/token"
        claims = {
            "iss": configured.oidc_issuer,
            "sub": "operator",
            "aud": "test",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": authorization["nonce"][0],
            "email": "operator@example.test",
            "email_verified": True,
        }
        signing_key = (
            key if valid_signature else JsonWebKey.generate_key("RSA", 2048, is_private=True)
        )
        return httpx.Response(
            200,
            json={
                "access_token": "unused-local-token",
                "token_type": "Bearer",
                "id_token": jwt.encode(
                    {"alg": "RS256", "kid": "test"}, claims, signing_key
                ).decode(),
            },
        )

    app.state.oauth.create_client("oidc").client_kwargs["transport"] = httpx.MockTransport(provider)
    for valid_signature in (False, True):
        response = client.get("/api/auth/login", follow_redirects=False)
        authorization.update(parse_qs(urlsplit(response.headers["location"]).query))
        response = client.get(
            "/api/auth/callback",
            params={
                "code": "local-code",
                "state": authorization["state"][0],
            },
            follow_redirects=False,
        )
        assert response.status_code == (303 if valid_signature else 400)
        me = client.get("/api/me").json()
        assert me["capabilities"]["platform_admin"] is valid_signature
        assert client.get("/api/admin/users").status_code == (200 if valid_signature else 401)
        if valid_signature:
            assert me["user"]["id"] == user_id


def test_oidc_token_response_cannot_supply_unsigned_operator_claims(operator_client):
    client, app, _ = operator_client
    client.cookies.clear()
    configured = app.state.settings
    authorization = {}

    def provider(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": configured.oidc_issuer,
                    "authorization_endpoint": configured.oidc_issuer + "/authorize",
                    "token_endpoint": configured.oidc_issuer + "/token",
                    "jwks_uri": configured.oidc_issuer + "/keys",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        assert request.url.path == "/token"
        return httpx.Response(
            200,
            json={
                "access_token": "unused-local-token",
                "token_type": "Bearer",
                "userinfo": {
                    "iss": configured.oidc_issuer,
                    "sub": "operator",
                    "aud": "test",
                    "nonce": authorization["nonce"][0],
                    "email": "operator@example.test",
                    "email_verified": True,
                },
            },
        )

    app.state.oauth.create_client("oidc").client_kwargs["transport"] = httpx.MockTransport(provider)
    response = client.get("/api/auth/login", follow_redirects=False)
    authorization.update(parse_qs(urlsplit(response.headers["location"]).query))
    response = client.get(
        "/api/auth/callback",
        params={"code": "local-code", "state": authorization["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 400
    me = client.get("/api/me").json()
    assert not me["authenticated"]
    assert not me["capabilities"]["platform_admin"]
    assert client.get("/api/admin/users").status_code == 401


def test_event_allowlist_atomic_finish_retry_and_failure_never_safe(
    backend_client, demo_results, monkeypatch
):
    client, app = backend_client
    me = login(client)
    analysis_id = seed_analysis(app, me, "running")
    original_session = app.state.db.session
    attempts = 0

    @contextmanager
    def transient_commit_failure(write=False):
        nonlocal attempts
        with original_session(write=write) as session:
            yield session
            if write and attempts == 0:
                attempts += 1
                raise OperationalError("synthetic", {}, Exception("test failure"))

    monkeypatch.setattr(app.state.db, "session", transient_commit_failure)
    result = demo_results[("public_ssh", "safe")]
    assert app.state.jobs.finish(analysis_id, {"result": result}) == "failed"
    assert app.state.jobs.finish(analysis_id, {"result": result}) == "deleted_or_terminal"
    with original_session() as session:
        job = session.get(Analysis, analysis_id)
        assert job.status == "failed" and job.result is None and job.decision is None
    counts = event_counts(app)
    assert counts["analysis_failed"] == 1
    assert counts["analysis_completed"] == counts["safe_result"] == 0
    with pytest.raises(ValueError, match="unknown_product_event"):
        with original_session(write=True) as session:
            record_event(session, "untrusted:" + LEAD["email"])


def test_terminal_events_are_once_under_concurrent_finish(backend_client, demo_results):
    client, app = backend_client
    me = login(client)
    analysis_id = seed_analysis(app, me, "running")
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(
            pool.map(
                lambda _: app.state.jobs.finish(
                    analysis_id, {"result": demo_results[("public_ssh", "safe")]}
                ),
                range(4),
            )
        )
    assert states.count("succeeded") == 1 and states.count("deleted_or_terminal") == 3
    counts = event_counts(app)
    assert counts["analysis_completed"] == counts["safe_result"] == 1
    assert counts["analysis_failed"] == 0


def test_milestones_match_server_actions_not_browser_posts(backend_client):
    client, app = backend_client
    me = login(client)
    proj = project(client, me)
    job = terminal(client, submit(client, proj["id"]).json()["id"])
    assert job["status"] == "succeeded"
    assert client.get(f"/api/analyses/{job['id']}/report?format=web").status_code == 200
    assert client.get(f"/api/analyses/{job['id']}/report?format=json").status_code == 200
    counts = event_counts(app)
    assert all(
        counts[name] == 1
        for name in (
            "account_created",
            "workspace_created",
            "project_created",
            "analysis_started",
            "analysis_completed",
            "block_result",
            "report_exported",
        )
    )
    assert counts["safe_result"] == counts["analysis_failed"] == 0
    assert client.post("/api/events", json={"name": "safe_result"}).status_code == 404
    with app.state.db.session() as session:
        for row in session.scalars(select(ProductEvent)):
            assert row.name in EVENT_NAMES
            for value in (row.user_id, row.organization_id, row.project_id, row.analysis_id):
                assert value is None or str(uuid.UUID(value)) == value


def test_retention_bounded_cleanup_and_cascades(backend_client, monkeypatch):
    client, app = backend_client
    me = login(client)
    bootstrap(client)
    analysis_id = seed_analysis(app, me)
    assert client.post("/api/beta-interest", json=LEAD).status_code == 201
    assert (
        client.put(f"/api/analyses/{analysis_id}/feedback", json={"useful": True}).status_code
        == 200
    )
    with app.state.db.session(write=True) as session:
        for model in (BetaInterest, AnalysisFeedback, ProductEvent):
            for row in session.scalars(select(model)):
                row.created_at = time.time() - 91 * 86400
    removed = cleanup_commercial(app.state.db, 1)
    assert removed == {"beta_interest": 1, "analysis_feedback": 1, "product_events": 1}
    monkeypatch.setattr("blastradius.server.events.EVENT_LIMIT", 3)
    with app.state.db.session(write=True) as session:
        session.execute(delete(ProductEvent))
        for _ in range(8):
            record_event(
                session,
                "project_created",
                user_id=me["user"]["id"],
                organization_id=me["organizations"][0]["id"],
            )
        assert session.scalar(select(func.count()).select_from(ProductEvent)) == 3
    assert (
        client.put(f"/api/analyses/{analysis_id}/feedback", json={"useful": False}).status_code
        == 200
    )
    assert client.delete(f"/api/analyses/{analysis_id}").status_code == 204
    with app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisFeedback)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProductEvent)
                .where(ProductEvent.analysis_id == analysis_id)
            )
            == 0
        )


def test_upgrade_and_restart_persist_data_and_recovery_once(
    migration_database, settings, demo_results, monkeypatch
):
    database = migration_database
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0003")
    database.migrate()
    database.migrate()
    with database.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    with database.session() as session:
        assert session.get(CommercialLock, 1)
    configured = replace(
        settings, database_url=database.engine.url.render_as_string(hide_password=False)
    )
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    app = create_app(configured)
    with TestClient(app) as client:
        me = login(client)
        bootstrap(client)
        analysis_id = seed_analysis(app, me)
        unfinished = seed_analysis(app, me, "running")
        feedback = client.put(
            f"/api/analyses/{analysis_id}/feedback",
            json={"useful": False, "message": "Persisted observation"},
        ).json()
        assert client.post("/api/beta-interest", json=LEAD).status_code == 201
        cookie = client.cookies.get("br_session")
    restarted = create_app(configured)
    with TestClient(restarted) as client:
        client.cookies.set("br_session", cookie)
        assert client.get(f"/api/analyses/{analysis_id}/feedback").json() == feedback
        with restarted.state.db.session() as session:
            assert session.scalar(select(BetaInterest)).email == LEAD["email"]
            assert session.get(Analysis, unfinished).status == "failed"
        restarted.state.jobs.recover()
        assert event_counts(restarted)["analysis_failed"] == 1


def test_cli_inspection_and_cleanup_are_bounded(operator_client, monkeypatch, capsys):
    client, app, _ = operator_client
    assert client.post("/api/beta-interest", json=LEAD).status_code == 201
    monkeypatch.setattr(
        Settings,
        "from_env",
        classmethod(lambda cls: replace(app.state.settings, admin_enabled=True)),
    )
    for resource in RESOURCES:
        assert admin_main(["inspect", resource, "--limit", "1"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, dict if resource in ("plans", "events") else list)
        if resource == "users":
            assert set(data[0]) == {"id", "name", "email", "email_verified"}
        if resource in ("organizations", "usage"):
            assert "name" in data[0] and "created_at" not in data[0]
    assert admin_main(["cleanup-commercial", "--limit", "1"]) == 0
    assert "removed" in json.loads(capsys.readouterr().out)
    with pytest.raises(SystemExit):
        admin_main(["inspect", "users", "--limit", "1001"])
    with pytest.raises(SystemExit):
        admin_main(["cleanup-commercial", "--limit", "1001"])
    limits = client.get("/api/admin/plans").json()
    expected = {"free": (1, 25, 7), "pro": (5, 500, 90), "team": (25, 5000, 365)}
    for plan in limits["plans"]:
        if plan["code"] in expected:
            assert (
                tuple(
                    plan["limits"][key]
                    for key in ("projects", "analyses_per_month", "retention_days")
                )
                == expected[plan["code"]]
            )
    assert not limits["payments_enabled"]


def test_admin_failure_redaction_retention_and_pagination(operator_client):
    client, app, _ = operator_client
    me = client.get("/api/me").json()
    analysis_id = seed_analysis(app, me, "failed")
    with app.state.db.session(write=True) as session:
        session.get(Analysis, analysis_id).error = "PRIVATE-TOKEN-in-worker-error"
    failures = client.get("/api/admin/failures").json()["items"]
    assert failures[0]["error"] == "analysis_failed"
    assert "PRIVATE-TOKEN" not in json.dumps(failures)
    for _ in range(2):
        assert client.post("/api/beta-interest", json=LEAD).status_code == 201
    page = client.get("/api/admin/beta-requests?limit=1").json()
    assert page["next_offset"] == 1
    next_page = client.get("/api/admin/beta-requests?limit=1&offset=1").json()
    assert page["items"][0]["id"] != next_page["items"][0]["id"]
    with app.state.db.session(write=True) as session:
        for row in session.scalars(select(BetaInterest)):
            row.created_at = time.time() - 91 * 86400
    assert client.get("/api/admin/beta-requests").json()["items"] == []


@pytest.mark.parametrize("model", [User, Organization, Project])
def test_commercial_foreign_keys_cascade_without_touching_leads(backend_client, model):
    client, app = backend_client
    me = login(client)
    bootstrap(client)
    analysis_id = seed_analysis(app, me)
    actor, actor_id = identity_client(app, org_id=me["organizations"][0]["id"], role="viewer")
    bootstrap(actor)
    assert (
        actor.put(f"/api/analyses/{analysis_id}/feedback", json={"useful": True}).status_code
        == 200
    )
    assert client.post("/api/beta-interest", json=LEAD).status_code == 201
    with app.state.db.session(write=True) as session:
        job = session.get(Analysis, analysis_id)
        target = {
            User: actor_id,
            Organization: me["organizations"][0]["id"],
            Project: job.project_id,
        }[model]
        session.execute(delete(model).where(model.id == target))
    with app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisFeedback)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProductEvent)
                .where(
                    ProductEvent.name == "feedback_submitted",
                )
            )
            == 0
        )
        assert session.scalar(select(func.count()).select_from(BetaInterest)) == 1
        if model is User:
            assert session.get(Analysis, analysis_id)


def test_populated_legacy_session_upgrade_and_downgrade(migration_database):
    database = migration_database
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0003")
        connection.execute(
            text(
                "INSERT INTO sessions (token_hash,user_id,csrf_token,expires_at)"
                " VALUES ('legacy-session',NULL,'legacy-csrf',9999999999)"
            )
        )
    database.migrate()
    with database.session() as session:
        assert not session.get(LoginSession, "legacy-session").oidc_authenticated
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0003")
        assert (
            connection.execute(
                text("SELECT csrf_token FROM sessions WHERE token_hash='legacy-session'")
            ).scalar()
            == "legacy-csrf"
        )
    database.migrate()
    with database.session() as session:
        assert session.get(CommercialLock, 1)
        assert not session.get(LoginSession, "legacy-session").oidc_authenticated


def test_feedback_anonymous_origin_and_expiration(backend_client):
    client, app = backend_client
    me = login(client)
    analysis_id = seed_analysis(app, me)
    path = f"/api/analyses/{analysis_id}/feedback"
    anonymous = TestClient(app)
    bootstrap(anonymous)
    assert anonymous.get(path).status_code == 401
    assert anonymous.put(path, json={"useful": True}).status_code == 401
    client.headers.pop("Origin", None)
    assert client.put(path, json={"useful": True}).status_code == 403
    bootstrap(client)
    assert client.put(path, json={"useful": True}).status_code == 200
    with app.state.db.session(write=True) as session:
        session.scalar(select(AnalysisFeedback)).created_at = time.time() - 91 * 86400
    assert client.get(path).json() == {"feedback": None}
    assert client.put(path, json={"useful": True}).status_code == 409
    assert cleanup_commercial(app.state.db)["analysis_feedback"] == 1
    assert client.put(path, json={"useful": False}).status_code == 200


@pytest.mark.parametrize(
    "ids",
    [
        ("not-an-id",),
        (str(uuid.uuid4()).upper(),),
        tuple(str(uuid.uuid4()) for _ in range(51)),
    ],
)
def test_web_admin_configuration_rejects_invalid_uuid_allowlists(settings, ids):
    with pytest.raises(ValueError):
        replace(settings, web_admin_user_ids=ids).validate()
