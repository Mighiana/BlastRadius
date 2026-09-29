"""Deploy/restart handoff: one lease owner, durable webhook intake, no lost events."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import pytest

pytest.importorskip("fastapi", reason="install .[server,dev] for handoff tests")

import test_github_app
import test_server
import blastradius.server.db as db_module
from fastapi.testclient import TestClient
from authlib.jose import JsonWebKey
from sqlalchemy import func, select, text

from blastradius.server.app import create_app
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.github_api import GitHubAPI
from blastradius.server.github_routes import register_installation
from blastradius.server.jobs import execute
from blastradius.server.models import Analysis, GitHubDelivery, GitHubRun
from blastradius.server.schemas import AnalysisInput

Provider = test_github_app.Provider
migration_database = test_server.migration_database
demo_results = test_server.demo_results
SECRET = "test-secret-" * 4
ACTIONS = ("opened", "synchronize", "reopened", "edited")
FORBIDDEN = (SECRET, test_github_app.TOKEN, "Authorization", "Cookie", "resource \"aws_", "brtest")


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
        github_webhook_secret=SECRET,
    )


@pytest.fixture
def db_settings(migration_database, settings):
    return replace(
        settings,
        database_url=migration_database.engine.url.render_as_string(hide_password=False),
        lease_wait_seconds=60,
        shutdown_drain_seconds=1,
    )


@pytest.fixture
def provider(db_settings, demo_results, monkeypatch):
    provider = Provider()
    monkeypatch.setattr("blastradius.server.app.build_demos", lambda _: demo_results)
    monkeypatch.setattr(
        "blastradius.server.github_routes.GitHubAPI",
        lambda _: GitHubAPI(db_settings, transport=httpx.MockTransport(provider)),
    )
    return provider


def instance(settings: Settings, provider: Provider):
    app = create_app(settings)
    app.state.github.api_factory = lambda: GitHubAPI(
        settings, transport=httpx.MockTransport(provider)
    )
    return app


def connect(client: TestClient, app, settings: Settings) -> None:
    csrf = client.get("/api/me").json()["csrf_token"]
    assert client.post("/api/auth/demo", headers={"X-CSRF-Token": csrf}).status_code == 200
    me = client.get("/api/me").json()
    client.headers["X-CSRF-Token"] = me["csrf_token"]
    org_id = me["organizations"][0]["id"]
    project = client.post("/api/projects", json={"name": "Infra", "organization_id": org_id})
    register_installation(app.state.db, settings, org_id, 10, 30, "verified-ticket-1")
    assert client.put(
        f"/api/projects/{project.json()['id']}/github",
        json={"installation_id": 10, "repository_id": 20},
    ).status_code == 200


def send(client, provider, delivery, action="opened", signature=None):
    body = json.dumps(provider.event(action)).encode()
    signature = signature or "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/github/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": delivery,
            "X-GitHub-Event": "pull_request",
            "Content-Type": "application/json",
        },
    )


def settled(app, timeout=30.0):
    """Wait until every delivery reached a terminal state; returns their statuses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with app.state.db.session() as session:
            rows = {d.id: d.status for d in session.scalars(select(GitHubDelivery))}
        if rows and all(s in ("handled", "ignored", "rejected") for s in rows.values()):
            app.state.github.executor.submit(lambda: None).result(timeout=30)
            return rows
        time.sleep(0.1)
    pytest.fail(f"deliveries did not settle: {rows}")


def wait_ready(client, timeout=15.0) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if client.get("/health/ready").status_code == 200:
            return time.monotonic() - started
        time.sleep(0.05)
    pytest.fail("successor did not become ready")


def observer(settings: Settings) -> Database:
    """Unfenced read-only view of the shared database, independent of any instance."""
    return Database(settings)


def counts(settings: Settings):
    with observer(settings).session() as session:
        return (
            session.scalar(select(func.count()).select_from(Analysis)),
            session.scalar(select(func.count()).select_from(GitHubRun)),
        )


def assert_private(caplog):
    text_ = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in FORBIDDEN:
        assert forbidden not in text_


@pytest.mark.parametrize("migration_database", ["sqlite", "postgres"], indirect=True)
def test_rolling_deploy_persists_every_event_and_processes_each_once(
    db_settings, provider, caplog
):
    """A, D, E, F, G: handoff with no active jobs while events keep arriving."""
    logger = logging.getLogger("blastradius")
    logger.addHandler(caplog.handler)
    caplog.handler.setLevel(logging.INFO)
    try:
        rolling_deploy(db_settings, provider)
    finally:
        logger.removeHandler(caplog.handler)
    events = [json.loads(r.getMessage()).get("event") for r in caplog.records if r.getMessage().startswith("{")]
    for name in (
        "service.shutdown_started",
        "service.lease_release_started",
        "service.lease_released",
        "service.lease_acquire_wait",
        "service.lease_acquired",
        "github.webhook_received",
        "github.webhook_persisted",
        "github.webhook_duplicate",
        "github.webhook_deferred",
        "github.webhook_processed",
    ):
        assert name in events, name
    assert_private(caplog)


