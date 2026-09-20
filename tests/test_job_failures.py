from __future__ import annotations

import copy
import threading
from contextlib import contextmanager

import pytest
import test_server
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from blastradius.server.models import Analysis, AnalysisArtifact, AttackPath, Finding, Usage
from blastradius.server.quotas import period
from test_server import login, project, submit, terminal

app = test_server.app
client = test_server.client
demo_results = test_server.demo_results
settings = test_server.settings


@pytest.mark.parametrize(
    "fault",
    [
        "false",
        "missing",
        "string",
        "markdown",
        "sarif",
        "empty",
        "list",
        "null",
        "passed",
        "score",
        "snapshot",
        "verdict",
        "finding",
    ],
)
def test_invalid_worker_result_never_persists_safe(client, app, demo_results, monkeypatch, fault):
    result = copy.deepcopy(demo_results[("public_ssh", "safe")])
    if fault == "false":
        result["analysis_complete"] = False
    elif fault == "missing":
        del result["analysis_complete"]
    elif fault == "string":
        result["analysis_complete"] = "true"
    elif fault == "markdown":
        result["reports"]["markdown"] = "Decision: BLOCK CHANGE"
    elif fault == "sarif":
        result["reports"]["sarif"]["runs"][0]["properties"]["decision"] = "REVIEW REQUIRED"
    elif fault == "passed":
        result["passed"] = False
    elif fault == "score":
        result["score"]["after"] -= 1
    elif fault == "snapshot":
        result["after"]["complete"] = False
    elif fault == "verdict":
        del result["verdict"]
    elif fault == "finding":
        result["findings"] = [{}]
    response = {"result": result}
    if fault == "empty":
        response = {"result": {}}
    elif fault == "list":
        response = []
    elif fault == "null":
        response = None
    monkeypatch.setattr("blastradius.server.jobs.execute", lambda *_: response)
    me = login(client)
    proj = project(client, me)
    job = terminal(client, submit(client, proj["id"]).json()["id"])
    assert job["status"] == "failed"
    assert job["result"] is None and job["decision"] is None
    for format in ("json", "markdown", "sarif", "web"):
        assert client.get(f"/api/analyses/{job['id']}/report?format={format}").status_code == 409
    assert client.get(f"/api/analyses/{job['id']}/artifacts").json() == {
        "artifacts": [],
        "normalized_version": None,
    }
    with app.state.db.session() as session:
        for model in (AnalysisArtifact, AttackPath, Finding):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        stored = session.get(Analysis, job["id"])
        assert stored.normalized_version is None


def test_dispatch_failure_is_terminal_and_accounted(app, monkeypatch):
    def unavailable(*_):
        raise RuntimeError("executor unavailable")

    with TestClient(app, raise_server_exceptions=False) as client:
        me = login(client)
        proj = project(client, me)
        monkeypatch.setattr(app.state.jobs.executor, "submit", unavailable)
        assert submit(client, proj["id"]).status_code == 500
        with app.state.db.session() as session:
            job = session.scalar(select(Analysis))
            assert job.status == "failed" and job.error == "dispatch_failed"
            assert job.completed_at and job.result is None
            assert session.get(Usage, (proj["organization_id"], period())).analyses == 1
        reservations = [app.state.jobs.reserve() for _ in range(app.state.settings.max_jobs)]
        assert all(reservations)
        assert not app.state.jobs.reserve()
        for _ in reservations:
            app.state.jobs.slots.release()


def test_terminal_persistence_retries_without_restart(client, app, monkeypatch):
    me = login(client)
    proj = project(client, me)
    original = app.state.db.session
    failures = 0

    @contextmanager
    def interrupted(write=False):
        nonlocal failures
        if write and threading.current_thread().name.startswith("analysis") and failures < 2:
            failures += 1
            raise OperationalError("test outage", {}, Exception("disposable fault"))
        with original(write=write) as session:
            yield session

    def execute(*_):
        monkeypatch.setattr(app.state.db, "session", interrupted)
        return {"error": "invalid_analysis_input"}

    monkeypatch.setattr("blastradius.server.jobs.execute", execute)
    job = terminal(client, submit(client, proj["id"]).json()["id"])
    assert failures == 2
    assert job["status"] == "failed" and job["completed_at"]
    assert job["result"] is None and job["decision"] is None


