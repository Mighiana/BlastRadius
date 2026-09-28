from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi", reason="install .[server,dev] for GitHub App tests")
pytest.importorskip("sqlalchemy", reason="install .[server,dev] for GitHub App tests")

from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from blastradius.server.app import create_app
from blastradius.server.admin import assign_plan
from blastradius.server.config import Settings
from blastradius.server.events import event_summary
from blastradius.server.github_api import (
    GitHubAPI,
    GitHubError,
    READ_PERMISSIONS,
    WRITE_PERMISSIONS,
)
from blastradius.server.github_publish import MARKER, publish, summary
from blastradius.server.github_routes import register_installation
from blastradius.server.github_types import Repository
from blastradius.server.models import (
    Analysis,
    GitHubDelivery,
    GitHubInstallation,
    GitHubRun,
    Membership,
    Organization,
    RepositoryConnection,
    Usage,
)
from blastradius.server.persistence import cleanup
from blastradius.server.quotas import period

BASE = "a" * 40
HEAD = "b" * 40
ROOT = Path(__file__).resolve().parents[1]
TOKEN = "test-installation-secret-not-for-logs"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class Provider:
    def __init__(self):
        self.permissions = dict(WRITE_PERMISSIONS)
        self.repository = {
            "id": 20,
            "full_name": "acme/infra",
            "owner": {"id": 30, "login": "acme"},
            "default_branch": "main",
        }
        self.pull = {
            "number": 1,
            "state": "open",
            "base": {"sha": BASE, "ref": "main", "repo": {"id": 20}},
            "head": {"sha": HEAD, "ref": "feature/network", "repo": {"id": 20}},
        }
        self.files = {
            BASE: (ROOT / "examples/safe/main.tf").read_bytes(),
            HEAD: (ROOT / "examples/vulnerable/main.tf").read_bytes(),
        }
        self.checks = []
        self.comments = []
        self.requests = []
        self.writes = []
        self.truncated = False
        self.entry_path = "main.tf"
        self.entry_mode = "100644"
        self.transient_reads = 0
        self.uncertain_check = False
        self.uncertain_comment = False
        self.hidden_comment = False
        self.stale_at_pull = 0
        self.pull_reads = 0
        self.expiry = 3600
        self.denied_prefix = ""

    def event(self, action="opened"):
        return {
            "action": action,
            "number": self.pull["number"],
            "installation": {"id": 10},
            "repository": {"id": 20},
            "pull_request": copy.deepcopy(self.pull),
        }

    def __call__(self, request):
        assert request.url.host == "api.github.com"
        path = request.url.path
        method = request.method
        self.requests.append((method, path))
        body = json.loads(request.content) if request.content else None
        if method != "GET" and not path.endswith("access_tokens"):
            self.writes.append((method, path, body))
        if self.denied_prefix and path.startswith(self.denied_prefix):
            return httpx.Response(403, json={"message": TOKEN})
        if method == "GET" and self.transient_reads:
            self.transient_reads -= 1
            return httpx.Response(503, json={"message": TOKEN})
        if path == "/app/installations/10":
            return httpx.Response(
                200,
                json={
                    "id": 10,
                    "app_id": 40,
                    "account": {"id": 30, "login": "acme"},
                    "permissions": self.permissions,
                    "suspended_at": None,
                },
            )
        if path == "/app/installations/10/access_tokens":
            assert body["repository_ids"] == [20]
            assert body["permissions"] in [READ_PERMISSIONS, WRITE_PERMISSIONS]
            expires = datetime.now(timezone.utc) + timedelta(seconds=self.expiry)
            return httpx.Response(
                201,
                json={
                    "token": TOKEN,
                    "expires_at": expires.isoformat(),
                    "permissions": body["permissions"],
                },
            )
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if path == "/installation/repositories":
            return httpx.Response(200, json={"total_count": 1, "repositories": [self.repository]})
        prefix = f"/repos/{self.repository['full_name']}"
        if path == f"{prefix}/pulls/1":
            self.pull_reads += 1
            pull = copy.deepcopy(self.pull)
            if self.stale_at_pull and self.pull_reads >= self.stale_at_pull:
                pull["head"]["sha"] = "c" * 40
            return httpx.Response(200, json=pull)
        if "/git/commits/" in path:
            sha = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"sha": sha, "tree": {"sha": sha}})
        if "/git/trees/" in path:
            sha = path.rsplit("/", 1)[1]
            data = self.files[sha]
            return httpx.Response(
                200,
                json={
                    "sha": sha,
                    "truncated": self.truncated,
                    "tree": [
                        {
                            "path": self.entry_path,
                            "mode": self.entry_mode,
                            "type": "blob",
                            "sha": git_blob(data),
                            "size": len(data),
                        }
                    ],
                },
            )
        if "/git/blobs/" in path:
            sha = path.rsplit("/", 1)[1]
            data = next(data for data in self.files.values() if git_blob(data) == sha)
            return httpx.Response(
                200,
                json={
                    "sha": sha,
                    "size": len(data),
                    "encoding": "base64",
                    "content": base64.b64encode(data).decode(),
                },
            )
        if path.endswith("/check-runs") and method == "GET":
            return httpx.Response(
                200, json={"total_count": len(self.checks), "check_runs": self.checks}
            )
        if path == f"{prefix}/check-runs" and method == "POST":
            check = {**body, "id": 100 + len(self.checks), "app": {"id": 40}}
            self.checks.append(check)
            if self.uncertain_check:
                self.uncertain_check = False
                raise httpx.ReadTimeout(TOKEN)
            return httpx.Response(201, json=check)
        if "/check-runs/" in path and method == "PATCH":
            check = next(c for c in self.checks if str(c["id"]) == path.rsplit("/", 1)[1])
            check.update(body)
            return httpx.Response(200, json=check)
        if path == f"{prefix}/issues/1/comments":
            if method == "GET":
                return httpx.Response(200, json=[] if self.hidden_comment else self.comments)
            comment = {
                **body,
                "id": 200 + len(self.comments),
                "user": {"id": 60, "type": "Bot"},
                "performed_via_github_app": {"id": 40},
            }
            self.comments.append(comment)
            if self.uncertain_comment:
                self.uncertain_comment = False
                raise httpx.ReadTimeout(TOKEN)
            return httpx.Response(201, json=comment)
        if "/issues/comments/" in path and method == "PATCH":
            comment = next(c for c in self.comments if str(c["id"]) == path.rsplit("/", 1)[1])
            comment.update(body)
            return httpx.Response(200, json=comment)
        raise AssertionError(f"unexpected mocked request {method} {path}")


