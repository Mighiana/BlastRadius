from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastapi", reason="install .[server,dev] for backend tests")
pytest.importorskip("sqlalchemy", reason="install .[server,dev] for backend tests")
pytest.importorskip("stripe", reason="install .[server,dev] for backend tests")

import httpx
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from authlib.jose import JsonWebKey, jwt
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from blastradius.server.app import create_app
from blastradius.server.auth import create_session, provision
from blastradius.server.billing import StripeGateway, safe_provider_url
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.demos import build_demos
from blastradius.server.fixtures import FIXTURES
from blastradius.server.jobs import JobManager, execute
from blastradius.server.lease import ServiceLease
from blastradius.server.models import (
    Analysis,
    Base,
    BillingEvent,
    LoginSession,
    Organization,
    Project,
    Usage,
)
from blastradius.server.quotas import lock_org, period, quota
from blastradius.server.schemas import AnalysisInput


@pytest.fixture(scope="session")
def demo_results(tmp_path_factory):
    return build_demos(Settings(data_dir=tmp_path_factory.mktemp("demo-worker")))


@pytest.fixture
def settings(tmp_path):
    return Settings(
        environment="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        public_url="http://testserver",
        auth_mode="demo",
        rate_limit=1000,
    )


@pytest.fixture
def app(settings, demo_results, monkeypatch):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def login(client):
    anonymous = client.get("/api/me").json()
    response = client.post(
        "/api/auth/demo", headers={"X-CSRF-Token": anonymous["csrf_token"]}
    )
    assert response.status_code == 200
    me = client.get("/api/me").json()
    client.headers["X-CSRF-Token"] = me["csrf_token"]
    return me