@pytest.mark.parametrize("outage", [2, 3])
def test_result_commit_rollback_and_exhaustion_fail_closed(
    client, app, demo_results, monkeypatch, caplog, outage
):
    me = login(client)
    proj = project(client, me)
    original = app.state.db.session
    failures = 0

    @contextmanager
    def interrupted(write=False):
        nonlocal failures
        with original(write=write) as session:
            yield session
            if (
                write
                and threading.current_thread().name.startswith("analysis")
                and failures < outage
            ):
                failures += 1
                session.flush()
                raise OperationalError("test outage", {}, Exception("disposable commit fault"))

    def execute(*_):
        monkeypatch.setattr(app.state.db, "session", interrupted)
        return {"result": demo_results[("public_ssh", "safe")]}

    monkeypatch.setattr("blastradius.server.jobs.execute", execute)
    job_id = submit(client, proj["id"]).json()["id"]
    app.state.jobs.shutdown()
    assert failures == outage
    assert client.get("/health/ready").status_code == (503 if outage == 3 else 200)
    with original() as session:
        job = session.get(Analysis, job_id)
        assert job.status == ("running" if outage == 3 else "failed")
        assert job.result is None and job.decision is None and job.normalized_version is None
        for model in (AnalysisArtifact, AttackPath, Finding):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    for format in ("json", "markdown", "sarif"):
        assert client.get(f"/api/analyses/{job_id}/report?format={format}").status_code == 409
    if outage == 3:
        assert "analysis.persistence_failed" in caplog.text
        assert not app.state.jobs.reserve()
        monkeypatch.setattr(app.state.db, "session", original)
        app.state.jobs.recover()
        assert client.get(f"/api/analyses/{job_id}").json()["error"] == "server_restarted"


def test_persistence_outage_hides_stale_progress_without_exposing_other_tenants(
    client, app, monkeypatch
):
    me = login(client)
    proj = project(client, me)
    completed = terminal(client, submit(client, proj["id"]).json()["id"])
    original = app.state.db.session

    @contextmanager
    def unavailable(write=False):
        if write and threading.current_thread().name.startswith("analysis"):
            raise OperationalError("test outage", {}, Exception("disposable fault"))
        with original(write=write) as session:
            yield session

    def execute(*_):
        monkeypatch.setattr(app.state.db, "session", unavailable)
        return {"error": "worker_failed"}

    monkeypatch.setattr("blastradius.server.jobs.execute", execute)
    job_id = submit(client, proj["id"]).json()["id"]
    app.state.jobs.shutdown()
    assert app.state.jobs.persistence_failed.is_set()
    for url in (
        f"/api/analyses/{job_id}",
        f"/api/projects/{proj['id']}/analyses",
    ):
        response = client.get(url)
        assert response.status_code == 503
        assert response.json() == {"detail": "analysis_persistence_failed"}
    assert submit(client, proj["id"]).status_code == 503
    assert client.get(f"/api/analyses/{completed['id']}").json() == completed
    assert client.get(f"/api/analyses/{completed['id']}/report").status_code == 200
    assert client.get(f"/api/projects/{proj['id']}/analyses?status=succeeded").status_code == 200
    with original() as session:
        job = session.get(Analysis, job_id)
        assert job.status == "running" and job.result is None and job.decision is None
        assert session.get(Usage, (proj["organization_id"], period())).analyses == 2
    login(client)
    for url in (
        f"/api/analyses/{job_id}",
        f"/api/projects/{proj['id']}/analyses",
        f"/api/analyses/{completed['id']}/report",
    ):
        assert client.get(url).status_code == 404
    assert submit(client, proj["id"]).status_code == 404
    monkeypatch.setattr(app.state.db, "session", original)
    app.state.jobs.recover()
    with original() as session:
        job = session.get(Analysis, job_id)
        assert job.status == "failed" and job.error == "server_restarted"
