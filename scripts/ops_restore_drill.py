"""Exercise logical recovery using only a newly created, disposable PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import URL

from blastradius.server.app import create_app
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.models import (
    Analysis,
    AnalysisArtifact,
    AnalysisFeedback,
    BetaInterest,
    Membership,
    Organization,
    Project,
    ProductEvent,
    Usage,
    User,
)

IMAGE = (
    "postgres:16.15-trixie@sha256:"
    "a3b7f434b2dc57ce85a67e171163eb8ab1a1ebcb39d27484661f26b1dfbe30d6"
)
LABEL = "io.blastradius.disposable-ops-drill"
SOURCE = "br_drill_source"
TARGET = "br_drill_restore"
MIGRATOR = "br_migrator"
RUNTIME = "br_runtime"


class DrillError(RuntimeError):
    """A bounded, nonsecret diagnostic safe to display."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DrillError(code)


def command(
    args: list[str], *, data: bytes | None = None, env: dict[str, str] | None = None
) -> bytes:
    try:
        result = subprocess.run(
            args, input=data, capture_output=True, env=env, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DrillError("subprocess_unavailable_or_timed_out") from None
    require(result.returncode == 0, "subprocess_failed_output_withheld")
    return result.stdout


def restore_guard(database: str, label: str, expected_label: str, tables: int) -> None:
    require(database == TARGET, "refusing_non_drill_restore_database")
    require(bool(expected_label) and label == expected_label, "refusing_unowned_container")
    require(tables == 0, "refusing_nonempty_restore_database")


class DisposablePostgres:
    def __init__(self) -> None:
        self.nonce = uuid.uuid4().hex
        self.name = "br-ops-drill-" + self.nonce
        self.password = secrets.token_urlsafe(32)
        self.port = 0

    def owned(self) -> bool:
        label = command([
            "docker", "inspect", "--format",
            '{{index .Config.Labels "' + LABEL + '"}}', self.name,
        ]).decode().strip()
        return label == self.nonce

    def start(self) -> None:
        host = (os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else "") or command([
            "docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}",
        ]).decode().strip()
        require(host.startswith("unix://"), "local_unix_docker_daemon_required")
        command([
            "docker", "run", "--detach", "--rm", "--pull=never",
            "--name", self.name, "--label", f"{LABEL}={self.nonce}",
            "--user", "postgres", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--memory=1g", "--cpus=1",
            "--pids-limit=128", "--log-driver=none",
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m,uid=999,gid=999",
            "--tmpfs", "/var/run/postgresql:rw,noexec,nosuid,size=16m,uid=999,gid=999",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--publish", "127.0.0.1::5432", "--env", "POSTGRES_PASSWORD", IMAGE,
        ], env={**os.environ, "POSTGRES_PASSWORD": self.password})
        mapping = command(["docker", "port", self.name, "5432/tcp"]).decode().strip()
        require(mapping.startswith("127.0.0.1:") and "\n" not in mapping, "invalid_port_binding")
        self.port = int(mapping.rsplit(":", 1)[1])
        deadline = time.monotonic() + 60
        while True:
            try:
                with self.connect("postgres", "postgres"):
                    return
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise DrillError("postgres_startup_timeout") from None
                time.sleep(0.2)

    def connect(self, database: str, role: str) -> psycopg.Connection[tuple[object, ...]]:
        require(database in {SOURCE, TARGET, "postgres"}, "refusing_non_drill_database")
        require(self.port > 0, "postgres_not_started")
        return psycopg.connect(
            host="127.0.0.1", port=self.port, dbname=database, user=role,
            password=self.password, connect_timeout=3, autocommit=True,
        )

    def settings(self, database: str, directory: Path, role: str = MIGRATOR) -> Settings:
        require(database in {SOURCE, TARGET}, "refusing_non_drill_database")
        url = URL.create(
            "postgresql+psycopg", username=role, password=self.password,
            host="127.0.0.1", port=self.port, database=database,
        )
        return Settings(
            environment="test", database_url=url.render_as_string(hide_password=False),
            data_dir=directory, public_url="http://testserver", auth_mode="disabled",
            auto_migrate=False,
        )

    def initialize(self) -> None:
        require(self.owned(), "refusing_unowned_container")
        with self.connect("postgres", "postgres") as conn:
            for role in (MIGRATOR, RUNTIME):
                conn.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(self.password)))
            for database in (SOURCE, TARGET):
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(MIGRATOR),
                ))

    def pg(self, tool: str, database: str, *options: str, data: bytes | None = None) -> bytes:
        require(self.owned(), "refusing_unowned_container")
        require(database in {SOURCE, TARGET}, "refusing_non_drill_database")
        require(tool in {"pg_dump", "pg_restore"}, "unsupported_postgres_tool")
        return command([
            "docker", "exec", "-i", self.name, tool, "--username", MIGRATOR,
            "--dbname", database, "--no-owner", "--no-privileges", *options,
        ], data=data)

    def restore(self, archive: bytes, database: str = TARGET) -> None:
        require(database == TARGET, "refusing_non_drill_restore_database")
        require(self.owned(), "refusing_unowned_container")
        with self.connect(database, MIGRATOR) as conn:
            tables = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            ).fetchone()
        if tables is None:
            raise DrillError("missing_table_count")
        restore_guard(database, self.nonce, self.nonce, int(str(tables[0])))
        self.pg("pg_restore", database, "--exit-on-error", "--single-transaction", data=archive)

    def stop(self) -> None:
        exists = command([
            "docker", "ps", "-aq", "--filter", f"name=^/{self.name}$",
        ]).strip()
        if exists:
            require(self.owned(), "refusing_to_remove_unowned_container")
            command(["docker", "rm", "--force", self.name])


