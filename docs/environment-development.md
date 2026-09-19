# Development configuration worksheet

Prerequisites: Python 3.12, Node 24, npm and Make. Copy
[.env.example](../.env.example) to `.env`, then run `make dev`.

```dotenv
POSTGRES_DB=blastradius
POSTGRES_USER=blastradius
POSTGRES_PASSWORD=local-development-only
BLASTRADIUS_PORT=8000
BLASTRADIUS_ALEMBIC_CONFIG=alembic.ini
BR_ENV=development
BR_AUTH_MODE=demo
BR_PUBLIC_URL=http://localhost:8000
BR_DATABASE_URL=sqlite:///./.local/server.db
BR_DATA_DIR=.local
BR_STATIC_DIR=web/dist
BR_AUTO_MIGRATE=false
```

Runtime contract:

| Setting purpose | Local value/requirement |
|---|---|
| Environment mode | Explicit development; never infer production from absent secrets |
| Database | SQLite local file in ignored `.local/`, or PostgreSQL at `db:5432` inside Compose |
| Identity | Each local demo login provisions a disposable user; use OIDC for persistent identities |
| Browser origin/static assets | Same-origin assets at `/app/web/dist` in container |
| Scratch/output | Per-job temporary directory, cleaned on success and failure |
| Billing | Disabled by default; no live keys |
| Limits | Small finite input/resource/job limits, not unlimited |

Compose overrides the database, data directory and static root for the container.
For Vite hot reload, use [frontend development](frontend.md) and set
`BR_PUBLIC_URL=http://localhost:5173` to match its browser origin.
`.env` is trusted local configuration,
not an upload format. Never commit it. `make dev` does not deploy anything publicly.

For a repeatable fresh-clone check without starting a long-running server:

```bash
cp .env.example .env
make install
make migrate
make check
make wheel
```

`make migrate` can be repeated safely; it uses the installed Alembic resources and
upgrades to the current head. `make start` migrates the local SQLite database and
starts one server process; production uses an explicit migration job instead.
SQLite is for local development, not production deployment.

For local PostgreSQL use `make compose-up`, then `make compose-down` when finished.
Volumes survive shutdown. The app and database use non-root users and read-only
root filesystems. A first Trixie startup creates `postgres-trixie-data`; it does
not migrate an older Bookworm volume. Follow the
[deployment instructions](deployment.md#postgresql-compose) before changing an
existing database installation.