@pytest.fixture
def settings(tmp_path):
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    pem = tmp_path / "github.pem"
    pem.write_bytes(key.as_pem(is_private=True))
    pem.chmod(0o600)
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "static",
        auth_mode="demo",
        public_url="http://testserver",
        rate_limit=1000,
        admin_enabled=True,
        github_app_id=40,
        github_app_slug="blastradius-test",
        github_private_key_file=pem,
        github_webhook_secret="test-secret-" * 4,
    )


@pytest.fixture
def harness(settings, monkeypatch):
    provider = Provider()

    def factory():
        return GitHubAPI(settings, transport=httpx.MockTransport(provider))

    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: {})
    monkeypatch.setattr("blastradius.server.github_routes.GitHubAPI", lambda _: factory())
    app = create_app(settings)
    app.state.github.api_factory = factory
    with TestClient(app) as client:
        csrf = client.get("/api/me").json()["csrf_token"]
        assert client.post("/api/auth/demo", headers={"X-CSRF-Token": csrf}).status_code == 200
        me = client.get("/api/me").json()
        client.headers["X-CSRF-Token"] = me["csrf_token"]
        org_id = me["organizations"][0]["id"]
        project = client.post(
            "/api/projects", json={"name": "Infra", "organization_id": org_id}
        ).json()
        register_installation(app.state.db, settings, org_id, 10, 30, "verified-ticket-1")
        assert (
            client.put(
                f"/api/projects/{project['id']}/github",
                json={"installation_id": 10, "repository_id": 20},
            ).status_code
            == 200
        )
        provider.requests.clear()
        yield app, client, provider, project, me


def send(harness, event=None, delivery="delivery-1", name="pull_request", raw=None, signature=None):
    app, client, provider, _, _ = harness
    body = raw if raw is not None else json.dumps(event or provider.event()).encode()
    signature = (
        signature
        or "sha256="
        + hmac.new(
            app.state.settings.github_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
    )
    return client.post(
        "/api/github/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": delivery,
            "X-GitHub-Event": name,
            "Content-Type": "application/json",
        },
    )


def drain(app):
    app.state.github.executor.submit(lambda: None).result(timeout=30)


def run_record(app):
    with app.state.db.session() as session:
        return session.scalar(select(GitHubRun))


