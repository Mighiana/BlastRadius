from __future__ import annotations

import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import test_server
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from blastradius.server.app import create_app
from blastradius.server.db import Database, LeaseLost
from blastradius.server.lease import ServiceLease
from blastradius.server.jobs import execute
from blastradius.server.models import Analysis, Organization
from blastradius.server.schemas import AnalysisInput
from test_server import login, project, submit

backend_client = test_server.backend_client
demo_results = test_server.demo_results
migration_database = test_server.migration_database
settings = test_server.settings


def test_worker_is_killed_and_reaped_when_lease_is_lost(settings, monkeypatch):
    processes = []
    popen = subprocess.Popen

    def capture(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("blastradius.server.jobs.subprocess.Popen", capture)
    payload = AnalysisInput(project_id="test", before_files={"a.tf": ""}, after_files={"a.tf": ""})
    response = execute(payload, settings, lease_healthy=lambda: not processes)
    assert response == {"error": "service_lease_lost"}
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not list((settings.data_dir / "jobs").iterdir())


@pytest.mark.parametrize("migration_database", ["postgres"], indirect=True)
def test_postgres_lost_lease_fences_old_owner_and_worker(backend_client, monkeypatch):
    client, app = backend_client
    db = app.state.db
    if db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL backend termination requires PostgreSQL")
    me = login(client)
    proj = project(client, me)
    started, proceed = threading.Event(), threading.Event()

    def delayed(*_):
        started.set()
        assert proceed.wait(10)
        return {"error": "obsolete_worker"}

    monkeypatch.setattr("blastradius.server.jobs.execute", delayed)
    analysis_id = submit(client, proj["id"]).json()["id"]
    try:
        assert started.wait(5)
        assert client.get("/health/ready").status_code == 200
        with db.engine.begin() as connection:
            assert connection.execute(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": app.state.lease.pid}
            ).scalar()
        assert client.get("/health/ready").status_code == 503
        assert client.get("/api/me").status_code == 503
        assert client.post("/api/organizations", json={"name": "obsolete"}).status_code == 503
        assert not app.state.jobs.reserve()
        with TestClient(create_app(app.state.settings)) as replacement:
            assert replacement.get("/health/ready").status_code == 200
            replacement.cookies.update(client.cookies)
            assert replacement.get("/api/me").json()["user"]["id"] == me["user"]["id"]
            proceed.set()
            app.state.jobs.shutdown()
            with replacement.app.state.db.session() as session:
                job = session.get(Analysis, analysis_id)
                assert job.status == "failed" and job.error == "server_restarted"
                assert job.result is None and job.decision is None
            with pytest.raises(LeaseLost):
                with db.session(write=True) as session:
                    session.get(Organization, proj["organization_id"]).name = "obsolete"
            assert client.get("/health/ready").status_code == 503
    finally:
        proceed.set()


@pytest.mark.parametrize("migration_database", ["postgres"], indirect=True)
def test_postgres_successor_waits_for_old_transaction_rollback(migration_database, settings):
    db = migration_database
    if db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL transaction fencing requires PostgreSQL")
    db.migrate()
    lease = ServiceLease(db, settings.data_dir)
    lease.acquire()
    entered, proceed, acquired = threading.Event(), threading.Event(), threading.Event()
    successor_db = Database(
        replace(settings, database_url=db.engine.url.render_as_string(hide_password=False))
    )
    successor = ServiceLease(successor_db, settings.data_dir)

    def obsolete():
        with pytest.raises(LeaseLost):
            with db.session(write=True) as session:
                session.add(Organization(name="uncommitted old owner"))
                session.flush()
                entered.set()
                assert proceed.wait(10)

    def acquire():
        successor.acquire()
        acquired.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(obsolete)
            assert entered.wait(5)
            with db.engine.begin() as connection:
                connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": lease.pid})
            new = pool.submit(acquire)
            assert not acquired.wait(0.2)
            proceed.set()
            old.result(timeout=5)
            new.result(timeout=5)
        assert acquired.is_set()
        with successor_db.session() as session:
            assert not session.scalars(
                select(Organization).where(Organization.name == "uncommitted old owner")
            ).all()
    finally:
        proceed.set()
        successor.release()
        lease.release()
        successor_db.engine.dispose()