def rolling_deploy(db_settings, provider):
    old = instance(db_settings, provider)
    new = instance(db_settings, provider)
    responses = []
    with TestClient(old) as old_client:
        connect(old_client, old, db_settings)
        new_client = TestClient(new)
        new_client.__enter__()
        try:
            assert new_client.get("/health/live").status_code == 200
            assert new_client.get("/health/ready").status_code == 503
            # D/F: events delivered to the waiting successor are persisted, not refused.
            for i, action in enumerate(ACTIONS[:2]):
                responses.append(send(new_client, provider, f"during-{i}", action))
            # E: exact redelivery and same body under another delivery ID.
            responses.append(send(new_client, provider, "during-0", "opened"))
            responses.append(send(new_client, provider, "replayed-body", "opened"))
            # G: forged signature still rejected, nothing stored.
            forged = send(new_client, provider, "forged", "opened", signature="sha256=" + "0" * 64)
            assert forged.status_code == 401
            responses.append(send(old_client, provider, "old-owner", ACTIONS[2]))
            old_client.__exit__(None, None, None)
            responses.append(send(new_client, provider, "after-release", ACTIONS[3]))
            handoff = wait_ready(new_client)
            assert handoff < 5, handoff
            statuses = settled(new)
        finally:
            new_client.__exit__(None, None, None)
    assert all(r.status_code == 202 for r in responses), [r.status_code for r in responses]
    assert [r.json()["status"] for r in responses].count("duplicate") == 2
    assert set(statuses) == {"during-0", "during-1", "old-owner", "after-release"}
    assert set(statuses.values()) == {"handled"}
    with observer(db_settings).session() as session:
        assert session.get(GitHubDelivery, "forged") is None
        assert all(d.payload is None for d in session.scalars(select(GitHubDelivery)))
    assert counts(db_settings) == (1, 1)
    assert len(provider.checks) == len(provider.comments) == 1


@pytest.mark.parametrize("migration_database", ["sqlite", "postgres"], indirect=True)
def test_graceful_shutdown_hands_off_running_and_queued_deliveries(
    db_settings, provider, monkeypatch
):
    """B, C: a running analysis is stopped, queued deliveries stay durable."""
    started = threading.Event()

    calls = 0

    def blocked(_inputs, settings, policy, lease_healthy, stopping):
        nonlocal calls
        calls += 1
        started.set()
        if calls == 1:
            while not stopping.is_set() and lease_healthy():
                time.sleep(0.02)
            return {"error": "server_restarted"}
        return execute(_inputs, settings, policy, lease_healthy, stopping)

    monkeypatch.setattr("blastradius.server.github_service.execute", blocked)
    old = instance(db_settings, provider)
    new = instance(db_settings, provider)
    with TestClient(old) as old_client:
        connect(old_client, old, db_settings)
        assert send(old_client, provider, "running").json() == {"status": "queued"}
        assert started.wait(10)
        assert send(old_client, provider, "queued", "synchronize").json() == {"status": "queued"}
        new_client = TestClient(new)
        new_client.__enter__()
    try:
        assert wait_ready(new_client) < 5
        assert set(settled(new).values()) == {"handled"}
        with new.state.db.session() as session:
            analyses = list(session.scalars(select(Analysis)))
            assert {job.status for job in analyses} == {"failed", "succeeded"}
            assert "server_restarted" in {job.error for job in analyses}
    finally:
        new_client.__exit__(None, None, None)
    assert counts(db_settings) == (2, 1)
    assert len(provider.checks) == 1 and provider.checks[-1]["conclusion"] != "success"