def test_product_milestones_and_replay_are_exactly_once(harness):
    app, client, _, project, _ = harness
    with app.state.db.session() as session:
        assert event_summary(session)["counts"]["github_connected"] == 1
    assert client.put(
        f"/api/projects/{project['id']}/github",
        json={"installation_id": 10, "repository_id": 20},
    ).status_code == 200
    with app.state.db.session() as session:
        assert event_summary(session)["counts"]["github_connected"] == 1
    assert send(harness).status_code == 202
    drain(app)
    with app.state.db.session() as session:
        before = event_summary(session)["counts"]
    assert before["analysis_started"] == before["analysis_completed"] == before["block_result"] == 1
    assert send(harness, delivery="commercial-replay").json()["status"] == "duplicate"
    drain(app)
    with app.state.db.session() as session:
        assert event_summary(session)["counts"] == before


@pytest.mark.parametrize("response", [{"result": {}}, [], None])
def test_malformed_worker_response_finishes_run(harness, monkeypatch, response):
    app, client, provider, _, _ = harness
    monkeypatch.setattr("blastradius.server.github_service.execute", lambda *_: response)
    assert send(harness).status_code == 202
    drain(app)
    run = run_record(app)
    job = client.get(f"/api/analyses/{run.analysis_id}").json()
    assert job["status"] == "failed" and job["result"] is None and job["decision"] is None
    assert job["error"] == "invalid_worker_result"
    assert run.status == "published"
    assert provider.checks[0]["conclusion"] == "failure"
    assert "SAFE TO MERGE" not in provider.comments[0]["body"]
    assert client.get(f"/api/analyses/{run.analysis_id}/report").status_code == 409
    assert client.get(f"/api/analyses/{run.analysis_id}/artifacts").json()["artifacts"] == []
    with app.state.db.session() as session:
        assert session.get(GitHubDelivery, "delivery-1").status == "handled"


def test_base_retarget_with_unchanged_head_recomputes_result(harness):
    app, _, provider, _, _ = harness
    provider.files[BASE] = provider.files[HEAD]
    assert send(harness).json() == {"status": "queued"}
    drain(app)
    assert provider.checks[-1]["conclusion"] == "success"
    new_base = "c" * 40
    provider.pull["base"].update(sha=new_base, ref="release")
    provider.files[new_base] = (ROOT / "examples/safe/main.tf").read_bytes()
    event = provider.event("edited")
    event["changes"] = {"base": {"ref": {"from": "main"}, "sha": {"from": BASE}}}
    assert send(harness, event, delivery="retarget").json() == {"status": "queued"}
    drain(app)
    assert provider.checks[-1]["head_sha"] == HEAD
    assert provider.checks[-1]["conclusion"] == "failure"
    assert "BLOCK CHANGE" in provider.comments[0]["body"]
    with app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 2
        assert session.scalar(select(func.count()).select_from(GitHubRun)) == 2
    requests = len(provider.requests)
    assert send(harness, event, delivery="retarget-replay").json() == {"status": "duplicate"}
    assert len(provider.requests) == requests


def test_pr_to_real_isolated_analysis_check_comment_and_replay(harness, caplog):
    app, client, provider, project, _ = harness
    assert send(harness).json() == {"status": "queued"}
    drain(app)
    run = run_record(app)
    assert run.status == "published", run.error
    job = client.get(f"/api/analyses/{run.analysis_id}").json()
    assert job["decision"] == "BLOCK CHANGE"
    assert job["input_type"] == "github" and job["candidate_sha"] == HEAD
    assert job["policy_snapshot"]["source"] == "default"
    assert len(provider.checks) == len(provider.comments) == 1
    assert provider.checks[0]["status"] == "completed"
    assert provider.checks[0]["conclusion"] == "failure"
    assert "New critical paths: 1" in provider.comments[0]["body"]
    assert (
        f"/dashboard?project={project['id']}&analysis={run.analysis_id}"
        in provider.comments[0]["body"]
    )
    assert send(harness).json() == {"status": "duplicate"}
    assert send(harness, delivery="other-id").json() == {"status": "duplicate"}
    assert send(harness, provider.event("reopened"), delivery="delivery-2").json() == {
        "status": "queued"
    }
    drain(app)
    assert len(provider.checks) == len(provider.comments) == 1
    with app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 1
        assert session.get(Usage, (project["organization_id"], period())).analyses == 1
    assert TOKEN not in caplog.text and "PRIVATE KEY" not in caplog.text