def project(client, me):
    response = client.post(
        "/api/projects",
        json={
            "name": "Infrastructure",
            "organization_id": me["organizations"][0]["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit(client, project_id, **updates):
    scenario = FIXTURES["public_ssh"]
    payload = {
        "project_id": project_id,
        "before_files": scenario["before_files"],
        "after_files": scenario["after_files"],
    }
    payload.update(updates)
    return client.post("/api/analyses", json=payload)


def terminal(client, analysis_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = client.get(f"/api/analyses/{analysis_id}").json()
        if result["status"] not in {"queued", "running"}:
            return result
        threading.Event().wait(0.02)
    pytest.fail("Analysis did not finish")


def test_real_demo_fixtures_are_safe_risky_and_remediated(client, demo_results):
    scenarios = client.get("/api/demo/scenarios").json()["scenarios"]
    assert {s["id"] for s in scenarios} == {"public_ssh", "broad_iam", "public_bucket"}
    for scenario in scenarios:
        for stage in scenario["stages"]:
            response = client.get(f"/api/demo/{scenario['id']}?stage={stage}")
            assert response.status_code == 200
            report = response.json()
            assert report == demo_results[(scenario["id"], stage)]
            assert report["passed"] == (stage != "risky")
            baseline_score = demo_results[(scenario["id"], "safe")]["score"]["after"]
            if stage == "risky":
                assert report["score"]["after"] < baseline_score
                assert report["new_critical_paths"]
            else:
                assert report["score"]["after"] == baseline_score
                assert not report["new_critical_paths"]
            assert report["after"]["graph"]["nodes"]
            assert all(
                "reason" in edge and "evidence" in edge
                for edge in report["after"]["graph"]["edges"]
            )
            assert "/job-" not in json.dumps(report)
            assert (
                report == client.get(f"/api/demo/{scenario['id']}?stage={stage}").json()
            )
    assert client.get("/api/demo/nope").status_code == 404
    assert client.get("/api/demo/public_ssh?stage=nope").status_code == 422
    assert (
        client.post(
            "/api/analyses",
            json={
                "project_id": "demo",
                "before_files": {"a.tf": ""},
                "after_files": {"a.tf": ""},
            },
        ).status_code
        == 403
    )


def test_auth_rotation_csrf_and_hash_at_rest(client, app):
    anonymous = client.get("/api/me")
    original_cookie = client.cookies["br_session"]
    assert (
        "HttpOnly" in anonymous.headers["set-cookie"]
        and "SameSite=lax" in anonymous.headers["set-cookie"]
    )
    token = anonymous.json()["csrf_token"]
    assert not anonymous.json()["authenticated"]
    assert client.post("/api/auth/demo").status_code == 403
    assert (
        client.post("/api/auth/demo", headers=[(b"X-CSRF-Token", b"\xff")]).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/demo",
            headers={"X-CSRF-Token": token, "Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/demo",
            headers={"X-CSRF-Token": token, "Sec-Fetch-Site": "cross-site"},
        ).status_code
        == 403
    )
    me = login(client)
    assert me["authenticated"] and len(me["organizations"]) == 1
    assert client.cookies["br_session"] != original_cookie
    assert me["csrf_token"] != token
    with app.state.db.session() as db:
        sessions = list(db.scalars(select(LoginSession)))
        assert len(sessions) == 1
        assert sessions[0].token_hash != client.cookies["br_session"]
    assert (
        client.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code
        == 403
    )
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/projects").status_code == 401


def test_cookie_secure_in_production_and_expired_sessions_fail(client, app, settings):
    login(client)
    with app.state.db.session(write=True) as db:
        for session in db.scalars(select(LoginSession)):
            session.expires_at = time.time() - 1
        response = Response()
        create_session(response, db, replace(settings, environment="production"))
        assert "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=lax" in response.headers["set-cookie"]
    assert client.get("/api/projects").status_code == 401


def test_disabled_auth_still_serves_demo(settings, demo_results, monkeypatch):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    with TestClient(create_app(replace(settings, auth_mode="disabled"))) as client:
        me = client.get("/api/me").json()
        assert me["auth"] == {"enabled": False, "mode": "disabled", "login_url": None}
        assert me["billing"] == {"enabled": False, "test_mode": True}
        assert client.get("/api/projects").status_code == 503
        assert client.post("/api/auth/demo").status_code == 404
        assert client.get("/api/auth/login").status_code == 503
        assert client.get("/api/auth/callback").status_code == 503
        assert client.get("/api/demo/public_ssh").status_code == 200


@pytest.mark.parametrize(
    "updates",
    [
        {"environment": "production"},
        {"environment": "prd"},
        {"auth_mode": "invalid"},
        {"public_url": "https://x.example/callback"},
        {"public_url": "https://user:password@x.example"},
        {"auth_mode": "oidc"},
        {"stripe_secret_key": "sk_live_forbidden"},
        {"max_jobs": 0},
        {"workers": 10, "max_jobs": 1},
    ],
)
def test_config_rejects_unsafe_and_incomplete_settings(settings, updates):
    with pytest.raises(ValueError):
        replace(settings, **updates).validate()


def test_production_requires_explicit_environment_secret(monkeypatch):
    variables = {
        "BR_ENV": "production",
        "BR_DATABASE_URL": "postgresql+psycopg://localhost/br",
        "BR_PUBLIC_URL": "https://app.example",
        "BR_AUTH_MODE": "oidc",
        "BR_OIDC_ISSUER": "https://issuer.example",
        "BR_OIDC_CLIENT_ID": "client",
        "BR_OIDC_CLIENT_SECRET": "test-client-secret",
    }
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("BR_SESSION_SECRET", raising=False)
    with pytest.raises(ValueError):
        Settings.from_env()
    monkeypatch.setenv("BR_SESSION_SECRET", "a" * 48)
    settings = Settings.from_env()
    assert settings.production and not settings.auto_migrate
    with pytest.raises(ValueError):
        replace(settings, auto_migrate=True).validate()
    with pytest.raises(ValueError):
        replace(settings, auth_mode="demo").validate()


def test_oidc_redirect_uses_state_nonce_pkce_and_rejects_invalid_state(
    settings, demo_results, monkeypatch
):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    settings = replace(
        settings,
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        oidc_client_secret="test",
    )
    app = create_app(settings)
    oauth = app.state.oauth.create_client("oidc")
    oauth.server_metadata.update(
        {
            "issuer": settings.oidc_issuer,
            "_loaded_at": time.time(),
            "authorization_endpoint": "https://issuer.example/authorize",
            "token_endpoint": "https://issuer.example/token",
        }
    )
    with TestClient(app) as client:
        response = client.get("/api/auth/login", follow_redirects=False)
        params = parse_qs(urlsplit(response.headers["location"]).query)
        assert response.status_code == 302
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert params["state"] and params["nonce"] and params["code_challenge"]
        assert params["redirect_uri"] == ["http://testserver/api/auth/callback"]
        assert "code_verifier" not in params
        assert (
            client.get("/api/auth/callback?code=invalid&state=wrong").status_code == 400
        )
        assert not client.get("/api/me").json()["authenticated"]


@pytest.mark.parametrize(
    "invalid",
    [None, "signature", "nonce", "issuer", "audience", "expiry", "nonce_supported"],
)
def test_oidc_callback_verifies_signed_claims(
    settings, demo_results, monkeypatch, invalid
):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    settings = replace(
        settings,
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        oidc_client_secret="test",
    )
    key = JsonWebKey.generate_key(
        "RSA", 2048, is_private=True, options={"kid": "local"}
    )
    params = {}
    token_requests = []

    def transport(request):
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
            return httpx.Response(200, json={"keys": [key.as_dict(is_private=False)]})
        assert request.url.path == "/token"
        form = parse_qs(request.content.decode())
        token_requests.append(form)
        assert form["code"] == ["test-code"] and len(form["code_verifier"][0]) >= 43
        claims = {
            "iss": settings.oidc_issuer,
            "sub": "stable-subject",
            "aud": "client",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": params["nonce"][0],
            "email": "test@example.invalid",
            "email_verified": True,
            "name": "Test User",
        }
        if invalid in {"nonce", "nonce_supported"}:
            claims["nonce"] = "wrong"
        if invalid == "nonce_supported":
            claims["nonce_supported"] = False
        if invalid == "issuer":
            claims["iss"] = "https://evil.example"
        if invalid == "audience":
            claims["aud"] = "another-client"
        if invalid == "expiry":
            claims["exp"] = int(time.time()) - 600
        signing_key = (
            JsonWebKey.generate_key("RSA", 2048, is_private=True)
            if invalid == "signature"
            else key
        )
        encoded = jwt.encode(
            {"alg": "RS256", "kid": "local"}, claims, signing_key
        ).decode()
        return httpx.Response(
            200,
            json={
                "access_token": "test-access-token",
                "token_type": "Bearer",
                "id_token": encoded,
            },
        )

    app = create_app(settings)
    app.state.oauth.create_client("oidc").client_kwargs["transport"] = (
        httpx.MockTransport(transport)
    )
    with TestClient(app) as client:
        response = client.get("/api/auth/login", follow_redirects=False)
        params.update(parse_qs(urlsplit(response.headers["location"]).query))
        response = client.get(
            "/api/auth/callback",
            params={"code": "test-code", "state": params["state"][0]},
            follow_redirects=False,
        )
        assert response.status_code == (400 if invalid else 303)
        assert len(token_requests) == 1
        me = client.get("/api/me").json()
        assert me["authenticated"] == (invalid is None)
        if invalid is None:
            assert me["user"]["email"] == "test@example.invalid"
            assert me["organizations"][0]["role"] == "owner"


def test_tenant_isolation_reports_history_and_mutations(client, app):
    me = login(client)
    proj = project(client, me)
    submitted = submit(client, proj["id"])
    assert submitted.status_code == 202
    analysis_id = submitted.json()["id"]
    job = terminal(client, analysis_id)
    assert job["status"] == "succeeded", job
    assert job["result"]["passed"] is False
    assert job["created_at"] <= job["started_at"] <= job["completed_at"]
    for kind in ("web", "json", "markdown", "sarif"):
        assert (
            client.get(f"/api/analyses/{analysis_id}/report?format={kind}").status_code
            == 200
        )
    history = client.get(f"/api/projects/{proj['id']}/analyses").json()["analyses"]
    assert (
        len(history) == 1
        and "result" not in history[0]
        and history[0]["summary"]["decision"] == job["result"]["decision"]
    )
    stranger = TestClient(app)
    other = login(stranger)
    assert other["organizations"][0]["id"] != me["organizations"][0]["id"]
    assert stranger.get("/api/projects").json() == {"projects": []}
    for url in (
        f"/api/analyses/{analysis_id}",
        f"/api/analyses/{analysis_id}/report?format=sarif",
        f"/api/projects/{proj['id']}/analyses",
        f"/api/projects?organization_id={proj['organization_id']}",
        f"/api/organizations/{proj['organization_id']}/billing",
        f"/api/organizations/{proj['organization_id']}/members",
    ):
        assert stranger.get(url).status_code == 404
    assert stranger.delete(f"/api/analyses/{analysis_id}").status_code == 404
    assert stranger.delete(f"/api/projects/{proj['id']}").status_code == 404
    assert submit(stranger, proj["id"]).status_code == 404
    assert (
        stranger.post(
            "/api/projects",
            json={"organization_id": proj["organization_id"], "name": "IDOR"},
        ).status_code
        == 404
    )
    assert (
        stranger.post(
            f"/api/organizations/{proj['organization_id']}/billing/checkout",
            json={"plan": "pro"},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/analyses/{analysis_id}").status_code == 204
    assert client.get(f"/api/analyses/{analysis_id}/report").status_code == 404
    assert client.get("/api/me").json()["organizations"][0]["usage"]["analyses"] == 1
    assert not list((app.state.settings.data_dir / "jobs").iterdir())


def test_role_enforcement_and_no_owner_grant(client, app):
    owner = login(client)
    org_id = owner["organizations"][0]["id"]
    proj = project(client, owner)
    viewer_client = TestClient(app)
    viewer = login(viewer_client)
    user_id = viewer["user"]["id"]
    member_url = f"/api/organizations/{org_id}/members"
    assert (
        client.post(member_url, json={"user_id": user_id, "role": "owner"}).status_code
        == 422
    )
    assert (
        client.post(member_url, json={"user_id": user_id, "role": "viewer"}).status_code
        == 402
    )
    with app.state.db.session(write=True) as db:
        db.get(Organization, org_id).plan = "pro"
    assert (
        client.post(member_url, json={"user_id": user_id, "role": "viewer"}).status_code
        == 201
    )
    assert viewer_client.get(f"/api/projects/{proj['id']}/analyses").status_code == 200
    assert submit(viewer_client, proj["id"]).status_code == 403
    assert viewer_client.delete(f"/api/projects/{proj['id']}").status_code == 403
    assert viewer_client.get(f"/api/organizations/{org_id}/billing").status_code == 403
    assert (
        viewer_client.post(
            member_url, json={"user_id": owner["user"]["id"]}
        ).status_code
        == 403
    )
    assert client.delete(member_url + "/" + owner["user"]["id"]).status_code == 409
    assert client.delete(member_url + "/" + user_id).status_code == 204
    assert viewer_client.get(f"/api/projects/{proj['id']}/analyses").status_code == 404
    created = viewer_client.post(
        "/api/organizations", json={"name": "My second workspace"}
    ).json()
    assert created["role"] == "owner" and created["plan"] == "free"
    assert client.get(f"/api/organizations/{created['id']}/members").status_code == 404


@pytest.mark.parametrize(
    "updates",
    [
        {"before_files": {"../escape.tf": "resource"}},
        {"after_files": {"/host/secrets.tf": ""}},
        {"after_files": {"main.tf": "\x00"}},
        {"repo_url": "https://example.invalid/private"},
        {"path": "/etc/passwd"},
        {"plan": {"planned_values": {}}},
        {"after_files": {}},
        {"before_files": {"a.tf": 12}},
    ],
)
def test_submission_rejects_unsafe_and_malformed_inputs(client, updates):
    proj = project(client, login(client))
    assert submit(client, proj["id"], **updates).status_code == 422


def test_parser_failure_and_plan_input_are_persisted(client):
    proj = project(client, login(client))
    bad = submit(
        client, proj["id"], after_files={"main.tf": 'resource "aws_instance" "a" {'}
    )
    assert terminal(client, bad.json()["id"])["status"] == "failed"
    plan = json.loads(
        (Path(__file__).parents[1] / "examples/plans/ssh_open_plan.json").read_text()
    )
    response = client.post(
        "/api/analyses", json={"project_id": proj["id"], "plan": plan}
    )
    job = terminal(client, response.json()["id"])
    assert job["status"] == "succeeded" and not job["result"]["passed"]
    assert job["result"]["remediation"]["patched_files"] == {}
    assert client.get("/api/me").json()["organizations"][0]["usage"]["analyses"] == 2


def test_body_file_resource_limits_and_sanitized_errors(
    client, app, monkeypatch, caplog
):
    proj = project(client, login(client))
    assert (
        submit(
            client, proj["id"], before_files={f"f{index}.tf": "" for index in range(31)}
        ).status_code
        == 413
    )
    response = client.post(
        "/api/analyses", content=b"x" * (app.state.settings.max_body_bytes + 1)
    )
    assert response.status_code == 413
    assert (
        response.headers["x-request-id"]
        and response.headers["cache-control"] == "no-store"
    )
    assert (
        client.post(
            "/api/analyses", content=b"{}", headers={"content-encoding": "gzip"}
        ).status_code
        == 415
    )
    assert client.post(
        "/api/analyses",
        content="{private-secret",
        headers={"content-type": "application/json"},
    ).json() == {"detail": "invalid_request"}
    payload = AnalysisInput(
        project_id="test",
        before_files=FIXTURES["public_ssh"]["before_files"],
        after_files=FIXTURES["public_ssh"]["after_files"],
    )
    result = execute(payload, replace(app.state.settings, max_resources=1))
    assert result == {"error": "resource_limit_exceeded"}
    monkeypatch.setattr(
        "blastradius.server.app.usage_payload",
        lambda *_: (_ for _ in ()).throw(ValueError("private-secret")),
    )
    with caplog.at_level(logging.INFO, logger="blastradius.http"):
        response = client.get("/api/me")
    assert response.status_code == 500 and response.json() == {
        "detail": "internal_error"
    }
    assert response.headers["x-request-id"]
    assert "private-secret" not in caplog.text


def test_rate_limits_separate_demo_auth_and_general(
    settings, demo_results, monkeypatch
):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    with TestClient(
        create_app(
            replace(settings, demo_rate_limit=1, auth_rate_limit=1, rate_limit=2)
        )
    ) as client:
        assert client.get("/api/demo/public_ssh").status_code == 200
        assert client.get("/api/demo/public_ssh").status_code == 429
        assert client.get("/api/auth/login").status_code == 503
        assert client.get("/api/auth/login").status_code == 429
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert client.get("/health/live").status_code == 429


def test_quota_capacity_and_deleted_running_jobs(client, app, monkeypatch):
    me = login(client)
    proj = project(client, me)
    for _ in range(2):
        project(client, me)
    assert (
        client.post(
            "/api/projects",
            json={"name": "Fourth", "organization_id": proj["organization_id"]},
        ).status_code
        == 402
    )
    manager = app.state.jobs
    reservations = [manager.reserve() for _ in range(app.state.settings.max_jobs)]
    assert all(reservations)
    assert submit(client, proj["id"]).status_code == 429
    assert client.get("/api/me").json()["organizations"][0]["usage"]["analyses"] == 0
    for _ in reservations:
        manager.slots.release()
    with app.state.db.session(write=True) as db:
        db.add(
            Usage(organization_id=proj["organization_id"], period=period(), analyses=20)
        )
    assert submit(client, proj["id"]).status_code == 402
    with app.state.db.session(write=True) as db:
        db.get(Usage, (proj["organization_id"], period())).analyses = 0
    started, proceed = threading.Event(), threading.Event()

    def delayed(*_):
        started.set()
        assert proceed.wait(5)
        return {"error": "test_failure"}

    monkeypatch.setattr("blastradius.server.jobs.execute", delayed)
    try:
        response = submit(client, proj["id"])
        assert response.status_code == 202 and started.wait(3)
        assert (
            client.get(f"/api/analyses/{response.json()['id']}/report").status_code
            == 409
        )
        assert client.delete(f"/api/projects/{proj['id']}").status_code == 204
    finally:
        proceed.set()
        manager.shutdown()
    assert client.get(f"/api/analyses/{response.json()['id']}").status_code == 404


def test_migrations_and_restart_recovery(settings):
    db = Database(settings)
    assert not db.ready()
    db.migrate()
    db.migrate()
    assert db.ready()
    assert {
        "users",
        "memberships",
        "projects",
        "analyses",
        "usage",
        "billing_events",
    } <= set(inspect(db.engine).get_table_names())
    with db.session(write=True) as session:
        user = provision(session, "test", "subject", "Tester", "")
        assert provision(session, "test", "subject", "Tester", "").id == user.id
        org = session.scalar(select(Organization))
        proj = Project(organization_id=org.id, name="Test")
        session.add(proj)
        session.flush()
        job = Analysis(
            project_id=proj.id,
            organization_id=org.id,
            created_by=user.id,
            base_label="a",
            candidate_label="b",
        )
        session.add(job)
        session.flush()
        analysis_id = job.id
    abandoned = settings.data_dir / "jobs" / "job-abandoned"
    abandoned.mkdir(parents=True)
    (abandoned / "input.json").write_text("sensitive")
    manager = JobManager(db, settings)
    manager.recover()
    with db.session() as session:
        job = session.get(Analysis, analysis_id)
        assert job.status == "failed" and job.error == "server_restarted"
    assert not abandoned.exists()
    lease = ServiceLease(db, settings.data_dir)
    lease.acquire()
    with pytest.raises(RuntimeError, match="Only one"):
        ServiceLease(db, settings.data_dir).acquire()
    lease.release()
    manager.shutdown()
    db.engine.dispose()


def test_worker_timeout_cleans_up(settings, monkeypatch):
    def timeout(*args, **kwargs):
        assert "-I" in args[0]
        assert set(kwargs["env"]) == {"PATH", "PYTHONHASHSEED"}
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr("blastradius.server.jobs.subprocess.run", timeout)
    payload = AnalysisInput(
        project_id="test", before_files={"a.tf": ""}, after_files={"a.tf": ""}
    )
    assert execute(payload, settings) == {"error": "analysis_timeout"}
    assert not list((settings.data_dir / "jobs").iterdir())


class FakeGateway:
    def __init__(self):
        self.customers: list[str] = []
        self.checkouts: list[tuple[str, str, str]] = []
        self.portals: list[tuple[str, str]] = []

    def customer(self, organization_id):
        self.customers.append(organization_id)
        return "cus_" + organization_id

    def checkout(self, customer_id, price, return_url):
        self.checkouts.append((customer_id, price, return_url))
        return "https://checkout.stripe.com/test"

    def portal(self, customer_id, return_url):
        self.portals.append((customer_id, return_url))
        return "https://billing.stripe.com/test"


def sign(body: bytes, secret: str, timestamp: int | None = None) -> str:
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(
        secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def event(customer, event_id="evt_test", created=100, status="active"):
    return {
        "id": event_id,
        "object": "event",
        "type": "customer.subscription.updated",
        "livemode": False,
        "created": created,
        "data": {
            "object": {
                "id": "sub_test",
                "object": "subscription",
                "livemode": False,
                "customer": customer,
                "status": status,
                "items": {
                    "data": [
                        {"quantity": 1, "price": {"id": "price_pro", "livemode": False}}
                    ]
                },
            }
        },
    }


@pytest.fixture
def billing_client(settings, demo_results, monkeypatch):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    settings = replace(
        settings,
        stripe_secret_key="sk_test_not_a_real_key",
        stripe_webhook_secret="whsec_local_test",
        stripe_price_pro="price_pro",
        stripe_price_team="price_team",
    )
    gateway = FakeGateway()
    app = create_app(settings, gateway=gateway)
    with TestClient(app) as client:
        yield client, settings, gateway


def send_event(client, settings, payload, *, timestamp=None, secret=None):
    body = json.dumps(payload).encode()
    return client.post(
        "/api/billing/webhook",
        content=body,
        headers={
            "Stripe-Signature": sign(
                body, secret or settings.stripe_webhook_secret, timestamp
            )
        },
    )


def test_billing_signed_events_replay_and_quota_updates(billing_client):
    client, settings, gateway = billing_client
    me = login(client)
    org_id = me["organizations"][0]["id"]
    url = f"/api/organizations/{org_id}/billing"
    assert (
        client.post(url + "/checkout", json={"plan": "enterprise"}).status_code == 422
    )
    assert (
        client.post(
            url + "/checkout",
            json={"plan": "pro", "return_url": "https://evil.example"},
        ).status_code
        == 422
    )
    assert client.post(url + "/checkout", json={"plan": "pro"}).status_code == 200
    assert gateway.checkouts == [
        ("cus_" + org_id, "price_pro", "http://testserver/billing")
    ]
    assert client.get(url).json()["plan"] == "free"
    payload = event("cus_" + org_id)
    assert send_event(client, settings, payload).status_code == 200
    assert client.get(url).json()["usage"]["limits"]["analyses_per_month"] == 500
    assert send_event(client, settings, payload).json()["duplicate"] is True
    assert client.post(url + "/checkout", json={"plan": "team"}).status_code == 409
    assert client.post(url + "/portal").status_code == 200
    assert gateway.portals == [("cus_" + org_id, "http://testserver/billing")]
    assert (
        send_event(
            client,
            settings,
            event("cus_" + org_id, "evt_old", created=99, status="canceled"),
        ).json()["stale"]
        is True
    )
    assert client.get(url).json()["plan"] == "pro"
    assert (
        send_event(
            client,
            settings,
            event("cus_" + org_id, "evt_cancel", created=101, status="canceled"),
        ).status_code
        == 200
    )
    assert client.get(url).json()["usage"]["limits"]["analyses_per_month"] == 20
    with client.app.state.db.session() as db:
        assert len(list(db.scalars(select(BillingEvent)))) == 3


@pytest.mark.parametrize(
    "kind",
    [
        "signature",
        "expired",
        "future",
        "live",
        "object_live",
        "customer",
        "price",
        "subscription",
        "quantity",
    ],
)
def test_billing_rejects_forgery_and_untrusted_mapping(billing_client, kind):
    client, settings, _ = billing_client
    me = login(client)
    org_id = me["organizations"][0]["id"]
    url = f"/api/organizations/{org_id}/billing"
    assert client.post(url + "/checkout", json={"plan": "pro"}).status_code == 200
    payload = event("cus_" + org_id)
    timestamp, secret = None, None
    obj = payload["data"]["object"]
    if kind == "signature":
        secret = "whsec_forged"
    elif kind in {"expired", "future"}:
        timestamp = int(time.time()) + (600 if kind == "future" else -600)
    elif kind == "live":
        payload["livemode"] = True
    elif kind == "object_live":
        obj["livemode"] = True
    elif kind == "customer":
        obj["customer"] = "cus_unknown"
        obj["metadata"] = {"blastradius_organization": org_id}
    elif kind == "price":
        obj["items"]["data"][0]["price"]["id"] = "price_arbitrary"
    elif kind == "subscription":
        obj["id"] = "bad"
    elif kind == "quantity":
        obj["items"]["data"][0]["quantity"] = 100
    assert (
        send_event(
            client, settings, payload, timestamp=timestamp, secret=secret
        ).status_code
        == 400
    )
    assert client.get(url).json()["plan"] == "free"
    with client.app.state.db.session() as db:
        assert not list(db.scalars(select(BillingEvent)))


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {
            "id": "evt_test",
            "livemode": False,
            "created": 1,
            "type": "customer.subscription.updated",
            "data": [],
        },
        {
            "id": "evt_test",
            "livemode": False,
            "created": True,
            "type": "customer.subscription.updated",
        },
    ],
)
def test_signed_malformed_webhooks_are_rejected(billing_client, payload):
    client, settings, _ = billing_client
    assert send_event(client, settings, payload).status_code == 400


def test_disabled_billing_and_provider_url_validation(client):
    me = login(client)
    url = f"/api/organizations/{me['organizations'][0]['id']}/billing"
    assert client.get(url).json()["enabled"] is False
    assert client.post(url + "/checkout", json={"plan": "pro"}).status_code == 503
    assert client.post(url + "/portal").status_code == 503
    assert client.post("/api/billing/webhook", content="{}").status_code == 503
    for target in (
        "http://checkout.stripe.com",
        "https://checkout.stripe.com.evil.example",
        "https://user@checkout.stripe.com",
    ):
        with pytest.raises(ValueError):
            safe_provider_url(target, "checkout.stripe.com")
    assert safe_provider_url(
        "https://checkout.stripe.com/test", "checkout.stripe.com"
    ).endswith("/test")


def test_official_stripe_sdk_adapter_uses_allowlisted_parameters(settings, monkeypatch):
    calls = []

    class FakeCustomer:
        id = "cus_test"
        livemode = False

    class FakeCheckout:
        url = "https://checkout.stripe.com/test"
        livemode = False

    class FakePortal:
        url = "https://billing.stripe.com/test"

    gateway = StripeGateway(replace(settings, stripe_secret_key="sk_test_local"))

    def customer(**kwargs):
        calls.append(kwargs)
        return FakeCustomer()

    def checkout(**kwargs):
        calls.append(kwargs)
        return FakeCheckout()

    def portal(**kwargs):
        calls.append(kwargs)
        return FakePortal()

    monkeypatch.setattr(gateway.client.v1.customers, "create", customer)
    monkeypatch.setattr(gateway.client.v1.checkout.sessions, "create", checkout)
    monkeypatch.setattr(gateway.client.v1.billing_portal.sessions, "create", portal)
    assert gateway.customer("org") == "cus_test"
    assert gateway.checkout(
        "cus_test", "price_pro", "https://app.example/billing"
    ).startswith("https://checkout.stripe.com/")
    assert gateway.portal("cus_test", "https://app.example/billing").startswith(
        "https://billing.stripe.com/"
    )
    assert calls[0]["options"]["idempotency_key"] == "blastradius-customer-org"
    assert calls[1]["params"]["customer"] == "cus_test"
    assert calls[1]["params"]["mode"] == "subscription"
    assert calls[1]["params"]["line_items"] == [{"price": "price_pro", "quantity": 1}]


@pytest.mark.skipif(
    not os.environ.get("BR_TEST_DATABASE_URL"),
    reason="set BR_TEST_DATABASE_URL to a disposable PostgreSQL database",
)
def test_postgres_migration_jobs_and_atomic_quotas(settings, demo_results, monkeypatch):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    settings = replace(settings, database_url=os.environ["BR_TEST_DATABASE_URL"])
    app = create_app(settings)
    with TestClient(app) as client:
        me = login(client)
        proj = project(client, me)
        job = terminal(client, submit(client, proj["id"]).json()["id"])
        assert job["status"] == "succeeded", job
        database = app.state.db
        with database.engine.connect() as connection:
            assert (
                compare_metadata(MigrationContext.configure(connection), Base.metadata)
                == []
            )
        with pytest.raises(RuntimeError, match="Only one"):
            ServiceLease(database, settings.data_dir).acquire()

        def consume(_):
            try:
                with database.session(write=True) as db:
                    org = lock_org(db, proj["organization_id"])
                    quota(db, org, "analyses_per_month")
                return True
            except HTTPException as error:
                assert error.status_code == 402
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(consume, range(30)))
        assert sum(results) == 19
        assert (
            client.get("/api/me").json()["organizations"][0]["usage"]["analyses"] == 20
        )
        assert client.delete(f"/api/projects/{proj['id']}").status_code == 204
        assert client.get(f"/api/analyses/{job['id']}").status_code == 404
