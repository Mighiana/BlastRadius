from __future__ import annotations

import fcntl
import threading
from pathlib import Path
from typing import IO

from sqlalchemy.engine import Connection
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from blastradius.server.db import Database, LeaseLost


OWNER = """
SELECT EXISTS (
    SELECT 1 FROM pg_locks
    WHERE locktype = 'advisory' AND pid = :pid AND granted
      AND classid = 0 AND objid = 481936024 AND objsubid = 1
      AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
)
"""


class ServiceLease:
    def __init__(self, db: Database, data_dir: Path):
        self.db = db
        self.data_dir = data_dir
        self.file: IO[str] | None = None
        self.connection: Connection | None = None
        self.pid: int | None = None
        self.lost = threading.Event()
        self.lock = threading.RLock()

    def acquire(self) -> None:
        if self.db.engine.dialect.name == "postgresql":
            self.connection = self.db.engine.connect()
            if not self.connection.exec_driver_sql(
                "SELECT pg_try_advisory_lock(481936024)"
            ).scalar():
                self.connection.close()
                raise RuntimeError("Only one server process per database is supported")
            self.pid = self.connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            # Drain transactions admitted by the previous owner before recovery.
            self.connection.exec_driver_sql("SELECT pg_advisory_xact_lock(481936025)")
            self.connection.commit()
        else:
            database = self.db.engine.url.database
            lock_path = (
                Path(database + ".lock")
                if database and database != ":memory:"
                else self.data_dir / "server.lock"
            )
            self.file = lock_path.open("a")
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.file.close()
                raise RuntimeError("Only one server process per database is supported") from None
        self.db.fence = self.fence
        self.db.lease_healthy = self.healthy

    def healthy(self) -> bool:
        with self.lock:
            if self.lost.is_set():
                return False
            if self.connection is not None:
                try:
                    if self.connection.closed or self.connection.invalidated:
                        raise LeaseLost()
                    owner = self.connection.execute(text(OWNER), {"pid": self.pid}).scalar()
                    self.connection.commit()
                    if owner:
                        return True
                except (SQLAlchemyError, LeaseLost):
                    pass
            elif self.file and not self.file.closed:
                return True
            self.lost.set()
            return False

    def fence(self, session: Session) -> None:
        if self.lost.is_set():
            raise LeaseLost("service_lease_lost")
        if self.pid is not None:
            session.execute(text("SELECT pg_advisory_xact_lock_shared(481936025)"))
            if session.execute(text(OWNER), {"pid": self.pid}).scalar():
                return
            self.lost.set()
            raise LeaseLost("service_lease_lost")
        if not self.healthy():
            raise LeaseLost("service_lease_lost")

    def release(self) -> None:
        with self.lock:
            self.lost.set()
            if self.connection is not None:
                try:
                    if not self.connection.closed and not self.connection.invalidated:
                        self.connection.exec_driver_sql("SELECT pg_advisory_unlock(481936024)")
                        self.connection.commit()
                except SQLAlchemyError:
                    pass
                finally:
                    self.connection.close()
            if self.file and not self.file.closed:
                fcntl.flock(self.file, fcntl.LOCK_UN)
                self.file.close()