@pytest.mark.parametrize("plan", ["free", "pro", "team"])
def test_github_policy_entitlements_reach_real_worker_and_filtered_history(harness, plan):
    app, client, _, project, _ = harness
    org_id = project["organization_id"]
    assign_plan(app.state.db, org_id, "team")
    policy = {
        "gate": {
            "block_new_critical_paths": False,
            "block_new_sensitive_exposure": False,
            "block_public_admin_ports": False,
        },
    }
    assert client.put(f"/api/organizations/{org_id}/policy", json=policy).status_code == 200
    assign_plan(app.state.db, org_id, plan)
    assert send(harness).status_code == 202
    drain(app)
    run = run_record(app)
    job = client.get(f"/api/analyses/{run.analysis_id}").json()
    assert job["status"] == "succeeded"
    assert job["policy_snapshot"]["source"] == ("organization" if plan == "team" else "default")
    assert (job["decision"] == "BLOCK CHANGE") is (plan != "team")
    assert job["result"]["after"]["attack_paths"]
    history = client.get(
        f"/api/projects/{project['id']}/analyses",
        params={"input_type": "github", "branch": "feature/network", "status": "succeeded"},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["analyses"][0]["id"] == job["id"]
    assert (
        client.get(f"/api/projects/{project['id']}/analyses", params={"input_type": "hcl"}).json()[
            "total"
        ]
        == 0
    )
    assert client.get(f"/api/organizations/{org_id}/usage").json()["analyses"] == 1


@pytest.mark.parametrize("bad", ["sha1=abc", "sha256=" + "0" * 64, "not-a-signature"])
def test_forged_signatures_do_not_queue(harness, bad):
    assert send(harness, signature=bad).status_code == 401
    assert not harness[2].requests and run_record(harness[0]) is None


def test_raw_body_changes_conflicts_oversize_and_unsupported(harness):
    app, _, provider, _, _ = harness
    raw = json.dumps(provider.event()).encode()
    sig = (
        "sha256="
        + hmac.new(
            app.state.settings.github_webhook_secret.encode(), raw, hashlib.sha256
        ).hexdigest()
    )
    assert send(harness, raw=raw + b" ", signature=sig).status_code == 401
    assert send(harness, raw=b"x" * (app.state.settings.max_body_bytes + 1)).status_code == 413
    assert send(harness, raw=b"{}", name="push").json() == {"status": "ignored"}
    assert send(harness, raw=b'{"x": 1}', name="push").status_code == 409
    assert send(harness, {"action": "closed"}, delivery="closed").json() == {"status": "ignored"}
    assert send(harness, raw=b"[[]]", delivery="bad").status_code == 400
    assert not provider.requests


@pytest.mark.parametrize(
    "field",
    [
        "installation",
        "repository",
        "number",
        "base_sha",
        "head_sha",
        "base_repo",
        "head_repo",
        "ref",
    ],
)
def test_payload_identity_mismatches_cannot_analyze_or_publish(harness, field):
    app, _, provider, _, _ = harness
    event = provider.event()
    if field in ("installation", "repository"):
        event[field]["id"] = 999
    elif field == "number":
        event["pull_request"]["number"] = 2
    elif field in ("base_sha", "head_sha"):
        event["pull_request"][field.split("_")[0]]["sha"] = "d" * 40
    elif field in ("base_repo", "head_repo"):
        event["pull_request"][field.split("_")[0]]["repo"]["id"] = 999
    else:
        event["pull_request"]["head"]["ref"] = "other-branch"
    assert send(harness, event).status_code == 202
    drain(app)
    assert run_record(app) is None and not provider.writes


@pytest.mark.parametrize("stale_at", [1, 2, 3, 4, 5])
def test_head_is_rechecked_before_every_publishing_mutation(harness, stale_at):
    app, _, provider, _, _ = harness
    provider.stale_at_pull = stale_at
    send(harness)
    drain(app)
    assert not provider.comments
    if stale_at <= 3:
        assert not provider.writes
    if provider.checks:
        assert provider.checks[0].get("conclusion") != "success"


def test_forks_are_read_through_base_repo_and_never_executed(harness):
    app, _, provider, _, _ = harness
    provider.pull["head"]["repo"]["id"] = 999
    send(harness)
    drain(app)
    assert run_record(app).head_repository_id == 999
    assert run_record(app).status == "published"
    assert ("GET", f"/repos/acme/infra/git/commits/{HEAD}") in provider.requests
    assert all("fork" not in path for _, path in provider.requests)


def test_fork_unreadable_fails_closed_with_review(harness):
    app, _, provider, _, _ = harness
    provider.pull["head"]["repo"]["id"] = 999
    provider.denied_prefix = f"/repos/acme/infra/git/commits/{HEAD}"
    send(harness)
    drain(app)
    assert provider.checks[0]["conclusion"] == "failure"
    assert "REVIEW REQUIRED" in provider.comments[0]["body"]


@pytest.mark.parametrize("action", ["suspend", "deleted", "removed"])
def test_lifecycle_revocation_stops_future_work(harness, action):
    app, client, provider, project, _ = harness
    event = {"action": action, "installation": {"id": 10}, "repositories_removed": [{"id": 20}]}
    name = "installation_repositories" if action == "removed" else "installation"
    assert send(harness, event, name=name).json() == {"status": "handled"}
    assert send(harness, delivery="pr-after-revoked").json() == {"status": "ignored"}
    status = client.get(f"/api/projects/{project['id']}/github").json()
    assert status["connection"]["status"] == "revoked" and not provider.requests
    send(
        harness,
        {"action": "unsuspend", "installation": {"id": 10}},
        name="installation",
        delivery="unsuspend",
    )
    assert send(harness, delivery="still-revoked").json() == {"status": "duplicate"}
    assert not provider.requests


def test_removed_provider_permissions_reject_without_work(harness):
    app, _, provider, _, _ = harness
    provider.permissions["checks"] = "read"
    send(harness)
    drain(app)
    assert run_record(app) is None and not provider.writes
    with app.state.db.session() as session:
        assert session.scalar(select(RepositoryConnection)).status == "revoked"


def test_repository_mismatch_rejects_without_work(harness):
    app, _, provider, _, _ = harness
    provider.repository["id"] = 999
    send(harness)
    drain(app)
    assert run_record(app) is None and not provider.writes


def test_quota_failure_publishes_review_and_does_not_charge(harness):
    app, _, provider, project, _ = harness
    with app.state.db.session(write=True) as session:
        session.add(Usage(organization_id=project["organization_id"], period=period(), analyses=25))
    send(harness)
    drain(app)
    assert run_record(app).analysis_id is None
    assert run_record(app).error == "analysis_quota_exceeded"
    assert provider.checks[0]["conclusion"] == "failure"
    assert "REVIEW REQUIRED" in provider.comments[0]["body"]
    assert not any("/git/" in path for _, path in provider.requests)


@pytest.mark.parametrize(
    "fault",
    [
        "truncated",
        "symlink",
        "submodule",
        "traversal",
        "nested",
        "json",
        "vars",
        "binary",
        "lfs",
        "empty",
        "oversize",
        "module",
    ],
)
def test_unsupported_sources_never_report_safe(harness, fault):
    app, _, provider, _, _ = harness
    if fault == "truncated":
        provider.truncated = True
    elif fault in ("symlink", "submodule"):
        provider.entry_mode = "120000" if fault == "symlink" else "160000"
    elif fault in ("traversal", "nested", "json", "vars", "empty"):
        provider.entry_path = {
            "traversal": "../main.tf",
            "nested": "nested/main.tf",
            "json": "main.tf.json",
            "vars": "settings.tfvars",
            "empty": "README.md",
        }[fault]
    else:
        provider.files[HEAD] = {
            "binary": b"\0",
            "lfs": b"version https://git-lfs.github.com/spec/v1\n",
            "oversize": b"x" * (app.state.settings.max_body_bytes // 2 + 1),
            "module": b'module "hidden" { source = "./hidden" }\n',
        }[fault]
    send(harness)
    drain(app)
    assert provider.checks and provider.checks[0]["conclusion"] == "failure"
    assert "SAFE TO MERGE" not in provider.comments[0]["body"]


@pytest.mark.parametrize("uncertain", ["check", "comment"])
def test_uncertain_mutations_reconcile_without_duplicates(harness, uncertain):
    app, _, provider, _, _ = harness
    provider.uncertain_check = uncertain == "check"
    provider.uncertain_comment = uncertain == "comment"
    provider.transient_reads = 1
    send(harness)
    drain(app)
    assert run_record(app).status == "published", run_record(app).error
    assert len(provider.checks) == len(provider.comments) == 1
    assert (
        len(
            [
                1
                for method, path, _ in provider.writes
                if method == "POST" and path.endswith("check-runs")
            ]
        )
        == 1
    )
    assert (
        len(
            [
                1
                for method, path, _ in provider.writes
                if method == "POST" and path.endswith("comments")
            ]
        )
        == 1
    )


def test_uncertain_invisible_comment_is_not_reposted(harness):
    app, _, provider, _, _ = harness
    provider.uncertain_comment = provider.hidden_comment = True
    send(harness)
    drain(app)
    assert run_record(app).error == "github_comment_reconciliation_required"
    assert len(provider.comments) == 1


def test_human_marker_not_modified_and_bot_comment_updated_on_new_head(harness):
    app, _, provider, _, _ = harness
    human = {"id": 80, "body": MARKER, "user": {"id": 90, "type": "User"}}
    provider.comments.append(human)
    send(harness)
    drain(app)
    provider.pull["head"]["sha"] = "c" * 40
    provider.files["c" * 40] = provider.files[BASE]
    send(harness, delivery="second-head")
    drain(app)
    assert len(provider.comments) == 2 and human["body"] == MARKER
    assert "SAFE TO MERGE" in provider.comments[1]["body"]
    assert provider.checks[-1]["conclusion"] == "success"


def test_status_config_csrf_and_tenant_registration_boundary(harness):
    app, client, _, project, me = harness
    configuration = client.get("/api/github/config").json()
    assert configuration["available"] and configuration["self_service"] is False
    assert "secret" not in json.dumps(configuration) and "private" not in json.dumps(configuration)
    assert (
        client.put(
            f"/api/projects/{project['id']}/github",
            json={
                "installation_id": 10,
                "repository_id": 20,
            },
            headers={"X-CSRF-Token": "bad"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/projects/{project['id']}/github",
            json={
                "installation_id": 10,
                "repository_id": 20,
            },
            headers={"Origin": "https://untrusted.test"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/projects/{project['id']}/github",
            json={
                "installation_id": 999,
                "repository_id": 20,
            },
        ).status_code
        == 404
    )
    with app.state.db.session(write=True) as session:
        org = Organization(name="Other")
        session.add(org)
        session.flush()
        other_org_id = org.id
        installation = session.get(GitHubInstallation, 10)
        installation.organization_id = org.id
    assert (
        client.put(
            f"/api/projects/{project['id']}/github",
            json={
                "installation_id": 10,
                "repository_id": 20,
            },
        ).status_code
        == 404
    )
    assert client.get(f"/api/organizations/{other_org_id}/github/installations").status_code == 404
    with pytest.raises(ValueError, match="already registered"):
        register_installation(
            app.state.db, app.state.settings, project["organization_id"], 10, 30, "ticket"
        )
    with app.state.db.session(write=True) as session:
        session.get(GitHubInstallation, 10).organization_id = project["organization_id"]
        session.get(Membership, (me["user"]["id"], project["organization_id"])).role = "viewer"
    assert client.delete(f"/api/projects/{project['id']}/github").status_code == 403


def test_disabled_and_invalid_key_configuration_is_unavailable(settings, monkeypatch):
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: {})
    for changed in (
        replace(settings, github_app_id=0),
        replace(settings, github_private_key_file=Path("/missing")),
    ):
        app = create_app(changed)
        with TestClient(app) as client:
            configuration = client.get("/api/github/config").json()
            assert not configuration["available"] and configuration["installation_url"] is None
            if not changed.github_enabled:
                assert client.post("/api/github/webhook").status_code == 503


@pytest.mark.parametrize("expiry", [-1, 10, 7200])
def test_expired_or_overlong_tokens_rejected(settings, expiry):
    provider = Provider()
    provider.expiry = expiry
    with GitHubAPI(settings, httpx.MockTransport(provider)) as api:
        with pytest.raises(GitHubError, match="github_token_invalid"):
            api.installation_token(10, 20)


def test_jwt_is_short_lived_and_private_key_permissions_fail_closed(settings):
    with GitHubAPI(settings) as api:
        token = api.app_token()
        key = JsonWebKey.import_key(settings.github_private_key_file.read_bytes())
        claims = jwt.decode(token, key)
        claims.validate()
        assert claims["iss"] == "40"
        assert claims["exp"] - claims["iat"] <= 600
        settings.github_private_key_file.chmod(0o644)
        with pytest.raises(GitHubError, match="github_key_unavailable"):
            api.app_token()
    assert "test-secret" not in repr(settings)


def test_api_response_size_redirect_and_request_budget(settings):
    for response, error in [
        (
            httpx.Response(302, headers={"Location": "https://untrusted.test"}),
            "github_response_invalid",
        ),
        (httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)), "github_response_limit"),
        (httpx.Response(200, content=b"{}"), "github_budget_exceeded"),
    ]:
        with GitHubAPI(settings, httpx.MockTransport(lambda _: response)) as api:
            if error == "github_budget_exceeded":
                api.remaining = 0
            with pytest.raises(GitHubError, match=error):
                api.request("GET", "/test", TOKEN)
    with GitHubAPI(settings) as api:
        with pytest.raises(GitHubError, match="invalid_api_path"):
            api.request("GET", "//evil.test/token", TOKEN)


def test_retention_prevents_late_publication_and_run_visibility(harness):
    app, client, provider, project, _ = harness
    send(harness)
    drain(app)
    run = run_record(app)
    writes = len(provider.writes)
    with app.state.db.session(write=True) as session:
        session.get(Analysis, run.analysis_id).created_at = time.time() - 8 * 86400
        session.get(GitHubRun, run.id).created_at = time.time() - 8 * 86400
    with app.state.github.api_factory() as api:
        with pytest.raises(GitHubError, match="github_analysis_expired"):
            publish(api, app.state.db, run.id, app.state.settings)
    assert len(provider.writes) == writes
    assert client.get(f"/api/projects/{project['id']}/github").json()["latest_run"] is None
    assert cleanup(app.state.db) == 1
    assert run_record(app).analysis_id is None


def test_repository_connection_disconnect_blocks_replays(harness):
    app, client, provider, project, _ = harness
    assert client.delete(f"/api/projects/{project['id']}/github").status_code == 204
    assert send(harness).json() == {"status": "ignored"}
    assert not provider.requests
    with app.state.db.session() as session:
        assert session.scalar(select(RepositoryConnection)).status == "disconnected"


def test_blob_integrity_and_truncated_tree_validation(settings):
    provider = Provider()
    repository = Repository.model_validate(provider.repository)

    def corrupt(request):
        response = provider(request)
        if "/git/blobs/" in request.url.path:
            body = response.json()
            body["content"] = base64.b64encode(b"forged").decode()
            return httpx.Response(200, json=body)
        return response

    with GitHubAPI(settings, httpx.MockTransport(corrupt)) as api:
        with pytest.raises(GitHubError, match="github_blob_mismatch"):
            api.snapshot(TOKEN, repository, HEAD, ".")


def test_restart_recovery_and_queue_backpressure_are_redeliverable(harness):
    app, _, provider, _, _ = harness
    for _ in range(app.state.settings.max_jobs):
        assert app.state.jobs.reserve()
    try:
        assert send(harness).status_code == 503
        with app.state.db.session() as session:
            assert session.get(GitHubDelivery, "delivery-1") is None
    finally:
        for _ in range(app.state.settings.max_jobs):
            app.state.jobs.slots.release()
    with app.state.db.session(write=True) as session:
        raw = json.dumps(provider.event()).encode()
        session.add(
            GitHubDelivery(
                id="delivery-1",
                body_hash=hashlib.sha256(b"pull_request\0" + raw).hexdigest(),
                event="pull_request",
                status="queued",
            )
        )
    app.state.github.recover()
    assert send(harness).json() == {"status": "queued"}
    drain(app)
    assert run_record(app).status == "published"


def test_concurrent_deliveries_reserve_one_analysis_and_publish_once(harness):
    app, _, provider, _, _ = harness
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: send(harness, delivery=f"parallel-{i}").json(), range(4)))
    assert [r["status"] for r in results].count("queued") == 1
    assert [r["status"] for r in results].count("duplicate") == 3
    drain(app)
    assert len(provider.checks) == len(provider.comments) == 1
    with app.state.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 1


