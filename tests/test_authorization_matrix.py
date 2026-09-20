from __future__ import annotations

import ast
import json
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
import pytest
from authlib.jose import JsonWebKey
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import select

from blastradius.server.app import create_app
from blastradius.server.auth import create_session, token_hash
from blastradius.server.config import Settings
from blastradius.server.github_api import GitHubAPI, WRITE_PERMISSIONS
from blastradius.server.models import (
    Analysis,
    AnalysisArtifact,
    GitHubInstallation,
    Invitation,
    LoginSession,
    Membership,
    Organization,
    Project,
    User,
)
from blastradius.server.schemas import PolicyInput

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("owner", "admin", "developer", "viewer")
MANAGERS = ROLES[:2]


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    roles: tuple[str, ...] = ROLES
    body: str = ""
    success: int = 200
    tenant: bool = True


ROUTES = [
    Route("GET", "/api/projects?organization_id={org}"),
    Route("POST", "/api/projects", MANAGERS, "project", 201),
    Route("GET", "/api/projects/{project}"),
    Route("PATCH", "/api/projects/{project}", MANAGERS, "name"),
    Route("DELETE", "/api/projects/{project}", MANAGERS, success=204),
    Route("GET", "/api/projects/{project}/analyses"),
    Route("GET", "/api/projects/{project}/policy"),
    Route("PUT", "/api/projects/{project}/policy", MANAGERS, "empty"),
    Route("DELETE", "/api/projects/{project}/policy", MANAGERS, success=204),
    Route("POST", "/api/analyses", ROLES[:3], "analysis", 202),
    Route("GET", "/api/analyses/{analysis}"),
    Route("DELETE", "/api/analyses/{analysis}", ROLES[:3], success=204),
    *[
        Route("GET", f"/api/analyses/{{analysis}}/report?format={fmt}")
        for fmt in ("web", "json", "markdown", "sarif")
    ],
    Route("GET", "/api/analyses/{analysis}/findings"),
    Route("GET", "/api/analyses/{analysis}/paths"),
    Route("GET", "/api/analyses/{analysis}/artifacts"),
    *[
        Route("GET", f"/api/analyses/{{analysis}}/artifacts/{{{fmt}}}")
        for fmt in ("json", "markdown", "sarif")
    ],
    Route("PATCH", "/api/organizations/{org}", MANAGERS, "name"),
    Route("DELETE", "/api/organizations/{org}", ("owner",), success=204),
    Route("GET", "/api/organizations/{org}/usage"),
    Route("GET", "/api/organizations/{org}/billing", ("owner",)),
    Route("GET", "/api/organizations/{org}/members", MANAGERS),
    Route("PATCH", "/api/organizations/{org}/members/{target}", MANAGERS, "role"),
    Route("DELETE", "/api/organizations/{org}/members/{target}", MANAGERS, success=204),
    Route("POST", "/api/organizations/{org}/invitations", MANAGERS, "invitation", 201),
    Route("GET", "/api/organizations/{org}/invitations", MANAGERS),
    Route("DELETE", "/api/organizations/{org}/invitations/{invite}", MANAGERS, success=204),
    Route("GET", "/api/organizations/{org}/policy"),
    Route("PUT", "/api/organizations/{org}/policy", MANAGERS, "empty"),
    Route("DELETE", "/api/organizations/{org}/policy", MANAGERS, success=204),
    Route("GET", "/api/organizations/{org}/audit", MANAGERS),
    Route("GET", "/api/organizations/{org}/github/installations"),
    Route("GET", "/api/projects/{project}/github"),
    Route("PUT", "/api/projects/{project}/github", MANAGERS, "github"),
    Route("DELETE", "/api/projects/{project}/github", MANAGERS, success=204),
    Route("GET", "/api/account/sessions", tenant=False),
    Route("DELETE", "/api/account/sessions/{own_session}", success=204, tenant=False),
    Route("DELETE", "/api/account/sessions", success=204, tenant=False),
    Route("POST", "/api/organizations", body="name", success=201, tenant=False),
    Route("POST", "/api/auth/logout", tenant=False),
]
ACCEPT = Route("POST", "/api/invitations/accept", body="accept", tenant=False)


def payload(route, ids):
    return {
        "": None,
        "empty": {},
        "name": {"name": "Changed"},
        "project": {"name": "Created", "organization_id": ids["org"]},
        "role": {"role": "viewer"},
        "accept": {"token": "A" * 43},
        "invitation": {"email": "new@example.test", "role": "developer"},
        "github": {"installation_id": ids["installation"], "repository_id": ids["repository"]},
        "analysis": {
            "project_id": ids["project"],
            "before_files": {"main.tf": (ROOT / "examples/safe/main.tf").read_text()},
            "after_files": {"main.tf": (ROOT / "examples/vulnerable/main.tf").read_text()},
        },
    }[route.body]


