from __future__ import annotations

import fcntl
from pathlib import Path
from typing import IO

from sqlalchemy.engine import Connection

from blastradius.server.db import Database


class ServiceLease:
    def __init__(self, db: Database, data_dir: Path):
        self.db = db
        self.data_dir = data_dir
        self.file: IO[str] | None = None
        self.connection: Connection | None = None

    def acquire(self) -> None:
        if self.db.engine.dialect.name == "postgresql":
            self.connection = self.db.engine.connect()
            if not self.connection.exec_driver_sql(
                "SELECT pg_try_advisory_lock(481936024)"
            ).scalar():
                self.connection.close()
                raise RuntimeError("Only one server process per database is supported")
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

    def release(self) -> None:
        if self.connection:
            self.connection.exec_driver_sql("SELECT pg_advisory_unlock(481936024)")
            self.connection.commit()
            self.connection.close()
        if self.file and not self.file.closed:
            fcntl.flock(self.file, fcntl.LOCK_UN)
            self.file.close()