def test_permissions_removed_after_analysis_block_publication(harness, monkeypatch):
    app, _, provider, _, _ = harness

    def removed(*_args):
        provider.permissions["checks"] = "read"
        return {"error": "worker_failed"}

    monkeypatch.setattr("blastradius.server.github_service.execute", removed)
    send(harness)
    drain(app)
    assert not provider.writes
    assert run_record(app).error == "github_installation_unavailable"


def test_revocation_during_analysis_blocks_publication(harness, monkeypatch):
    app, _, provider, _, _ = harness

    def revoked(*_args):
        with app.state.db.session(write=True) as session:
            session.scalar(select(RepositoryConnection)).status = "revoked"
        return {"error": "worker_failed"}

    monkeypatch.setattr("blastradius.server.github_service.execute", revoked)
    send(harness)
    drain(app)
    assert not provider.writes
    assert run_record(app).error == "github_connection_revoked"


def test_operator_registration_checks_account_and_flag(harness):
    app, _, _, project, _ = harness
    with pytest.raises(GitHubError, match="github_installation_unavailable"):
        register_installation(
            app.state.db, app.state.settings, project["organization_id"], 10, 999, "ticket"
        )
    with pytest.raises(ValueError, match="BR_ADMIN_ENABLED"):
        register_installation(
            app.state.db,
            replace(app.state.settings, admin_enabled=False),
            project["organization_id"],
            10,
            30,
            "ticket",
        )