def provider(request):
    path = request.url.path
    if path.endswith("/access_tokens"):
        body = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "token": f"local-{body['repository_ids'][0]}",
                "permissions": body["permissions"],
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            },
        )
    if path.startswith("/app/installations/"):
        installation = int(path.rsplit("/", 1)[-1])
        return httpx.Response(
            200,
            json={
                "id": installation,
                "app_id": 40,
                "account": {"id": installation + 100, "login": f"tenant-{installation + 100}"},
                "permissions": dict(WRITE_PERMISSIONS),
                "suspended_at": None,
            },
        )
    if path == "/installation/repositories":
        repo = int(request.headers["authorization"].rsplit("-", 1)[-1])
        return httpx.Response(
            200,
            json={
                "total_count": 1,
                "repositories": [
                    {
                        "id": repo,
                        "full_name": f"tenant-{repo}/infra",
                        "owner": {"id": repo, "login": f"tenant-{repo}"},
                        "default_branch": "main",
                    }
                ],
            },
        )
    raise AssertionError(f"Unexpected provider request {request.method} {path}")


def actor(app, credentials):
    cookie, csrf, _ = credentials
    client = TestClient(app, base_url=app.state.settings.public_url)
    client.cookies.set("br_session", cookie)
    client.headers.update({"X-CSRF-Token": csrf, "Origin": app.state.settings.public_url})
    return client


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    directory = tmp_path_factory.mktemp("auth-matrix")
    key_path = directory / "local-test-key.pem"
    key_path.write_bytes(
        JsonWebKey.generate_key("RSA", 2048, is_private=True).as_pem(is_private=True)
    )
    key_path.chmod(0o600)
    settings = Settings(
        environment="test",
        auth_mode="demo",
        public_url="http://testserver",
        data_dir=directory / "data",
        database_url=f"sqlite:///{directory / 'seed.db'}",
        static_dir=directory / "no-static",
        rate_limit=10000,
        auth_rate_limit=10000,
        github_app_id=40,
        github_app_slug="local-test",
        github_private_key_file=key_path,
        github_webhook_secret="isolated-test-only-" * 3,
    )
    tenants, sessions = {}, {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("blastradius.server.app.build_demos", lambda _: {})
        app = create_app(settings)
        with TestClient(app):
            for index, tenant in enumerate(("A", "B"), start=1):
                with app.state.db.session(write=True) as session:
                    org = Organization(
                        name=tenant,
                        plan="team",
                        policy_version=index,
                        policy=PolicyInput.model_validate(
                            {"thresholds": {"minimum_security_score": index}}
                        ).model_dump(),
                    )
                    session.add(org)
                    session.flush()
                    project = Project(name=f"Private-{tenant}", organization_id=org.id)
                    session.add(project)
                    users = {}
                    for role in (*ROLES, "target"):
                        user = User(
                            issuer="https://local.example", subject=f"{tenant}-{role}", name=role
                        )
                        session.add(user)
                        session.flush()
                        users[role] = user.id
                        session.add(
                            Membership(
                                user_id=user.id,
                                organization_id=org.id,
                                role=role if role != "target" else "developer",
                            )
                        )
                        response = Response()
                        login = create_session(response, session, settings, user.id)
                        session.flush()
                        sessions[tenant, role] = (
                            SimpleCookie(response.headers["set-cookie"])["br_session"].value,
                            login.csrf_token,
                            login.id,
                        )
                    session.add(
                        GitHubInstallation(
                            id=index * 10,
                            organization_id=org.id,
                            account_id=index * 10 + 100,
                            account_login=f"tenant-{index * 10 + 100}",
                        )
                    )
                    invitation = Invitation(
                        organization_id=org.id,
                        email="recipient@example.test",
                        role="developer",
                        token_hash=token_hash(tenant * 43),
                        created_by=users["owner"],
                        expires_at=time.time() + 3600,
                    )
                    session.add(invitation)
                    session.flush()
                    tenants[tenant] = {
                        "org": org.id,
                        "project": project.id,
                        "invite": invitation.id,
                        "installation": index * 10,
                        "repository": index * 10 + 100,
                        **users,
                    }
                owner = actor(app, sessions[tenant, "owner"])
                response = owner.post(
                    "/api/analyses",
                    json=payload(
                        next(route for route in ROUTES if route.body == "analysis"), tenants[tenant]
                    ),
                )
                assert response.status_code == 202, response.text
                tenants[tenant]["analysis"] = response.json()["id"]
                owner.close()
            app.state.jobs.shutdown()
            with app.state.db.session() as session:
                for tenant in tenants.values():
                    job = session.get(Analysis, tenant["analysis"])
                    assert job.status == "succeeded" and job.decision == "BLOCK CHANGE"
                    for artifact in session.scalars(
                        select(AnalysisArtifact).where(AnalysisArtifact.analysis_id == job.id)
                    ):
                        tenant[artifact.format] = artifact.id
    return settings, directory / "seed.db", tenants, sessions


@pytest.fixture
def matrix(seed, tmp_path, monkeypatch):
    settings, seed_path, tenants, sessions = seed
    db_path = tmp_path / "isolated.db"
    with sqlite3.connect(seed_path) as source, sqlite3.connect(db_path) as target:
        source.backup(target)
    settings = replace(settings, database_url=f"sqlite:///{db_path}", data_dir=tmp_path / "data")
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: {})
    app = create_app(settings)
    app.state.github.api_factory = lambda: GitHubAPI(
        settings, transport=httpx.MockTransport(provider)
    )
    with TestClient(app):
        yield app, tenants, sessions


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: f"{r.method}:{r.path}")
@pytest.mark.parametrize("role", ROLES)
def test_route_role_and_tenant_boundary(matrix, route, role):
    app, tenants, sessions = matrix
    ids = dict(tenants["A"], own_session=sessions["A", role][2])
    client = actor(app, sessions["A", role])
    if route.tenant:
        foreign = actor(app, sessions["B", role])
        assert (
            foreign.request(
                route.method, route.path.format(**ids), json=payload(route, ids)
            ).status_code
            == 404
        )
        foreign.close()
    response = client.request(route.method, route.path.format(**ids), json=payload(route, ids))
    assert response.status_code == (route.success if role in route.roles else 403), response.text
    if route.method == "GET" and route.path == "/api/organizations/{org}/policy":
        assert response.json()["version"] == 1
        assert response.json()["policy"]["thresholds"] == {"minimum_security_score": 1}
    if route.path == "/api/organizations/{org}/github/installations":
        rows = response.json()["installations"]
        assert len(rows) == 1 and rows[0]["id"] == ids["installation"]
        assert rows[0]["account_login"] == "tenant-110" and rows[0]["status"] == "active"
    client.close()


