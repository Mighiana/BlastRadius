from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ops_restore_drill import (
    TARGET,
    DisposablePostgres,
    DrillError,
    command,
    main,
    restore_guard,
    run,
)


@pytest.mark.parametrize(
    ("database", "label", "expected", "tables", "error"),
    [
        ("production", "nonce", "nonce", 0, "non_drill"),
        (TARGET, "other", "nonce", 0, "unowned"),
        (TARGET, "", "", 0, "unowned"),
        (TARGET, "nonce", "nonce", 1, "nonempty"),
    ],
)
def test_restore_refuses_unsafe_targets(
    database: str, label: str, expected: str, tables: int, error: str,
) -> None:
    with pytest.raises(DrillError, match=error):
        restore_guard(database, label, expected, tables)


def test_restore_refuses_other_database_before_any_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("A non-drill database must never be contacted")

    monkeypatch.setattr(DisposablePostgres, "connect", unexpected)
    with pytest.raises(DrillError, match="non_drill_restore"):
        DisposablePostgres().restore(b"untrusted", "production")


def test_existing_output_directory_is_not_touched(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run(tmp_path)
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_subprocess_failure_does_not_expose_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(["redacted"], 1, b"secret", b"secret")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(DrillError) as error:
        command(["unused"])
    assert "secret" not in str(error.value)
    assert "withheld" in str(error.value)


def test_cli_error_does_not_expose_exception_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    def failed(_path: Path) -> dict[str, object]:
        raise RuntimeError("private connection detail")

    monkeypatch.setattr("ops_restore_drill.run", failed)
    assert main(["--output-dir", str(tmp_path / "new")]) == 1
    output = capsys.readouterr()
    assert "private connection detail" not in output.err
    assert '"error": "RuntimeError"' in output.err


def test_no_live_database_option_is_accepted(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--output-dir", "unused", "--database-url", "production"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_remote_docker_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    with pytest.raises(DrillError, match="local_unix"):
        DisposablePostgres().start()


def test_context_cannot_override_local_docker_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def remote(args: list[str]) -> bytes:
        calls.append(args)
        return b"ssh://remote"

    monkeypatch.setenv("DOCKER_HOST", "unix:///local")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    monkeypatch.setattr("ops_restore_drill.command", remote)
    with pytest.raises(DrillError, match="local_unix"):
        DisposablePostgres().start()
    assert calls == [["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]]


@pytest.mark.skipif(
    os.environ.get("BR_RUN_OPS_DRILL") != "1",
    reason="Opt in to disposable Docker PostgreSQL with BR_RUN_OPS_DRILL=1.",
)
def test_disposable_postgres_recovery(tmp_path: Path) -> None:
    report = run(tmp_path / "drill")
    assert report["status"] == "passed"
    assert report["schema_and_data_match"] is True
    assert report["source_unchanged"] is True
    assert report["nonempty_restore_refused"] is True