def test_repository_rename_preserves_stable_authorization(harness):
    app, _, provider, _, _ = harness
    provider.repository["full_name"] = "acme/renamed"
    send(harness)
    drain(app)
    assert run_record(app).status == "published"
    assert ("GET", "/repos/acme/renamed/pulls/1") in provider.requests


def test_comment_scan_cap_leaves_failure_instead_of_duplicate(harness):
    app, _, provider, _, _ = harness
    provider.comments = [
        {"id": i + 1, "body": "human", "user": {"id": i + 1, "type": "User"}} for i in range(100)
    ]
    send(harness)
    drain(app)
    assert run_record(app).error == "github_comment_scan_limit"
    assert not any(
        method == "POST" and path.endswith("comments") for method, path, _ in provider.writes
    )


def test_trusted_policy_is_snapshotted_before_worker_and_candidate_cannot_replace_it(
    harness, monkeypatch
):
    app, _, provider, project, _ = harness
    with app.state.db.session(write=True) as session:
        org = session.get(Organization, project["organization_id"])
        org.plan = "team"
        org.policy = {"version": 1, "thresholds": {"minimum_security_score": 90}}
        org.policy_version = 7

    def worker(_payload, _settings, policy):
        assert policy == {
            "source": "organization",
            "version": 7,
            "rules": {"version": 1, "thresholds": {"minimum_security_score": 90}},
        }
        with app.state.db.session(write=True) as session:
            org = session.get(Organization, project["organization_id"])
            org.policy = {"version": 1, "thresholds": {"minimum_security_score": 1}}
            org.policy_version = 8
        return {"error": "worker_failed"}

    monkeypatch.setattr("blastradius.server.github_service.execute", worker)
    send(harness)
    drain(app)
    with app.state.db.session() as session:
        job = session.get(Analysis, run_record(app).analysis_id)
        assert job.policy_snapshot["version"] == 7
        assert job.policy_snapshot["rules"]["thresholds"]["minimum_security_score"] == 90
    assert provider.checks[0]["conclusion"] == "failure"