@pytest.mark.parametrize(
    ("route", "boundary"),
    [
        (route, boundary)
        for route in [*ROUTES, ACCEPT]
        for boundary in ("anonymous", "expired", "revoked", "csrf", "origin")
        if route.method != "GET" or boundary not in ("csrf", "origin")
    ],
    ids=lambda value: f"{value.method}:{value.path}" if isinstance(value, Route) else value,
)
def test_route_session_csrf_and_origin(matrix, route, boundary):
    app, tenants, sessions = matrix
    client = actor(app, sessions["A", "owner"])
    cookie, _, sid = sessions["A", "owner"]
    ids = dict(tenants["A"], own_session=sid)
    if boundary == "anonymous":
        client.cookies.clear()
    elif boundary in ("expired", "revoked"):
        with app.state.db.session(write=True) as session:
            login = session.get(LoginSession, token_hash(cookie))
            if boundary == "expired":
                login.expires_at = time.time() - 1
            else:
                session.delete(login)
    elif boundary == "csrf":
        client.headers.pop("X-CSRF-Token")
    else:
        client.headers["Origin"] = "http://localhost"
        client.headers["X-Forwarded-Host"] = "testserver"
    response = client.request(route.method, route.path.format(**ids), json=payload(route, ids))
    assert response.status_code == (401 if route.method == "GET" else 403), response.text
    client.close()


def test_nested_identifiers_and_own_sessions(matrix):
    app, tenants, sessions = matrix
    own, other = tenants["A"], tenants["B"]
    client = actor(app, sessions["A", "owner"])
    for fmt in ("json", "markdown", "sarif"):
        assert (
            client.get(f"/api/analyses/{own['analysis']}/artifacts/{other[fmt]}").status_code == 404
        )
    assert (
        client.delete(f"/api/organizations/{own['org']}/invitations/{other['invite']}").status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/organizations/{own['org']}/members/{other['owner']}", json={"role": "viewer"}
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/organizations/{own['org']}/members/{other['owner']}").status_code
        == 404
    )
    assert (
        client.put(
            f"/api/projects/{own['project']}/github",
            json={
                "installation_id": other["installation"],
                "repository_id": other["repository"],
            },
        ).status_code
        == 404
    )
    assert client.delete(f"/api/account/sessions/{sessions['B', 'owner'][2]}").status_code == 404
    assert {row["id"] for row in client.get("/api/account/sessions").json()["sessions"]} == {
        sessions["A", "owner"][2]
    }
    assert {row["id"] for row in client.get("/api/projects").json()["projects"]} == {own["project"]}
    client.close()


def test_authenticated_route_inventory():
    renames = {
        "{organization_id}": "{org}",
        "{project_id}": "{project}",
        "{analysis_id}": "{analysis}",
        "{user_id}": "{target}",
        "{invitation_id}": "{invite}",
        "{session_id}": "{own_session}",
        "{artifact_id}": "{json}",
    }
    covered = {(route.method, route.path.split("?")[0]) for route in [*ROUTES, ACCEPT]}
    for filename in ("app.py", "lifecycle.py", "github_routes.py"):
        tree = ast.parse((ROOT / "blastradius/server" / filename).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "require_user"
                for call in ast.walk(node)
            ):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                if decorator.func.attr not in ("get", "post", "patch", "put", "delete"):
                    continue
                path = ast.literal_eval(decorator.args[0])
                for original, replacement in renames.items():
                    path = path.replace(original, replacement)
                assert (decorator.func.attr.upper(), path) in covered, (filename, path)