@dataclass(frozen=True)
class Snapshot:
    counts: dict[str, int]
    data_sha256: str
    schema_sha256: str


def digest(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def snapshot(pg: DisposablePostgres, database: str) -> Snapshot:
    counts: dict[str, int] = {}
    rows: dict[str, list[str]] = {}
    with pg.connect(database, MIGRATOR) as conn:
        for (name,) in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ):
            require(isinstance(name, str), "invalid_table_name")
            table = str(name)
            values = conn.execute(sql.SQL("SELECT row_to_json(t)::text FROM {} t").format(
                sql.Identifier(table),
            )).fetchall()
            rows[table] = sorted(str(value[0]) for value in values)
            counts[table] = len(values)
        columns = conn.execute(
            "SELECT table_name, column_name, data_type, is_nullable, column_default, "
            "character_maximum_length, numeric_precision, numeric_scale, datetime_precision "
            "FROM information_schema.columns WHERE table_schema='public' "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
        constraints = conn.execute(
            "SELECT c.relname, conname, contype, conkey, confkey, confrelid::regclass::text, "
            "convalidated, condeferrable, condeferred, confupdtype, confdeltype, confmatchtype "
            "FROM pg_constraint k JOIN pg_class c ON k.conrelid=c.oid "
            "JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='public' "
            "ORDER BY c.relname, conname"
        ).fetchall()
        indexes = conn.execute(
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename, indexname"
        ).fetchall()
    return Snapshot(counts, digest(rows), digest([columns, constraints, indexes]))


def seed(db: Database) -> tuple[str, str]:
    now = time.time()
    with db.session(write=True) as session:
        user = User(issuer="urn:blastradius:disposable-drill", subject="synthetic",
                    name="Synthetic restore probe")
        org = Organization(name="Synthetic restore workspace")
        session.add_all([user, org])
        session.flush()
        session.add(Membership(user_id=user.id, organization_id=org.id, role="owner"))
        project = Project(organization_id=org.id, name="Synthetic restore project")
        session.add(project)
        session.flush()
        ids = []
        for age in (8 * 86400, 0):
            analysis = Analysis(
                project_id=project.id, organization_id=org.id, created_by=user.id,
                base_label="synthetic", candidate_label="synthetic", status="failed",
                error="synthetic_restore_probe", created_at=now - age,
            )
            session.add(analysis)
            session.flush()
            session.add(AnalysisArtifact(
                analysis_id=analysis.id, format="markdown", media_type="text/plain",
                content="Synthetic retention sentinel. Not an analysis report.",
            ))
            ids.append(analysis.id)
        session.add(Usage(organization_id=org.id, period="2000-01", analyses=2, exports=0))
        for age in (92 * 86400, 91 * 86400, 0):
            reviewer = User(issuer="urn:blastradius:disposable-drill", subject=str(age),
                            name="Synthetic feedback reviewer")
            session.add(reviewer)
            session.flush()
            session.add(BetaInterest(
                name="Synthetic beta request", email="synthetic@example.test",
                company="", role="", problem="Synthetic retention probe",
                privacy_version="2026-09-20", created_at=now - age,
            ))
            session.add(AnalysisFeedback(
                analysis_id=ids[1], project_id=project.id, organization_id=org.id,
                user_id=reviewer.id, useful=False, message="Synthetic feedback probe",
                created_at=now - age, updated_at=now - age,
            ))
            session.add(ProductEvent(name="beta_interest_submitted", created_at=now - age))
        session.add(AnalysisFeedback(
            analysis_id=ids[0], project_id=project.id, organization_id=org.id,
            user_id=user.id, useful=False, message="Synthetic cascade probe",
        ))
        session.add(ProductEvent(
            name="analysis_failed", analysis_id=ids[0], project_id=project.id,
            organization_id=org.id, user_id=user.id,
        ))
    return ids[0], ids[1]


def grant_runtime(pg: DisposablePostgres) -> None:
    with pg.connect(TARGET, MIGRATOR) as conn:
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(RUNTIME)))
        conn.execute(sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
        ).format(sql.Identifier(RUNTIME)))
        conn.execute(sql.SQL(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
        ).format(sql.Identifier(RUNTIME)))
        conn.execute(sql.SQL("REVOKE ALL ON TABLE alembic_version FROM {}").format(
            sql.Identifier(RUNTIME),
        ))
        conn.execute(sql.SQL("GRANT SELECT ON TABLE alembic_version TO {}").format(
            sql.Identifier(RUNTIME),
        ))


