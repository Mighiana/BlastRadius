from alembic import context

from blastradius.server.config import Settings
from blastradius.server.db import Database, run_migrations

connection = context.config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    db = Database(Settings.from_env())
    try:
        with db.engine.begin() as connection:
            run_migrations(connection)
    finally:
        db.engine.dispose()
