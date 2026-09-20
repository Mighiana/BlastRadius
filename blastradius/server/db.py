from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable, Iterator
from pathlib import Path

from alembic import command
from alembic import context
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from blastradius.server.config import Settings
from blastradius.server.models import Base


class LeaseLost(RuntimeError):
    pass


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    return config


class Database:
    def __init__(self, settings: Settings):
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        sqlite = settings.database_url.startswith("sqlite")
        options: dict = (
            {"connect_args": {"check_same_thread": False, "timeout": 30}}
            if sqlite
            else {"pool_pre_ping": True}
        )
        if settings.database_url.endswith(":memory:"):
            options["poolclass"] = StaticPool
        self.engine = create_engine(settings.database_url, **options)
        if sqlite:
            event.listen(self.engine, "connect", _sqlite_options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.fence: Callable[[Session], None] | None = None
        self.lease_healthy: Callable[[], bool] = lambda: True

    @contextmanager
    def session(self, write: bool = False) -> Iterator[Session]:
        with self.sessions() as session:
            try:
                if self.fence:
                    self.fence(session)
                if write and self.engine.dialect.name == "sqlite":
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                yield session
                if self.fence:
                    self.fence(session)
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def migrate(self) -> None:
        config = migration_config()
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return (
                    connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
                    == ScriptDirectory.from_config(migration_config()).get_current_head()
                )
        except Exception:
            return False


def _sqlite_options(connection, _record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