def integrity_checks(pg: DisposablePostgres) -> list[str]:
    checks = [
        ("foreign_key", "INSERT INTO memberships VALUES ('absent','absent','owner')", "23503"),
        ("membership_role", "UPDATE memberships SET role='superuser'", "23514"),
        ("identity_unique",
         "INSERT INTO users (id, issuer, subject, email, name, created_at, email_verified) "
         "SELECT 'duplicate', issuer, subject, email, name, created_at, "
         "email_verified FROM users LIMIT 1", "23505"),
        ("runtime_no_ddl", "CREATE TABLE forbidden_probe (id integer)", "42501"),
        ("runtime_no_migration_write", "DELETE FROM alembic_version", "42501"),
    ]
    with pg.connect(TARGET, RUNTIME) as conn:
        flags = conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        require(flags == (False,) * 5, "runtime_role_privileges_too_broad")
        require(conn.execute(
            "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname='public'"
        ).fetchall() == [(MIGRATOR,)], "unexpected_table_owner")
        for name, statement, expected in checks:
            try:
                with conn.transaction():
                    conn.execute(statement)
                    raise DrillError("integrity_guard_not_enforced_" + name)
            except psycopg.Error as exc:
                require(exc.sqlstate == expected, "unexpected_integrity_error_" + name)
    return [name for name, _, _ in checks]