@pytest.mark.parametrize("migration_database", ["postgres"], indirect=True)
def test_crash_after_persist_and_after_analysis_creation_recover_once(
    db_settings, provider, monkeypatch
):
    """H, I: the old owner dies without releasing; the successor recovers exactly once."""
    started = threading.Event()

    calls = 0

    def blocked(_inputs, settings, policy, lease_healthy, stopping):
        nonlocal calls
        calls += 1
        started.set()
        if calls == 1:
            while not stopping.is_set() and lease_healthy():
                time.sleep(0.02)
            return {"error": "service_lease_lost"}
        return execute(_inputs, settings, policy, lease_healthy, stopping)

    monkeypatch.setattr("blastradius.server.github_service.execute", blocked)
    old = instance(db_settings, provider)
    new = instance(db_settings, provider)
    with TestClient(old) as old_client:
        connect(old_client, old, db_settings)
        # I: analysis row created and running.
        assert send(old_client, provider, "crash-running").json() == {"status": "queued"}
        assert started.wait(10)
        # H: persisted but never dispatched.
        monkeypatch.setattr(old.state.github, "dispatch", lambda _id: {"status": "deferred"})
        assert send(old_client, provider, "crash-pending", "synchronize").status_code == 202
        with old.state.db.engine.begin() as connection:
            assert connection.execute(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": old.state.lease.pid}
            ).scalar()
        new_client = TestClient(new)
        new_client.__enter__()
        try:
            assert wait_ready(new_client) < 5
            assert old_client.get("/health/ready").status_code == 503
            assert not old.state.jobs.reserve()
        except BaseException:
            new_client.__exit__(None, None, None)
            raise
    try:
        # The stale owner's shutdown released nothing it no longer held.
        assert new.state.lease.healthy()
        assert new_client.get("/health/ready").status_code == 200
        statuses = settled(new)
    finally:
        new_client.__exit__(None, None, None)
    assert set(statuses.values()) == {"handled"}
    with observer(db_settings).session() as session:
        jobs = list(session.scalars(select(Analysis)))
        assert {job.status for job in jobs} == {"failed", "succeeded"}
        assert "server_restarted" in {job.error for job in jobs}
    assert counts(db_settings) == (2, 1)
    assert len(provider.checks) == len(provider.comments) == 1


@pytest.mark.parametrize("migration_database", ["postgres"], indirect=True)
def test_concurrent_duplicate_intake_on_postgres_stores_one_row(db_settings, provider):
    old = instance(db_settings, provider)
    waiting = instance(db_settings, provider)
    with TestClient(old) as old_client:
        connect(old_client, old, db_settings)
        old.state.jobs.draining.set()  # owner alive but not dispatching: pure intake race
        with TestClient(waiting) as client:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(
                    pool.map(lambda i: send(client, provider, f"dup-{i % 2}").json()["status"], range(16))
                )
    assert results.count("deferred") == 1 and results.count("duplicate") == 15
    with observer(db_settings).session() as session:
        assert session.scalar(select(func.count()).select_from(GitHubDelivery)) == 1


@pytest.mark.parametrize("migration_database", ["postgres"], indirect=True)
def test_dispatch_lock_timeout_returns_database_deferred(
    db_settings, provider, monkeypatch, caplog
):
    app = instance(db_settings, provider)
    logger = logging.getLogger("blastradius.server.github_service")
    logger.addHandler(caplog.handler)
    with TestClient(app) as client:
        try:
            connect(client, app, db_settings)
            app.state.github.dispatch_pending = lambda: 0
            raw = json.dumps(provider.event()).encode()
            payload = test_github_app.PullEvent.model_validate(provider.event())
            with app.state.db.intake() as session:
                session.add(
                    GitHubDelivery(
                        id="locked-delivery",
                        body_hash=hashlib.sha256(b"pull_request\0" + raw).hexdigest(),
                        event="pull_request",
                        status="pending",
                        payload=payload.model_dump_json(),
                    )
                )
            with app.state.db.engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(
                        text(
                            "SELECT id FROM github_deliveries "
                            "WHERE id = 'locked-delivery' FOR UPDATE"
                        )
                    )
                    monkeypatch.setattr(db_module, "LOCK_TIMEOUT", "500ms")
                    started = time.monotonic()
                    result = app.state.github.dispatch("locked-delivery")
                    elapsed = time.monotonic() - started
                finally:
                    transaction.rollback()
        finally:
            logger.removeHandler(caplog.handler)
    assert result == {"status": "deferred"}
    assert elapsed < 2
    events = [json.loads(record.getMessage()) for record in caplog.records]
    assert {
        "event": "github.webhook_deferred",
        "delivery_id": "locked-delivery",
        "reason": "database_unavailable",
    } in events


def test_stopping_kills_and_reaps_a_running_worker(tmp_path, monkeypatch):
    processes = []
    popen = subprocess.Popen

    def capture(*args, **kwargs):
        processes.append(popen(*args, **kwargs))
        return processes[-1]

    monkeypatch.setattr("blastradius.server.jobs.subprocess.Popen", capture)
    settings = Settings(environment="test", data_dir=tmp_path, database_url="sqlite://")
    stopping = threading.Event()

    def healthy():
        stopping.set()
        return True

    payload = AnalysisInput(project_id="t", before_files={"a.tf": ""}, after_files={"a.tf": ""})
    assert execute(payload, settings, lease_healthy=healthy, stopping=stopping) == {
        "error": "server_restarted"
    }
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not list((tmp_path / "jobs").iterdir())
