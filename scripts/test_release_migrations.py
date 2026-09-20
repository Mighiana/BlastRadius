from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("alembic", reason="install .[server,dev] for migration tests")
pytest.importorskip("sqlalchemy", reason="install .[server,dev] for migration tests")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from blastradius.server.config import Settings
from blastradius.server.db import Database

ROOT = Path(__file__).resolve().parents[1]


def test_preview_environment_file_controls_migration_without_changing_local_settings(
    tmp_path: Path,
) -> None:
    environment_file = tmp_path / "preview config.env"
    database = tmp_path / "preview" / "server.db"
    local_file = ROOT / ".env"
    original = local_file.read_bytes() if local_file.exists() else None
    environment_file.write_text(
        "\n".join(
            [
                "BR_ENV=preview",
                "BR_PUBLIC_URL=https://8000--fixture.preview.devinapps.com",
                "BR_AUTH_MODE=demo",
                "BR_AUTO_MIGRATE=false",
                f"BR_DATA_DIR='{database.parent}'",
                f"BR_DATABASE_URL='sqlite:///{database}'",
                f"BLASTRADIUS_ALEMBIC_CONFIG='{ROOT / 'alembic.ini'}'",
            ]
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["make", "migrate", f"ENV_FILE={environment_file}", f"VENV={sys.prefix}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    db = Database(Settings(database_url=f"sqlite:///{database}", data_dir=database.parent))
    try:
        assert db.ready()
    finally:
        db.engine.dispose()
    assert (local_file.read_bytes() if local_file.exists() else None) == original


@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "upgrade-from-0001"])
def test_migrate_uses_current_head_and_preserves_existing_data(
    tmp_path: Path, existing: bool
) -> None:
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    env = {
        **os.environ,
        "BR_ENV": "test",
        "BR_AUTH_MODE": "disabled",
        "BR_AUTO_MIGRATE": "false",
        "BR_DATABASE_URL": url,
        "BR_DATA_DIR": str(tmp_path),
        "BLASTRADIUS_ALEMBIC_CONFIG": str(ROOT / "alembic.ini"),
        "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
    }
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    engine = create_engine(url)
    if existing:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
            connection.exec_driver_sql("CREATE TABLE release_restore_probe (value TEXT NOT NULL)")
            connection.exec_driver_sql("INSERT INTO release_restore_probe VALUES ('preserve-me')")
    for _ in range(2):
        result = subprocess.run(
            ["sh", str(ROOT / "scripts/container-entrypoint.sh"), "migrate"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        assert set(MigrationContext.configure(connection).get_current_heads()) == set(
            script.get_heads()
        )
        if existing:
            assert (
                connection.exec_driver_sql("SELECT value FROM release_restore_probe").scalar()
                == "preserve-me"
            )
    db = Database(
        Settings(environment="test", database_url=url, data_dir=tmp_path, auto_migrate=False)
    )
    try:
        assert db.ready(), "Readiness must follow the packaged migration head."
    finally:
        db.engine.dispose()
        engine.dispose()