def operator_env(settings: Settings) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("BR_")}
    env.update({
        "BR_ENV": "test", "BR_AUTH_MODE": "disabled", "BR_ADMIN_ENABLED": "true",
        "BR_AUTO_MIGRATE": "false", "BR_DATABASE_URL": settings.database_url,
        "BR_DATA_DIR": str(settings.data_dir), "BR_PUBLIC_URL": settings.public_url,
    })
    return env


def cleanup_cli(settings: Settings) -> int:
    output = json.loads(command(
        [sys.executable, "-m", "blastradius.server.admin", "cleanup", "--limit", "1"],
        env=operator_env(settings),
    ))
    require(isinstance(output, dict) and type(output.get("removed")) is int, "bad_cleanup_result")
    return int(output["removed"])


def commercial_cleanup_cli(settings: Settings) -> dict[str, int]:
    output = json.loads(command(
        [sys.executable, "-m", "blastradius.server.admin", "cleanup-commercial", "--limit", "1"],
        env=operator_env(settings),
    ))
    require(isinstance(output, dict) and isinstance(output.get("removed"), dict),
            "bad_commercial_cleanup_result")
    removed = output["removed"]
    require(set(removed) == {"beta_interest", "analysis_feedback", "product_events"}
            and all(type(count) is int for count in removed.values()),
            "bad_commercial_cleanup_counts")
    return {str(name): int(count) for name, count in removed.items()}


