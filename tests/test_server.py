from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastapi", reason="install .[server,dev] for backend tests")
pytest.importorskip("sqlalchemy", reason="install .[server,dev] for backend tests")

import httpx
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from authlib.jose import JsonWebKey, jwt
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url

from blastradius.server.app import create_app
from blastradius.server.admin import assign_plan, main as admin_main
from blastradius.server.auth import create_session, provision, token_hash
from blastradius.server.config import Settings
from blastradius.server.db import Database, migration_config
from blastradius.server.demos import build_demos
from blastradius.server.fixtures import FIXTURES
from blastradius.server.jobs import JobManager, execute
from blastradius.server.lease import ServiceLease
from blastradius.server.models import (
    Analysis,
    AnalysisArtifact,
    AttackPath,
    AttackPathHop,
    AuditEvent,
    Base,
    Finding,
    Invitation,
    Membership,
    LoginSession,
    Organization,
    Project,
    Usage,
    User,
)
from blastradius.server.observability import JsonFormatter
from blastradius.server.persistence import cleanup
from blastradius.server.plans import PLANS
from blastradius.server.quotas import lock_org, period, quota
from blastradius.server.schemas import AnalysisInput, EnterpriseLimits


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
def app(settings, demo_results, monkeypatch, caplog):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    app = create_app(settings)
    logger = logging.getLogger("blastradius")
    caplog.handler.setLevel(logging.WARNING)
    logger.addHandler(caplog.handler)
    try:
        yield app
    finally:
        logger.removeHandler(caplog.handler)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def test_workspace_origin_rejection_is_not_an_owner_permission_failure(client, settings):
    anonymous = client.get("/api/me").json()
    assert anonymous["auth"]["public_url"] == settings.public_url
    alternate = "http://testserver:8001"
    rejected_login = client.post(
        "/api/auth/demo",
        headers={"X-CSRF-Token": anonymous["csrf_token"], "Origin": alternate},
    )
    assert rejected_login.status_code == 403
    assert rejected_login.json()["detail"] == "invalid_origin"
    me = login(client)
    assert me["organizations"][0]["role"] == "owner"
    for origin, status in ((alternate, 403), (settings.public_url, 201)):
        response = client.post(
            "/api/organizations",
            json={"name": "Second workspace"},
            headers={"X-CSRF-Token": me["csrf_token"], "Origin": origin},
        )
        assert response.status_code == status
        if status == 403:
            assert response.json()["detail"] == "invalid_origin"
        else:
            assert response.json()["role"] == "owner"
    refreshed = client.get("/api/me").json()
    assert refreshed["user"]["id"] == me["user"]["id"]
    assert len(refreshed["organizations"]) == 2


