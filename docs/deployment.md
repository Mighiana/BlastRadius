# Deployment and local environments

The integrated application serves Vite assets and the API from one FastAPI
process. No new public deployment, provider write or purchase has been performed.

## Environments

| Environment | Database | Identity | Payments | Network |
|---|---|---|---|---|
| Development | Server's SQLite local mode, or local Compose PostgreSQL | Explicit local/demo mode only if supported by server | Disabled | Loopback |
| Test | Disposable isolated database per test run | Test credentials/mocks; cross-tenant negative tests | Mocks or approved Stripe test mode | No live write APIs |
| Production | PostgreSQL, encrypted storage/backups, dedicated application role | Verified production identity provider; fail closed | Disabled until explicit commercial approval | TLS through reviewed ingress |

The root [.env.example](../.env.example) contains local development settings.
The [development](environment-development.md), [test](environment-test.md), and
[production](environment-production.md) sheets identify what must be configured.
The full service setting contract is in [authentication](auth.md).
No Vite variable can hold a secret: `VITE_*` values are public browser assets.

## Local commands

Prerequisites: Python 3.12, Node 22.12+ or 24, npm, Make; Docker/Compose for PostgreSQL.

```bash
cp .env.example .env
make dev
```

`make dev` installs optional server/UI/dev extras and pinned quality tooling,
runs `npm ci`, lint, types, unit tests and build, migrates SQLite, then serves at
`http://localhost:8000`. `.env` is a trusted local shell-style file when
using Make; never source environment files from a contributor's PR or upload.

For CLI/legacy-only work, `make install-core` and `make legacy` work independently.
Do not interpret CLI success as authentication/database/frontend verification.

## Image

The multi-stage [Dockerfile](../Dockerfile) builds Vite assets with Node, installs
`.[server]` into a virtual environment, and runs Python as UID/GID 10001.
The build copies assets to `/app/web/dist`, served through `BR_STATIC_DIR`.
Known browser routes return the application shell; missing API, health and asset
paths remain 404. A wheel contains the engine, service, fixtures and migrations;
it does not bundle the frontend, which must be built separately.
The final stage does not require Node, Terraform, AWS credentials or root.

Image versions and multi-platform manifest digests are explicit. The handoff uses
Node 22.23.2, Python 3.12.13 and PostgreSQL 16.15, verified against the upstream
registry. Version releases predate the handoff by more than seven days; the
Node/PostgreSQL image rebuilds were published on the handoff date.
Review base-image provenance and scan both build and runtime images before
promotion. Update digests deliberately when security patches become available.
Python direct dependencies are pinned, but the repository does not yet contain
a fully hashed transitive lock; record the actual resolved environment.
Do not call this a bit-reproducible build.

## PostgreSQL Compose

Compose explicitly overrides `BR_DATABASE_URL` to PostgreSQL at `db:5432` using
`POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD`. The example password is
local-only; use URL-safe values in this local Compose template. Production should
provide a properly encoded managed PostgreSQL URL, TLS, separate roles and secrets.

```bash
docker compose config --quiet
make compose-up
```

`make compose-up` starts PostgreSQL, runs one migration job, then starts the
application. `BLASTRADIUS_ALEMBIC_CONFIG=/app/alembic.ini` uses packaged migration
resources and the same `Settings` as `python -m blastradius.server.migrate`.
`BR_AUTO_MIGRATE=false` ensures the service checks the schema instead of changing it.

The database uses `pg_isready`, persists in `postgres-data`, and exposes no host
port. App traffic binds only to `127.0.0.1:8000` by default. The app filesystem is
read-only except `/app/.local` and a bounded `/tmp`; capabilities are dropped.
`app-data` holds the `BR_DATA_DIR` job directories with UID 10001 permissions.
Database records live in PostgreSQL. Exactly one ASGI process per database is
supported; the service lease rejects a second instance. Jobs use a bounded memory
queue and isolated subprocesses, not a distributed durable queue.

`make compose-down` stops containers while retaining data volumes.
Do not use `down -v` unless explicitly deleting local test data.
Compose is a local/reference deployment, not a managed production platform.

## Migration strategy

Run exactly one migration job per release, before admitting traffic from the new
application. Use the same image and configuration as the service. Do not run
uncoordinated `upgrade head` from every API replica.

Back up PostgreSQL and test restore before a risky schema change. Prefer
backward-compatible expand/contract migrations across releases.
Record the migration head before/after. Treat a failed migration as failed
deployment; never start the new release against an unknown schema.
Automatic destructive downgrades are not a rollback strategy.

For production, use a separately authorized migration database role, then run the
app with only the data permissions it needs. The local Compose role is not that
production privilege design.

## Health, proxy and rollout

The image checks `/health/ready`: the database schema must be at revision `0001`
and all nine real-engine demo reports must be loaded. `/health/live` is liveness.
Production host checks use the host from `BR_PUBLIC_URL` in the internal probe.

The entrypoint disables forwarded-header trust. A production TLS ingress needs
explicit trusted-proxy settings, allowed host/origin checks, request-body limits,
timeouts and rate limits. Do not enable trust for arbitrary forwarded headers.
Document the actual settings after server integration.

Before public deployment: verify a clean build, PostgreSQL migration/restore,
nonroot/read-only operation, TLS and auth failure modes, tenant isolation,
quota/concurrency behavior, cancellation, retention and deletion. Record image
digest and model version. Roll out a small controlled instance before scaling.
Public deployment, billing activation and domains require separate owner approval.