def run(directory: Path) -> dict[str, object]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    pg = DisposablePostgres()
    started = time.monotonic()
    try:
        pg.start()
        pg.initialize()
        settings = pg.settings(SOURCE, directory / "source")
        db = Database(settings)
        try:
            db.migrate()
            db.migrate()
            require(db.ready(), "source_schema_not_ready")
            expired, current = seed(db)
        finally:
            db.engine.dispose()
        before = snapshot(pg, SOURCE)
        archive = pg.pg("pg_dump", SOURCE, "--format=custom")
        require(archive.startswith(b"PGDMP"), "invalid_archive")
        archive_path = directory / "synthetic.dump"
        with archive_path.open("xb") as handle:
            handle.write(archive)
        archive_path.chmod(0o600)
        restored_at = time.monotonic()
        pg.restore(archive)
        restore_seconds = round(time.monotonic() - restored_at, 3)
        require(snapshot(pg, TARGET) == before, "restore_schema_or_data_mismatch")
        try:
            pg.restore(archive)
            raise DrillError("nonempty_restore_was_allowed")
        except DrillError as exc:
            require(str(exc) == "refusing_nonempty_restore_database", "unexpected_restore_refusal")
        grant_runtime(pg)
        integrity = integrity_checks(pg)
        runtime_settings = pg.settings(TARGET, directory / "restore", RUNTIME)
        with TestClient(create_app(runtime_settings)) as client:
            require(client.get("/health/live").json() == {"status": "ok"}, "liveness_failed")
            ready = client.get("/health/ready")
            require(ready.status_code == 200 and ready.json() == {"status": "ready"},
                    "readiness_failed")
        removed = cleanup_cli(runtime_settings)
        require(removed == 1 and cleanup_cli(runtime_settings) == 0, "retention_not_idempotent")
        with pg.connect(TARGET, RUNTIME) as conn:
            require(conn.execute("SELECT id FROM analyses").fetchall() == [(current,)],
                    "retention_kept_wrong_analysis")
            require(conn.execute("SELECT analysis_id FROM analysis_artifacts").fetchall()
                    == [(current,)], "retention_child_cascade_failed")
            require(conn.execute("SELECT analyses FROM usage").fetchall() == [(2,)],
                    "retention_refunded_usage")
            require(conn.execute(
                "SELECT count(*) FROM audit_events WHERE action='retention.cleanup'"
            ).fetchone() == (1,), "retention_audit_missing")
            require(conn.execute(
                "SELECT count(*) FROM analysis_feedback WHERE analysis_id = %s", (expired,),
            ).fetchone() == (0,), "feedback_cascade_failed")
            require(conn.execute(
                "SELECT count(*) FROM product_events WHERE analysis_id = %s", (expired,),
            ).fetchone() == (0,), "event_cascade_failed")
            head = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        commercial_batches = [commercial_cleanup_cli(runtime_settings) for _ in range(3)]
        expected_batch = {"beta_interest": 1, "analysis_feedback": 1, "product_events": 1}
        require(commercial_batches == [
            expected_batch, expected_batch, dict.fromkeys(expected_batch, 0),
        ], "commercial_retention_not_bounded_or_idempotent")
        with pg.connect(TARGET, RUNTIME) as conn:
            for table in expected_batch:
                require(conn.execute(sql.SQL("SELECT count(*) FROM {}").format(
                    sql.Identifier(table),
                )).fetchone() == (1,), "commercial_retention_kept_wrong_rows")
                require(conn.execute(sql.SQL(
                    "SELECT count(*) FROM {} WHERE created_at <= %s"
                ).format(sql.Identifier(table)), (time.time() - 90 * 86400,)).fetchone()
                    == (0,), "commercial_retention_kept_expired_rows")
            require(conn.execute(
                "SELECT count(*) FROM audit_events WHERE action='commercial.cleanup'"
            ).fetchone() == (3,), "commercial_cleanup_audit_missing")
            require(conn.execute("SELECT analyses FROM usage").fetchall() == [(2,)],
                    "commercial_retention_refunded_usage")
        require(expired != current and snapshot(pg, SOURCE) == before, "source_was_modified")
        return {
            "status": "passed", "scope": "synthetic disposable local logical recovery only",
            "postgres_image": IMAGE, "migration_head": str(head[0]) if head else "",
            "snapshot": asdict(before), "schema_and_data_match": True,
            "schema_signature": [
                "column order, types, length/precision, nullability and defaults",
                "constraint names, types, keys, referenced tables, validation and actions",
                "index definitions",
            ],
            "backup_bytes": len(archive), "backup_sha256": hashlib.sha256(archive).hexdigest(),
            "restore_seconds": restore_seconds,
            "runtime_role": {
                "name": RUNTIME, "superuser": False, "ddl": False, "createdb": False,
                "createrole": False, "replication": False, "bypassrls": False,
                "table_owner": MIGRATOR,
            },
            "integrity_checks": integrity, "nonempty_restore_refused": True,
            "health": {"live": 200, "ready": 200, "transport": "in-process ASGI"},
            "retention": {"removed": removed, "repeat_removed": 0, "cascade": True,
                          "usage_preserved": True, "audited": True},
            "commercial_retention": {
                "batches": commercial_batches, "remaining_per_table": 1,
                "analysis_cascades": True, "usage_preserved": True, "audited": True,
            },
            "source_unchanged": True, "duration_seconds": round(time.monotonic() - started, 3),
            "limitations": [
                "No live database, customer evidence, browser, external provider or TLS tested.",
                "Logical dump is not encrypted, a physical backup, managed backup or PITR.",
                "CHECK expression text is not hashed: PostgreSQL rewrites equivalent casts; "
                "membership role enforcement is checked with a failing write.",
                "No recovery objective, disaster recovery or image promotion approval.",
            ],
        }
    finally:
        pg.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New private directory; existing paths are refused.")
    args = parser.parse_args(argv)
    try:
        report = run(args.output_dir)
    except Exception as exc:
        code = str(exc) if isinstance(exc, DrillError) else type(exc).__name__
        print(json.dumps({"status": "failed", "error": code}), file=sys.stderr)
        return 1
    report["disposable_container_removed"] = True
    report["command"] = [
        sys.executable, str(Path(__file__).resolve()), "--output-dir", str(args.output_dir),
    ]
    path = args.output_dir / "evidence.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