@pytest.mark.parametrize(
    ("environment", "origin"),
    [
        ("development", "http://localhost:8000"),
        ("preview", "https://8000--session.preview.devinapps.com"),
        ("test", "https://app.example"),
    ],
)
def test_configured_origin_bootstrap_mutations_and_fail_closed(
    settings, demo_results, monkeypatch, environment, origin
):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    configured = replace(settings, environment=environment, public_url=origin)
    app = create_app(configured)
    with TestClient(app, base_url=origin) as client:
        response = client.get("/api/me")
        anonymous = response.json()
        assert anonymous["auth"]["public_url"] == origin
        assert ("Secure" in response.headers["set-cookie"]) == origin.startswith("https:")
        headers = {"Origin": origin, "X-CSRF-Token": anonymous["csrf_token"]}
        assert client.post(
            "/api/organizations", json={"name": "Anonymous"}, headers=headers
        ).status_code == 401
        assert client.post("/api/auth/demo", headers=headers).status_code == 200
        me = client.get("/api/me").json()
        headers["X-CSRF-Token"] = me["csrf_token"]
        assert client.post(
            "/api/organizations", json={"name": "Trusted origin"}, headers=headers
        ).status_code == 201
        for hostile in (
            {"Origin": "https://untrusted.example"},
            {"Origin": "http://localhost:8001"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
            {
                "Origin": "http://localhost",
                "Host": "localhost",
                "X-Forwarded-Host": urlsplit(origin).netloc,
                "X-Forwarded-Proto": "http",
                "Sec-Fetch-Site": "same-origin",
            },
            {
                "Origin": "https://untrusted.example",
                "Host": "untrusted.example",
                "X-Forwarded-Host": "untrusted.example",
                "X-Forwarded-Proto": "https",
                "Forwarded": "host=untrusted.example;proto=https",
            },
        ):
            rejected = client.post(
                "/api/organizations",
                json={"name": "Rejected"},
                headers=headers | hostile,
            )
            assert rejected.status_code == 403
            assert rejected.json()["detail"] == "invalid_origin"
        rejected = client.post(
            "/api/organizations", json={"name": "Missing CSRF"}, headers={"Origin": origin}
        )
        assert rejected.status_code == 403
        assert rejected.json()["detail"] == "csrf_required"
        assert len(client.get("/api/me").json()["organizations"]) == 2
        assert client.post(
            "/api/projects",
            json={"organization_id": "unavailable", "name": "Unauthorized"},
            headers=headers,
        ).status_code == 404
        logout = client.post("/api/auth/logout", headers=headers)
        assert logout.status_code == 200
        assert ("Secure" in logout.headers["set-cookie"]) == origin.startswith("https:")
        assert client.get("/api/projects").status_code == 401


@pytest.mark.parametrize("environment", ["development", "test", "preview", "production"])
@pytest.mark.parametrize("origin", [None, "", "http://localhost:8000", "https://app.example"])
def test_environment_origin_defaults_and_explicit_https(monkeypatch, environment, origin):
    for name in list(os.environ):
        if name.startswith("BR_"):
            monkeypatch.delenv(name)
    for name, value in {
        "BR_ENV": environment,
        "BR_SESSION_SECRET": "a" * 48,
        "BR_AUTH_MODE": "oidc",
        "BR_OIDC_ISSUER": "https://issuer.example",
        "BR_OIDC_CLIENT_ID": "client",
        "BR_OIDC_CLIENT_SECRET": "test-client-secret",
        "BR_DATABASE_URL": "postgresql+psycopg://localhost/br",
    }.items():
        monkeypatch.setenv(name, value)
    if origin is not None:
        monkeypatch.setenv("BR_PUBLIC_URL", origin)
    if origin == "" or (environment in {"preview", "production"} and origin != "https://app.example"):
        with pytest.raises(ValueError, match="BR_PUBLIC_URL"):
            Settings.from_env()
    else:
        configured = Settings.from_env()
        assert configured.public_url == (origin or "http://localhost:8000")
        assert configured.secure_cookies == (origin == "https://app.example")


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("postgres://user:pass@example/db", "postgresql+psycopg://user:pass@example/db"),
        ("postgresql://user:pass@example/db", "postgresql+psycopg://user:pass@example/db"),
        ("postgresql+psycopg://user:pass@example/db", "postgresql+psycopg://user:pass@example/db"),
        ("sqlite:///./server.db", "sqlite:///./server.db"),
    ],
)
def test_database_url_normalization(monkeypatch, database_url, expected):
    for name in list(os.environ):
        if name.startswith("BR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("BR_DATABASE_URL", database_url)
    assert Settings.from_env().database_url == expected


@pytest.mark.parametrize("value", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_log_level_from_environment(monkeypatch, value):
    for name in list(os.environ):
        if name.startswith("BR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("BR_LOG_LEVEL", value)
    assert Settings.from_env().log_level == value


def test_invalid_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("BR_LOG_LEVEL", "verbose")
    with pytest.raises(ValueError, match="BR_LOG_LEVEL"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["601", "-1"])
def test_lease_wait_seconds_must_be_bounded(monkeypatch, value):
    monkeypatch.setenv("BR_LEASE_WAIT_SECONDS", value)
    with pytest.raises(ValueError, match="BR_LEASE_WAIT_SECONDS"):
        Settings.from_env()


@pytest.mark.parametrize(
    "origin",
    [
        "https://*.preview.devinapps.com",
        "https://app.example/path",
        "https://app.example?trusted=true",
        "https://app.example#fragment",
        "https://user:password@app.example",
        "https://app.example:0",
        "https://app.example:invalid",
        "https://app.example:65536",
        " https://app.example",
        "https://app.example\\untrusted",
    ],
)
def test_public_origin_rejects_ambiguous_configuration(settings, origin):
    with pytest.raises(ValueError):
        replace(settings, public_url=origin).validate()


def test_https_preview_oidc_cookie_and_callback_ignore_forwarded_origin(
    settings, demo_results, monkeypatch
):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    origin = "https://8000--session.preview.devinapps.com"
    configured = replace(
        settings,
        environment="preview",
        public_url=origin,
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        oidc_client_secret="test",
    )
    app = create_app(configured)
    oauth = app.state.oauth.create_client("oidc")
    oauth.server_metadata.update(
        {
            "issuer": configured.oidc_issuer,
            "_loaded_at": time.time(),
            "authorization_endpoint": "https://issuer.example/authorize",
            "token_endpoint": "https://issuer.example/token",
        }
    )
    with TestClient(app, base_url=origin) as client:
        response = client.get(
            "/api/auth/login",
            headers={
                "Host": "untrusted.example",
                "X-Forwarded-Host": "untrusted.example",
                "X-Forwarded-Proto": "http",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        params = parse_qs(urlsplit(response.headers["location"]).query)
        assert params["redirect_uri"] == [origin + "/api/auth/callback"]
        cookies = SimpleCookie()
        cookies.load(response.headers["set-cookie"])
        assert cookies["br_oidc"]["secure"]
        assert cookies["br_oidc"]["httponly"]
        assert cookies["br_oidc"]["samesite"] == "lax"


def login(client):
    anonymous = client.get("/api/me").json()
    response = client.post("/api/auth/demo", headers={"X-CSRF-Token": anonymous["csrf_token"]})
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
        files_response = client.get(f"/api/demo/{scenario['id']}/files")
        assert files_response.status_code == 200
        files = files_response.json()
        assert set(files) == {"scenario_id", "title", "before_files", "after_files"}
        assert files["scenario_id"] == scenario["id"]
        assert files["title"] == FIXTURES[scenario["id"]]["title"]
        assert files["before_files"] == FIXTURES[scenario["id"]]["before_files"]
        assert files["after_files"] == FIXTURES[scenario["id"]]["after_files"]
        AnalysisInput(
            project_id="demo",
            before_files=files["before_files"],
            after_files=files["after_files"],
        )
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
            assert report == client.get(f"/api/demo/{scenario['id']}?stage={stage}").json()
    assert client.get("/api/demo/nope/files").status_code == 404
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
    assert client.post("/api/auth/demo", headers=[(b"X-CSRF-Token", b"\xff")]).status_code == 403
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
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 403
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
        assert me["auth"] == {
            "enabled": False,
            "mode": "disabled",
            "login_url": None,
            "public_url": settings.public_url,
        }
        assert me["billing"] == {"enabled": False, "mode": "commercial_beta"}
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
        assert client.get("/api/auth/callback?code=invalid&state=wrong").status_code == 400
        assert not client.get("/api/me").json()["authenticated"]


@pytest.mark.parametrize(
    "invalid",
    [None, "signature", "nonce", "issuer", "audience", "expiry", "nonce_supported"],
)
def test_oidc_callback_verifies_signed_claims(settings, demo_results, monkeypatch, invalid):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    settings = replace(
        settings,
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        oidc_client_secret="test",
    )
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "local"})
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
            JsonWebKey.generate_key("RSA", 2048, is_private=True) if invalid == "signature" else key
        )
        encoded = jwt.encode({"alg": "RS256", "kid": "local"}, claims, signing_key).decode()
        return httpx.Response(
            200,
            json={
                "access_token": "test-access-token",
                "token_type": "Bearer",
                "id_token": encoded,
            },
        )

    app = create_app(settings)
    app.state.oauth.create_client("oidc").client_kwargs["transport"] = httpx.MockTransport(
        transport
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


@pytest.mark.parametrize(
    ("email", "verified", "expected"),
    [
        (["invited@example.test"], True, ""),
        ({"address": "invited@example.test"}, True, ""),
        (None, True, ""),
        ("a" * 321 + "@example.test", True, ""),
        ("invited@example.test\x00", True, ""),
        ("invited@example.test", "true", ""),
        ("invited@example.test", False, ""),
        ("INVITED@example.test", True, "invited@example.test"),
        ("Straße@example.test", True, "straße@example.test"),
    ],
    ids=[
        "list",
        "mapping",
        "missing",
        "overlong",
        "control",
        "string-flag",
        "unverified",
        "ascii-case",
        "unicode",
    ],
)
def test_oidc_callback_keeps_only_valid_literal_verified_email(
    settings, demo_results, monkeypatch, email, verified, expected
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

    async def state_data(*args):
        return {"nonce": "test-nonce"}

    async def authorized_token(*args):
        return {
            "userinfo": {
                "iss": settings.oidc_issuer,
                "sub": "stable-subject",
                "nonce": "test-nonce",
                "email": email,
                "email_verified": verified,
            }
        }

    monkeypatch.setattr(oauth.framework, "get_state_data", state_data)
    monkeypatch.setattr(oauth, "authorize_access_token", authorized_token)
    with TestClient(app) as client:
        response = client.get("/api/auth/callback?state=test-state", follow_redirects=False)
        assert response.status_code == 303
        me = client.get("/api/me").json()
        assert me["authenticated"]
        assert me["user"]["email"] == expected
        assert me["user"]["email_verified"] is bool(expected)


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
    for kind in ("web", "json", "markdown"):
        assert client.get(f"/api/analyses/{analysis_id}/report?format={kind}").status_code == 200
    assert client.get(f"/api/analyses/{analysis_id}/report?format=sarif").status_code == 402
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
    assert client.post(member_url, json={"user_id": user_id, "role": "owner"}).status_code == 405
    assert (
        client.post(
            f"/api/organizations/{org_id}/invitations",
            json={"email": "viewer@example.test", "role": "viewer"},
        ).status_code
        == 402
    )
    with app.state.db.session(write=True) as db:
        db.get(Organization, org_id).plan = "team"
        db.add(Membership(user_id=user_id, organization_id=org_id, role="viewer"))
    assert viewer_client.get(f"/api/projects/{proj['id']}/analyses").status_code == 200
    assert submit(viewer_client, proj["id"]).status_code == 403
    assert viewer_client.delete(f"/api/projects/{proj['id']}").status_code == 403
    assert viewer_client.get(f"/api/organizations/{org_id}/billing").status_code == 403
    assert (
        viewer_client.patch(
            member_url + "/" + owner["user"]["id"], json={"role": "owner"}
        ).status_code
        == 403
    )
    assert client.delete(member_url + "/" + owner["user"]["id"]).status_code == 409
    assert client.delete(member_url + "/" + user_id).status_code == 204
    assert viewer_client.get(f"/api/projects/{proj['id']}/analyses").status_code == 404
    created = viewer_client.post("/api/organizations", json={"name": "My second workspace"}).json()
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
    bad = submit(client, proj["id"], after_files={"main.tf": 'resource "aws_instance" "a" {'})
    assert terminal(client, bad.json()["id"])["status"] == "failed"
    plan = json.loads((Path(__file__).parents[1] / "examples/plans/ssh_open_plan.json").read_text())
    response = client.post("/api/analyses", json={"project_id": proj["id"], "plan": plan})
    job = terminal(client, response.json()["id"])
    assert job["status"] == "succeeded" and not job["result"]["passed"]
    assert job["result"]["remediation"]["patched_files"] == {}
    assert client.get("/api/me").json()["organizations"][0]["usage"]["analyses"] == 2


def test_body_file_resource_limits_and_sanitized_errors(client, app, monkeypatch, caplog):
    proj = project(client, login(client))
    assert (
        submit(
            client, proj["id"], before_files={f"f{index}.tf": "" for index in range(31)}
        ).status_code
        == 413
    )
    response = client.post("/api/analyses", content=b"x" * (app.state.settings.max_body_bytes + 1))
    assert response.status_code == 413
    assert response.headers["x-request-id"] and response.headers["cache-control"] == "no-store"
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
    assert response.status_code == 500 and response.json() == {"detail": "internal_error"}
    assert response.headers["x-request-id"]
    assert "private-secret" not in caplog.text
    records = [
        json.loads(JsonFormatter().format(record))
        for record in caplog.records
        if record.name == "blastradius.http"
    ]
    assert any(
        record.get("status") == 500 and record.get("error") == "internal_error"
        for record in records
    )
    assert any(
        record.get("event") == "unhandled_exception"
        and record.get("exception") == "ValueError"
        for record in records
    )
    assert "Traceback" not in caplog.text


def test_request_log_is_structured_and_privacy_safe(client, settings, caplog):
    caplog.set_level(logging.INFO, logger="blastradius.http")
    response = client.get("/api/me?code=SECRET-QUERY&state=abc")
    records = [
        json.loads(JsonFormatter().format(record))
        for record in caplog.records
        if record.name == "blastradius.http"
    ]
    request = records[-1]
    assert (
        request["request_id"] == response.headers["x-request-id"]
        and request["method"] == "GET"
        and request["status"] == 200
        and request["endpoint"] == "/api/me"
        and request["duration_ms"] >= 0
    )
    assert "SECRET-QUERY" not in caplog.text

    caplog.clear()
    me = login(client)
    client.headers.pop("X-CSRF-Token")
    rejected = client.post(
        "/api/projects",
        json={"name": "Missing CSRF", "organization_id": me["organizations"][0]["id"]},
        headers={"Origin": settings.public_url},
    )
    assert rejected.status_code == 403
    request = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert request["status"] == 403 and request["error"] == "csrf_required"

    caplog.clear()
    analysis_id = str(uuid.uuid4())
    missing = client.get(f"/api/analyses/{analysis_id}")
    assert missing.status_code == 404
    request = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert (
        request["endpoint"] == "/api/analyses/{analysis_id}"
        and request["analysis_id"] == analysis_id
    )

    caplog.clear()
    unmatched = client.get("/api/nope/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert unmatched.status_code == 404
    request = json.loads(JsonFormatter().format(caplog.records[-1]))
    assert request["path"] == "/api/nope/*" and "analysis_id" not in request


def test_rate_limits_separate_demo_auth_and_general(settings, demo_results, monkeypatch):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    with TestClient(
        create_app(replace(settings, demo_rate_limit=1, auth_rate_limit=1, rate_limit=2))
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
        db.add(Usage(organization_id=proj["organization_id"], period=period(), analyses=25))
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
        assert client.get(f"/api/analyses/{response.json()['id']}/report").status_code == 409
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
    payload = AnalysisInput(project_id="test", before_files={"a.tf": ""}, after_files={"a.tf": ""})
    assert execute(payload, settings) == {"error": "analysis_timeout"}
    assert not list((settings.data_dir / "jobs").iterdir())


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
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
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
        assert sum(results) == 24
        assert client.get("/api/me").json()["organizations"][0]["usage"]["analyses"] == 25
        assert client.delete(f"/api/projects/{proj['id']}").status_code == 204
        assert client.get(f"/api/analyses/{job['id']}").status_code == 404


def identity_client(app, email="invited@example.test", verified=True, org_id=None, role="viewer"):
    other = TestClient(app)
    response = Response()
    with app.state.db.session(write=True) as session:
        user = provision(
            session, "https://test-issuer.example", str(uuid.uuid4()), "Invited", email, verified
        )
        login_session = create_session(response, session, app.state.settings, user.id)
        if org_id:
            session.add(Membership(user_id=user.id, organization_id=org_id, role=role))
        user_id = user.id
    cookie = response.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    other.cookies.set("br_session", cookie)
    other.headers["X-CSRF-Token"] = login_session.csrf_token
    return other, user_id


def test_payments_cannot_be_activated_and_catalog_is_authoritative(client, monkeypatch):
    for name, value in {
        "BR_STRIPE_SECRET_KEY": "sk_live_ignored",
        "BR_STRIPE_WEBHOOK_SECRET": "whsec_ignored",
        "BR_STRIPE_PRICE_PRO": "price_ignored",
        "BR_STRIPE_PRICE_TEAM": "price_ignored2",
        "BR_BILLING_ENABLED": "true",
        "BR_ADMIN_ENABLED": "true",
    }.items():
        monkeypatch.setenv(name, value)
    assert Settings.from_env().billing_enabled is False
    me = login(client)
    org_id = me["organizations"][0]["id"]
    assert client.get(f"/api/organizations/{org_id}/billing").json()["enabled"] is False
    for url in (
        f"/api/organizations/{org_id}/billing/checkout",
        f"/api/organizations/{org_id}/billing/portal",
        "/api/billing/webhook",
        "/api/admin/assign-plan",
    ):
        assert client.post(url, json={"plan": "team"}).status_code == 404
    assert (
        client.patch(
            f"/api/organizations/{org_id}", json={"name": "Org", "plan": "team"}
        ).status_code
        == 422
    )
    public = client.get("/api/plans").json()
    assert public["payments_enabled"] is False
    assert {p["code"]: p["limits"] for p in public["plans"]} == {
        key: value.limits for key, value in PLANS.items()
    }
    assert [(p["code"], p["monthly_price_usd"]) for p in public["plans"]] == [
        ("free", 0),
        ("pro", 49),
        ("team", 149),
        ("enterprise", None),
    ]
    assert [(p.projects, p.analyses_per_month, p.retention_days) for p in PLANS.values()] == [
        (1, 25, 7),
        (5, 500, 90),
        (25, 5000, 365),
        (25, 5000, 365),
    ]
    assert not any(
        p["features"]["payments"] or p["features"]["priority_queue"] or p["features"]["saml"]
        for p in public["plans"]
    )
    metadata = Path("pyproject.toml").read_text()
    assert "stripe" not in metadata.lower()
    assert not Path("blastradius/server/billing.py").exists()


def test_operator_assignment_audit_and_enterprise_limits(client, app, monkeypatch):
    me = login(client)
    org_id = me["organizations"][0]["id"]
    limits = EnterpriseLimits(projects=2, analyses_per_month=3, retention_days=12, members=4)
    result = assign_plan(app.state.db, org_id, "enterprise", limits)
    assert result["limits"] == limits.model_dump()
    with app.state.db.session() as session:
        event = session.scalar(select(AuditEvent).where(AuditEvent.action == "plan.assigned"))
        assert event.details == {
            "before": "free",
            "after": "enterprise",
            "limits": limits.model_dump(),
        }
        org = session.get(Organization, org_id)
        assert org.customer_id is None and org.subscription_id is None
    monkeypatch.delenv("BR_ADMIN_ENABLED", raising=False)
    with pytest.raises(SystemExit) as error:
        admin_main(["assign-plan", org_id, "pro"])
    assert error.value.code == 2


@pytest.mark.parametrize("role", ["owner", "admin", "developer", "viewer"])
def test_four_role_permission_matrix(client, app, role):
    me = login(client)
    org_id = me["organizations"][0]["id"]
    proj = project(client, me)
    assign_plan(app.state.db, org_id, "team")
    actor, _ = identity_client(app, org_id=org_id, role=role)
    manages = role in ("owner", "admin")
    assert actor.get(f"/api/projects/{proj['id']}").status_code == 200
    assert actor.get(f"/api/organizations/{org_id}/usage").status_code == 200
    assert actor.get(f"/api/organizations/{org_id}/billing").status_code == (
        200 if role == "owner" else 403
    )
    assert actor.patch(f"/api/organizations/{org_id}", json={"name": "Renamed"}).status_code == (
        200 if manages else 403
    )
    assert actor.post(
        "/api/projects", json={"name": "Other", "organization_id": org_id}
    ).status_code == (201 if manages else 403)
    assert actor.put(f"/api/projects/{proj['id']}/policy", json={}).status_code == (
        200 if manages else 403
    )
    assert actor.put(f"/api/organizations/{org_id}/policy", json={}).status_code == (
        200 if manages else 403
    )
    assert actor.get(f"/api/organizations/{org_id}/members").status_code == (
        200 if manages else 403
    )
    assert actor.get(f"/api/organizations/{org_id}/audit").status_code == (200 if manages else 403)
    assert actor.post(
        f"/api/organizations/{org_id}/invitations", json={"email": "new@example.test"}
    ).status_code == (201 if manages else 403)
    run = submit(actor, proj["id"])
    assert run.status_code == (403 if role == "viewer" else 202)
    if role != "viewer":
        assert terminal(actor, run.json()["id"])["status"] == "succeeded"
    if role != "owner":
        assert actor.delete(f"/api/organizations/{org_id}").status_code == 403
    assert actor.delete(f"/api/projects/{proj['id']}").status_code == (204 if manages else 403)


def test_owner_protection_and_organization_cascade(client, app):
    me = login(client)
    org_id = me["organizations"][0]["id"]
    proj = project(client, me)
    assign_plan(app.state.db, org_id, "team")
    admin, admin_id = identity_client(app, org_id=org_id, role="admin")
    owner_url = f"/api/organizations/{org_id}/members/{me['user']['id']}"
    assert client.patch(owner_url, json={"role": "developer"}).status_code == 409
    assert client.delete(owner_url).status_code == 409
    assert admin.patch(owner_url, json={"role": "viewer"}).status_code == 403
    assert admin.delete(owner_url).status_code == 403
    assert (
        admin.patch(
            f"/api/organizations/{org_id}/members/{admin_id}", json={"role": "owner"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/organizations/{org_id}/members/{admin_id}", json={"role": "owner"}
        ).status_code
        == 200
    )
    assert client.patch(owner_url, json={"role": "admin"}).status_code == 200
    assert client.delete(f"/api/organizations/{org_id}").status_code == 403
    job = terminal(admin, submit(admin, proj["id"]).json()["id"])
    assert admin.delete(f"/api/organizations/{org_id}").status_code == 204
    with app.state.db.session() as session:
        for model in (
            Project,
            Analysis,
            Finding,
            AttackPath,
            AttackPathHop,
            AnalysisArtifact,
            Invitation,
            Membership,
            Usage,
        ):
            if model is Membership:
                assert not list(
                    session.scalars(select(model).where(model.organization_id == org_id))
                )
            elif model not in (
                Project,
                Analysis,
                Finding,
                AttackPath,
                AttackPathHop,
                AnalysisArtifact,
            ):
                assert not list(session.scalars(select(model)))
        assert session.get(Analysis, job["id"]) is None
        assert session.scalar(select(func.count()).select_from(AttackPathHop)) == 0
        assert (
            session.scalar(select(AuditEvent).where(AuditEvent.action == "organization.deleted"))
            is not None
        )


def test_project_archive_metadata_and_atomic_slots(client, app):
    me = login(client)
    proj = project(client, me)
    url = f"/api/projects/{proj['id']}"
    assert (
        client.patch(
            url,
            json={
                "name": "Archived",
                "description": "Example",
                "repository": "acme/infra",
                "repository_provider": "github",
                "default_branch": "release/main",
                "environment": "staging",
                "terraform_root": "infra/aws",
                "archived": True,
            },
        ).status_code
        == 200
    )
    saved = client.get(url).json()
    assert saved["archived_at"] and saved["repository"] == "acme/infra"
    assert saved["repository_provider"] == "github" and saved["terraform_root"] == "infra/aws"
    assert submit(client, proj["id"]).status_code == 409
    other = project(client, me)
    assert client.patch(url, json={"name": "Restored", "archived": False}).status_code == 402
    assert client.delete(f"/api/projects/{other['id']}").status_code == 204
    assert client.patch(url, json={"name": "Restored"}).status_code == 200
    assert client.get(f"/api/organizations/{proj['organization_id']}/usage").json()["projects"] == 1
    for invalid in (
        {"name": "   "},
        {"name": "bad\nname"},
        {"name": "okay", "terraform_root": "../host"},
        {"name": "okay", "repository": "https://token@host/repo"},
    ):
        assert client.patch(url, json=invalid).status_code == 422


def test_session_information_revocation_and_no_hash_exposure(client, app):
    login(client)
    stranger, _ = identity_client(app)
    sessions = client.get("/api/account/sessions").json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["current"] is True
    assert "token_hash" not in sessions[0] and "csrf_token" not in sessions[0]
    url = "/api/account/sessions/" + sessions[0]["id"]
    assert stranger.delete(url).status_code == 404
    assert client.delete(url).status_code == 204
    assert client.get("/api/account/sessions").status_code == 401
    assert stranger.delete("/api/account/sessions").status_code == 204
    assert stranger.get("/api/account/sessions").status_code == 401


def create_invitation(client, org_id, email="invited@example.test", role="developer"):
    response = client.post(
        f"/api/organizations/{org_id}/invitations", json={"email": email, "role": role}
    )
    assert response.status_code == 201, response.text
    invite = response.json()
    return invite, invite["invitation_url"].split("#token=")[1]


def test_invitation_hash_single_use_verified_binding_and_manual_delivery(client, app, caplog):
    me = login(client)
    org_id = me["organizations"][0]["id"]
    assert (
        client.post(
            f"/api/organizations/{org_id}/invitations", json={"email": "invited@example.test"}
        ).status_code
        == 402
    )
    assign_plan(app.state.db, org_id, "team")
    caplog.set_level(logging.INFO)
    invite, token = create_invitation(client, org_id, "INVITED@example.test")
    assert len(token) == 43 and invite["delivery"] == "manual"
    with app.state.db.session() as session:
        stored = session.get(Invitation, invite["id"])
        assert stored.token_hash == token_hash(token) and token not in stored.token_hash
    assert token not in client.get(f"/api/organizations/{org_id}/invitations").text
    assert token not in client.get(f"/api/organizations/{org_id}/audit").text
    for email, verified in (("stranger@example.test", True), ("invited@example.test", False)):
        actor, _ = identity_client(app, email, verified)
        assert actor.post("/api/invitations/accept", json={"token": token}).status_code == 404
    assert client.post("/api/invitations/accept", json={"token": token}).status_code == 404
    actor, _ = identity_client(app)
    accepted = actor.post("/api/invitations/accept", json={"token": token})
    assert accepted.json() == {"organization_id": org_id, "role": "developer"}
    assert actor.post("/api/invitations/accept", json={"token": token}).status_code == 404
    usage = client.get(f"/api/organizations/{org_id}/usage").json()
    assert usage["members"] == 2 and usage["pending_invitations"] == 0
    assert token not in caplog.text and "invited@example.test" not in caplog.text
    assert (
        client.post(
            f"/api/organizations/{org_id}/invitations",
            json={"email": "new@example.test", "role": "owner"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("recipient", "different_mailbox"),
    [
        ("straße@example.test", "strasse@example.test"),
        ("strasse@example.test", "straße@example.test"),
        ("member@faß.test", "member@fass.test"),
        ("ſtaff@example.test", "staff@example.test"),
    ],
)
def test_invitation_binding_does_not_merge_unicode_mailboxes(
    client, app, recipient, different_mailbox
):
    org_id = login(client)["organizations"][0]["id"]
    assign_plan(app.state.db, org_id, "team")
    invite, token = create_invitation(client, org_id, recipient)
    other, other_id = identity_client(app, different_mailbox)
    response = other.post("/api/invitations/accept", json={"token": token})
    assert response.status_code == 404
    with app.state.db.session() as session:
        assert session.get(Membership, (other_id, org_id)) is None
        assert session.get(Invitation, invite["id"]).accepted_at is None
    intended, _ = identity_client(app, recipient)
    assert intended.post("/api/invitations/accept", json={"token": token}).status_code == 200


def test_verified_email_is_not_truncated_into_invited_identity(client, app):
    org_id = login(client)["organizations"][0]["id"]
    assign_plan(app.state.db, org_id, "team")
    recipient = "a" * (320 - len("@example.test")) + "@example.test"
    invite, token = create_invitation(client, org_id, recipient)
    actor, user_id = identity_client(app, recipient + ".different")
    assert actor.post("/api/invitations/accept", json={"token": token}).status_code == 404
    with app.state.db.session() as session:
        user = session.get(User, user_id)
        assert not user.email_verified and user.email == ""
        assert session.get(Invitation, invite["id"]).accepted_at is None
        assert session.get(Membership, (user_id, org_id)) is None


@pytest.mark.parametrize("email", ["", "invalid", "name@example.test\x00", "a" * 321])
def test_reauthentication_clears_invalid_verified_email(client, app, email):
    with app.state.db.session(write=True) as session:
        user = provision(session, "issuer", "subject", "User", "valid@example.test", True)
        assert user.email_verified
        again = provision(session, "issuer", "subject", "User", email, True)
        assert again.id == user.id
        assert again.email == "" and not again.email_verified
        restored = provision(session, "issuer", "subject", "User", "valid@example.test", True)
        assert restored.id == user.id and restored.email_verified
        assert restored.email == "valid@example.test"


@pytest.mark.parametrize("state", ["expired", "revoked", "downgraded"])
def test_invitation_unavailable_states(client, app, state):
    me = login(client)
    org_id = me["organizations"][0]["id"]
    assign_plan(app.state.db, org_id, "team")
    invite, token = create_invitation(client, org_id)
    if state == "revoked":
        assert (
            client.delete(f"/api/organizations/{org_id}/invitations/{invite['id']}").status_code
            == 204
        )
    elif state == "expired":
        with app.state.db.session(write=True) as session:
            session.get(Invitation, invite["id"]).expires_at = time.time() - 1
    else:
        assign_plan(app.state.db, org_id, "free")
    actor, _ = identity_client(app)
    response = actor.post("/api/invitations/accept", json={"token": token})
    assert response.status_code == (402 if state == "downgraded" else 404)
    with app.state.db.session() as session:
        assert session.get(Invitation, invite["id"]).accepted_at is None


def test_invitation_and_analysis_quota_races(backend_client):
    client, app = backend_client
    me = login(client)
    org_id = me["organizations"][0]["id"]
    proj = project(client, me)
    limits = EnterpriseLimits(projects=1, analyses_per_month=3, retention_days=30, members=2)
    assign_plan(app.state.db, org_id, "enterprise", limits)

    def invite(_):
        return client.post(
            f"/api/organizations/{org_id}/invitations", json={"email": "invited@example.test"}
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(invite, range(8)))
    assert sorted(r.status_code for r in responses) == [201] + [402] * 7
    token = next(
        r.json()["invitation_url"].split("#token=")[1] for r in responses if r.status_code == 201
    )
    actor, _ = identity_client(app)
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(
            pool.map(
                lambda _: actor.post("/api/invitations/accept", json={"token": token}).status_code,
                range(8),
            )
        )
    assert sorted(accepted) == [200] + [404] * 7

    def consume(_):
        try:
            with app.state.db.session(write=True) as session:
                quota(session, lock_org(session, org_id), "analyses_per_month")
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        consumed = list(pool.map(consume, range(12)))
    assert sorted(consumed) == [200] * 3 + [402] * 9
    assert submit(client, proj["id"]).status_code == 402
    assert client.get(f"/api/organizations/{org_id}/usage").json()["analyses"] == 3


def test_policy_snapshot_worker_normalization_history_and_export_gates(client, app, caplog):
    me = login(client)
    proj = project(client, me)
    org_id, project_id = proj["organization_id"], proj["id"]
    policy_url = f"/api/projects/{project_id}/policy"
    assert client.put(policy_url, json={}).status_code == 402
    assign_plan(app.state.db, org_id, "pro")
    policy = {
        "gate": {
            "block_new_critical_paths": False,
            "block_new_sensitive_exposure": False,
            "block_public_admin_ports": False,
        }
    }
    for invalid in (
        {"ignored_rule": False},
        {"gate": {"block_new_critical_paths": "false"}},
        {"thresholds": {"minimum_security_score": 101}},
    ):
        assert client.put(policy_url, json=invalid).status_code == 422
    before = terminal(client, submit(client, project_id).json()["id"])
    assert before["decision"] == "BLOCK CHANGE"
    assert client.put(policy_url, json=policy).json()["version"] == 1
    caplog.set_level(logging.INFO)
    submitted = submit(
        client, project_id, base_ref="main", candidate_ref="feature", candidate_sha="a" * 40
    )
    assert submitted.status_code == 202
    assert client.put(policy_url, json={}).json()["version"] == 2
    after = terminal(client, submitted.json()["id"])
    assert after["status"] == "succeeded", after
    assert after["decision"] != before["decision"]
    assert after["result"]["after"]["attack_paths"] == before["result"]["after"]["attack_paths"]
    assert after["policy_snapshot"]["version"] == 1
    assert after["policy_snapshot"]["rules"]["gate"]["block_new_critical_paths"] is False
    assert submit(client, project_id, policy=policy).status_code == 422
    assert submit(client, project_id, policy_snapshot={"rules": policy}).status_code == 422
    analysis_id = after["id"]
    paths = client.get(f"/api/analyses/{analysis_id}/paths").json()
    assert paths["normalized_version"] == 1 and paths["paths"][0]["hops"]
    assert client.get(f"/api/analyses/{analysis_id}/findings").json()["findings"]
    history = client.get(
        f"/api/projects/{project_id}/analyses?branch=feature&input_type=hcl&status=succeeded&limit=1"
    ).json()
    assert history["total"] == 1 and history["analyses"][0]["candidate_sha"] == "a" * 40
    assert history["analyses"][0]["score_after"] == after["result"]["score"]["after"]
    assert client.get(f"/api/projects/{project_id}/analyses?branch=missing").json()["total"] == 0
    artifacts = client.get(f"/api/analyses/{analysis_id}/artifacts").json()["artifacts"]
    assert {a["format"] for a in artifacts} == {"json", "markdown", "sarif"}
    for artifact in artifacts:
        assert (
            client.get(f"/api/analyses/{analysis_id}/artifacts/{artifact['id']}").status_code == 200
        )
    assert client.get(f"/api/analyses/{analysis_id}/report?format=sarif").status_code == 200
    assign_plan(app.state.db, org_id, "free")
    assert client.get(f"/api/analyses/{analysis_id}/report?format=sarif").status_code == 402
    assert "sarif" not in client.get(f"/api/analyses/{analysis_id}").json()["result"]["reports"]
    for artifact in artifacts:
        download = client.get(f"/api/analyses/{analysis_id}/artifacts/{artifact['id']}")
        assert download.status_code == (402 if artifact["format"] == "sarif" else 200)
        if artifact["format"] == "json":
            assert "sarif" not in download.json()["reports"]
    assert client.get(policy_url).json()["effective"]["source"] == "default"
    logs = [json.loads(r.message) for r in caplog.records if r.name == "blastradius.jobs"]
    assert (
        logs
        and logs[0]["analysis_id"] == analysis_id
        and logs[0]["request_id"] == submitted.headers["x-request-id"]
    )
    assert logs[0]["outcome"] == "succeeded" and logs[0]["duration_ms"] >= 0
    assert str(app.state.settings.data_dir) not in json.dumps(after["result"])
    assert not list((app.state.settings.data_dir / "jobs").iterdir())


def test_organization_policy_inheritance_and_clear(client, app):
    me = login(client)
    proj = project(client, me)
    org_id = proj["organization_id"]
    assign_plan(app.state.db, org_id, "team")
    org_url = f"/api/organizations/{org_id}/policy"
    project_url = f"/api/projects/{proj['id']}/policy"
    assert (
        client.put(org_url, json={"thresholds": {"minimum_security_score": 80}}).status_code == 200
    )
    assert client.get(project_url).json()["effective"]["source"] == "organization"
    assert client.put(project_url, json={}).status_code == 200
    assert client.get(project_url).json()["effective"]["source"] == "project"
    assert client.delete(project_url).status_code == 204
    assert client.get(project_url).json()["effective"]["source"] == "organization"
    assert client.delete(org_url).status_code == 204
    assert client.get(project_url).json()["effective"]["source"] == "default"


def test_expiration_read_gates_cleanup_cascades_and_usage_survives(client, app):
    me = login(client)
    proj = project(client, me)
    org_id = proj["organization_id"]
    job = terminal(client, submit(client, proj["id"]).json()["id"])
    analysis_id = job["id"]
    artifact_id = client.get(f"/api/analyses/{analysis_id}/artifacts").json()["artifacts"][0]["id"]
    with app.state.db.session(write=True) as session:
        session.get(Analysis, analysis_id).created_at = time.time() - 8 * 86400
    for suffix in (
        "",
        "/findings",
        "/paths",
        "/artifacts",
        f"/artifacts/{artifact_id}",
        "/report?format=json",
        "/report?format=sarif",
    ):
        assert client.get(f"/api/analyses/{analysis_id}" + suffix).status_code == 404
    assert client.get(f"/api/projects/{proj['id']}/analyses").json()["total"] == 0
    assign_plan(app.state.db, org_id, "pro")
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 200
    assign_plan(app.state.db, org_id, "free")
    assert cleanup(app.state.db, 1) == 1
    assert cleanup(app.state.db, 1) == 0
    with app.state.db.session() as session:
        for model in (Analysis, Finding, AttackPath, AttackPathHop, AnalysisArtifact):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.get(Usage, (org_id, period())).analyses == 1
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 404


def test_all_new_tenant_surfaces_reject_cross_tenant_access(client, app):
    me = login(client)
    proj = project(client, me)
    org_id = proj["organization_id"]
    assign_plan(app.state.db, org_id, "team")
    job = terminal(client, submit(client, proj["id"]).json()["id"])
    artifact_id = client.get(f"/api/analyses/{job['id']}/artifacts").json()["artifacts"][0]["id"]
    invite, _ = create_invitation(client, org_id)
    other, user_id = identity_client(app)
    for url in (
        f"/api/projects/{proj['id']}",
        f"/api/projects/{proj['id']}/policy",
        f"/api/organizations/{org_id}/usage",
        f"/api/organizations/{org_id}/policy",
        f"/api/organizations/{org_id}/audit",
        f"/api/organizations/{org_id}/invitations",
        f"/api/analyses/{job['id']}/findings",
        f"/api/analyses/{job['id']}/paths",
        f"/api/analyses/{job['id']}/artifacts",
        f"/api/analyses/{job['id']}/artifacts/{artifact_id}",
    ):
        assert other.get(url).status_code == 404, url
    for method, url, body in (
        ("PATCH", f"/api/organizations/{org_id}", {"name": "Other"}),
        ("PATCH", f"/api/projects/{proj['id']}", {"name": "Other"}),
        ("PATCH", f"/api/organizations/{org_id}/members/{me['user']['id']}", {"role": "viewer"}),
        ("POST", f"/api/organizations/{org_id}/invitations", {"email": "other@example.test"}),
        ("PUT", f"/api/organizations/{org_id}/policy", {}),
        ("PUT", f"/api/projects/{proj['id']}/policy", {}),
    ):
        assert other.request(method, url, json=body).status_code == 404, url
    for url in (
        f"/api/organizations/{org_id}",
        f"/api/organizations/{org_id}/policy",
        f"/api/projects/{proj['id']}/policy",
        f"/api/organizations/{org_id}/invitations/{invite['id']}",
        f"/api/organizations/{org_id}/members/{me['user']['id']}",
    ):
        assert other.delete(url).status_code == 404, url
    other_me = other.get("/api/me").json()
    other_proj = project(other, other_me)
    other_job = terminal(other, submit(other, other_proj["id"]).json()["id"])
    assert other.get(f"/api/analyses/{other_job['id']}/artifacts/{artifact_id}").status_code == 404


@pytest.fixture(params=["sqlite", "postgres"])
def migration_database(settings, request):
    if request.param == "sqlite":
        database = Database(settings)
        yield database
        database.engine.dispose()
        return
    if not os.environ.get("BR_TEST_DATABASE_URL"):
        pytest.skip("set BR_TEST_DATABASE_URL to a disposable PostgreSQL database")
    url = make_url(os.environ["BR_TEST_DATABASE_URL"])
    root = Database(replace(settings, database_url=url.render_as_string(hide_password=False)))
    schema = "beta_" + uuid.uuid4().hex
    with root.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    database = Database(replace(settings, database_url=url.render_as_string(hide_password=False)))
    try:
        yield database
    finally:
        database.engine.dispose()
        with root.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        root.engine.dispose()


def test_migration_0001_populated_upgrade_preserves_evidence_and_roles(migration_database):
    database = migration_database
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
        connection.execute(
            text("INSERT INTO users VALUES ('u','issuer','subject','mail@example.test','Old',1)")
        )
        connection.execute(
            text("INSERT INTO organizations VALUES ('o','Old','free',NULL,NULL,'none',0,1)")
        )
        connection.execute(text("INSERT INTO memberships VALUES ('u','o','member')"))
        connection.execute(text("INSERT INTO projects VALUES ('p','o','Old',1)"))
        connection.execute(
            text(
                "INSERT INTO analyses VALUES ('a','p','o','u','before','after','succeeded',NULL,1,2,3,:result)"
            ),
            {"result": '{"schema_version":1}'},
        )
        connection.execute(text("INSERT INTO sessions VALUES ('hash','u','csrf',9999999999)"))
    assert database.ready() is False
    database.migrate()
    database.migrate()
    assert database.ready()
    with database.session() as session:
        assert session.get(Membership, ("u", "o")).role == "developer"
        assert session.get(Analysis, "a").result == {"schema_version": 1}
        assert session.get(Analysis, "a").normalized_version is None
        assert session.get(Project, "p").description == ""
        assert session.get(LoginSession, "hash").id
        assert session.scalar(select(func.count()).select_from(Finding)) == 0
        from_user = session.execute(text("SELECT email_verified FROM users WHERE id='u'")).scalar()
        assert not from_user
    with database.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        if connection.dialect.name == "sqlite":
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


@pytest.fixture
def backend_client(migration_database, settings, demo_results, monkeypatch, caplog):
    settings = replace(
        settings,
        database_url=migration_database.engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    app = create_app(settings)
    logger = logging.getLogger("blastradius")
    caplog.handler.setLevel(logging.WARNING)
    logger.addHandler(caplog.handler)
    with TestClient(app) as client:
        try:
            yield client, app
        finally:
            logger.removeHandler(caplog.handler)


def test_atomic_project_slots_and_export_accounting(backend_client):
    client, app = backend_client
    me = login(client)
    org_id = me["organizations"][0]["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(
                    "/api/projects",
                    json={"organization_id": org_id, "name": "Racing"},
                ),
                range(8),
            )
        )
    assert sorted(r.status_code for r in responses) == [201] + [402] * 7
    project_id = next(r.json()["id"] for r in responses if r.status_code == 201)
    job = terminal(client, submit(client, project_id).json()["id"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(
            pool.map(
                lambda _: client.get(f"/api/analyses/{job['id']}/report?format=json").status_code,
                range(8),
            )
        )
    assert statuses == [200] * 8
    assert client.get(f"/api/organizations/{org_id}/usage").json()["exports"] == 8
    assert client.delete(f"/api/analyses/{job['id']}").status_code == 204
    usage = client.get(f"/api/organizations/{org_id}/usage").json()
    assert usage["analyses"] == 1 and usage["exports"] == 8


def test_bounded_cleanup_on_both_databases(migration_database):
    database = migration_database
    database.migrate()
    with database.session(write=True) as session:
        user = provision(session, "issuer", "subject", "User", "user@example.test")
        org = session.scalar(select(Organization))
        org.plan = "enterprise"
        org.plan_limits = EnterpriseLimits(
            projects=2, analyses_per_month=10, retention_days=12, members=3
        ).model_dump()
        project = Project(organization_id=org.id, name="Old")
        session.add(project)
        session.flush()
        for days in (11, 13, 14):
            session.add(
                Analysis(
                    project_id=project.id,
                    organization_id=org.id,
                    created_by=user.id,
                    base_label="base",
                    candidate_label="head",
                    status="failed",
                    created_at=time.time() - days * 86400,
                )
            )
    assert cleanup(database, 1) == 1
    assert cleanup(database, 1) == 1
    assert cleanup(database, 1) == 0
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 1
