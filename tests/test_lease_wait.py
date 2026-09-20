from __future__ import annotations

import fcntl
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blastradius.server.app import create_app
from blastradius.server.config import Settings
from blastradius.server.db import Database


def _prepared_settings(tmp_path: Path, lease_wait_seconds: int) -> Settings:
    settings = Settings(
        environment="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        public_url="http://testserver",
        auth_mode="demo",
        rate_limit=1000,
        lease_wait_seconds=lease_wait_seconds,
    )
    db = Database(settings)
    db.migrate()
    db.engine.dispose()
    return settings


def _held_lock(settings: Settings):
    database = settings.database_url.removeprefix("sqlite:///")
    handle = open(f"{database}.lock", "a+")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def test_lease_wait_serves_liveness_until_old_owner_releases(tmp_path):
    settings = _prepared_settings(tmp_path, 10)
    handle = _held_lock(settings)
    try:
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/live").status_code == 200
            assert client.get("/health/ready").status_code == 503
            assert client.get("/api/me").status_code == 503

            fcntl.flock(handle, fcntl.LOCK_UN)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if client.get("/health/ready").status_code == 200:
                    break
                time.sleep(0.1)
            else:
                pytest.fail("service did not become ready after the lease was released")
            assert client.get("/api/me").status_code == 200
    finally:
        handle.close()


def test_lease_wait_calls_fatal_after_timeout(tmp_path):
    settings = _prepared_settings(tmp_path, 1)
    handle = _held_lock(settings)
    reasons: list[str] = []
    try:
        with TestClient(create_app(settings, fatal=reasons.append)) as client:
            assert client.get("/health/live").status_code == 200
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not reasons:
                time.sleep(0.1)
            assert reasons == ["lease_wait_timeout"]
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def test_lease_wait_zero_preserves_startup_failure(tmp_path):
    settings = _prepared_settings(tmp_path, 0)
    handle = _held_lock(settings)
    try:
        with pytest.raises(RuntimeError, match="Only one server process"):
            with TestClient(create_app(settings)):
                pass
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
