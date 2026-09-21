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
| Payments | Unavailable; no payment configuration enables them |
| Limits | Small finite input/resource/job limits, not unlimited |

Compose overrides the database, data directory and static root for the container.
For Vite hot reload, use [frontend development](frontend.md) and set
`BR_PUBLIC_URL=http://localhost:5173` to match its browser origin.
`.env` is trusted local configuration,
not an upload format. Never commit it. `make dev` does not deploy anything publicly.
For the HTTPS Devin URL, use the separate [preview profile](environment-preview.md)
and `make start ENV_FILE=.env.preview`; do not overwrite the localhost `.env`.

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
root filesystems. A first Alpine startup creates `postgres-alpine-data`; it does
not migrate an older glibc volume. Follow the PostgreSQL compose [migration
procedure](deployment.md#postgresql-compose) before changing an existing
database installation.

## Parallel Desktop demo

For authenticated browser acceptance while another preview is running, use a
free local port and an isolated database/data directory. The verified Desktop
instance used port 8005; choose another free port if it is occupied. Do not
replace the existing `.env`, `.env.preview` or a running user's browser session.

Create an ignored `.env.desktop-demo` with:

```dotenv
BR_ENV=development
BR_AUTH_MODE=demo
BR_PUBLIC_URL=http://localhost:8005
BR_DATABASE_URL=sqlite:///./.local/desktop-demo-8005/server.db
BR_DATA_DIR=.local/desktop-demo-8005
BR_STATIC_DIR=web/dist
BR_AUTO_MIGRATE=false
BLASTRADIUS_ALEMBIC_CONFIG=alembic.ini
BLASTRADIUS_PORT=8005
```

Build the current frontend with `make frontend`, then run
`make start ENV_FILE=.env.desktop-demo`. Open `http://localhost:8005` in the
Desktop browser, using the hostname and port configured above exactly.
Never run two app processes against the same database.

Use a fresh browser context to test **Create local demo workspace** without
signing out an existing demo user. Demo sign-in creates a disposable identity;
logout revokes access and a later demo login does not recover that identity.
Keep both contexts open when the user needs the original workspace afterward.

1. Sign in through the actual demo button, then create/select a workspace and
   create a project.
2. Upload `examples/safe/main.tf` as the baseline and
   `examples/vulnerable/main.tf` as the candidate. Verify queued/running/succeeded,
   BLOCK, score 100 → 20, the critical path and responsible SSH ingress change.
3. Inspect the remediation patch and download JSON/Markdown. Free-plan SARIF
   should remain gated. Apply only the recommended SSH ingress repair to a
   separate local copy; submit a new comparison and verify SAFE, 100 → 100.
4. Open History, reopen both results and reload. Verify the same
   workspace/project/analysis IDs and that the original BLOCK report is unchanged.
5. Run logout and negative tenant/CSRF checks only in disposable test contexts.

The [recorded acceptance](readiness.md#local-authenticated-browser-acceptance)
establishes this local demo flow. The [external preview proxy limitation](environment-preview.md#diagnose-a-proxy-mismatch)
is tracked separately; local success does not establish HTTPS or OIDC acceptance.
