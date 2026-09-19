from alembic import context

from blastradius.server.db import run_migrations

run_migrations(context.config.attributes["connection"])