def test_key_symlinks_and_nonregular_files_are_unavailable(settings):
    link = settings.github_private_key_file.with_name("key-link.pem")
    link.symlink_to(settings.github_private_key_file)
    for path in (link, settings.github_private_key_file.parent):
        with GitHubAPI(replace(settings, github_private_key_file=path)) as api:
            with pytest.raises(GitHubError, match="github_key_unavailable"):
                api.app_token()


def test_identifiers_and_schema_do_not_leak_provider_secrets_on_failure(harness, caplog):
    app, client, provider, project, _ = harness
    provider.denied_prefix = "/app/installations/"
    send(harness)
    drain(app)
    output = client.get(f"/api/projects/{project['id']}/github").text
    with app.state.db.session() as session:
        delivery = session.get(GitHubDelivery, "delivery-1")
        assert delivery.error == "github_access_denied"
        assert delivery.status == "rejected"
    assert TOKEN not in output + caplog.text


def test_delivery_id_conflict_takes_precedence_over_body_deduplication(harness):
    first = {"action": "ignored-one"}
    second = {"action": "ignored-two"}
    assert send(harness, first, name="ping", delivery="one").status_code == 202
    assert send(harness, second, name="ping", delivery="two").status_code == 202
    assert send(harness, first, name="ping", delivery="two").status_code == 409


@pytest.mark.parametrize("complete", [None, False, "true", "false", 1])
def test_publisher_requires_literal_complete_before_safe_check(harness, complete):
    app, _, _, _, _ = harness
    send(harness)
    drain(app)
    run = run_record(app)
    with app.state.db.session(write=True) as session:
        job = session.get(Analysis, run.analysis_id)
        job.decision = "SAFE TO MERGE"
        session.execute(
            update(Analysis)
            .where(Analysis.id == job.id)
            .values(result={**job.result, "analysis_complete": complete})
        )
    title, conclusion, _, _ = summary(app.state.db, run, app.state.settings)
    assert (title, conclusion) == ("REVIEW REQUIRED", "failure")


def test_expired_run_with_deleted_analysis_cannot_publish(harness):
    app, _, provider, _, _ = harness
    send(harness)
    drain(app)
    run = run_record(app)
    with app.state.db.session(write=True) as session:
        session.delete(session.get(Analysis, run.analysis_id))
        session.get(GitHubRun, run.id).created_at = time.time() - 8 * 86400
    provider.writes.clear()
    with app.state.github.api_factory() as api:
        with pytest.raises(GitHubError, match="github_analysis_expired"):
            publish(api, app.state.db, run.id, app.state.settings)
    assert not provider.writes


def test_slow_response_deadline_is_checked_without_waiting_for_full_chunk(settings, monkeypatch):
    clock = [0]

    class SlowResponse(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(100):
                clock[0] += 10
                yield b" "

    monkeypatch.setattr("blastradius.server.github_api.time.monotonic", lambda: clock[0])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowResponse()))
    with GitHubAPI(settings, transport) as api:
        with pytest.raises(GitHubError, match="github_response_limit"):
            api.request("GET", "/resource", TOKEN)
    assert clock[0] == 90
