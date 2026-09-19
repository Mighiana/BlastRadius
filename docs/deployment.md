# Deployment and local environments

**Status:** release scaffolding prepared for integration. Building the complete
application requires the server/frontend units. No new public deployment,
provider write or purchase has been performed.

## Environments

| Environment | Database | Identity | Payments | Network |
|---|---|---|---|---|
| Development | Server's SQLite local mode, or local Compose PostgreSQL | Explicit local/demo mode only if supported by server | Disabled | Loopback |
| Test | Disposable isolated database per test run | Test credentials/mocks; cross-tenant negative tests | Mocks or approved Stripe test mode | No live write APIs |
| Production | PostgreSQL, encrypted storage/backups, dedicated application role | Verified production identity provider; fail closed | Disabled until explicit commercial approval | TLS through reviewed ingress |

The root [.env.example](../.env.example) contains tooling variables only.
The [development](environment-development.md), [test](environment-test.md), and
[production](environment-production.md) sheets identify what must be configured.
Use the **server owner's actual variable names**, not plausible substitutes.
No Vite variable can hold a secret: `VITE_*` values are public browser assets.

## Local commands

Prerequisites: Python 3.12, Node 22, npm, Make; Docker/Compose for PostgreSQL.

```bash
cp .env.example .env
make dev
```

`make dev` installs optional server/UI/dev extras and pinned quality tooling,
runs `npm ci`, lint, types and build, then serves on loopback. Missing integration
files fail before installation. `.env` is a trusted local shell-style file when
using Make; never source environment files from a contributor's PR or upload.

For CLI/legacy-only work, `make install-core` and `make legacy` work independently.
Do not interpret CLI success as authentication/database/frontend verification.

## Image

The multi-stage [Dockerfile](../Dockerfile) builds Vite assets with Node, installs
`.[server]` into a virtual environment, and runs Python as UID/GID 10001.
The build copies assets to `/app/web/dist`; the server must serve that directory.
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

Before running the application, configure its actual database setting to point
at `db:5432`, using values matching `POSTGRES_DB`, `POSTGRES_USER` and
`POSTGRES_PASSWORD`. The root example's password is local-only.
The server setting must **not** silently fall back to SQLite in Compose.

```bash
docker compose config --quiet
docker compose up -d --wait db
docker compose build app
docker compose run --rm migrate
make compose-up
```

`migrate` requires a real `BLASTRADIUS_ALEMBIC_CONFIG` path supplied by the server
unit. Until reconciled, it exits 2 with a clear message. Do not invent a path or
replace migrations with ad-hoc schema creation.

The database uses `pg_isready`, persists in `postgres-data`, and exposes no host
port. App traffic binds only to `127.0.0.1:8000` by default. The app filesystem is
read-only except `/app/.local` and a bounded `/tmp`; capabilities are dropped.
`app-data` holds local persistent application state if needed by the service.
Confirm the server actually writes only there. Named volume permissions must
be tested with UID 10001.

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

The supplied image checks TCP port 8000 only. This verifies that a listener exists,
not authentication, database readiness or healthy analysis.
The integration owner must wire the real liveness/readiness endpoint and ensure
readiness fails when required dependencies are unavailable.

The entrypoint disables forwarded-header trust. A production TLS ingress needs
explicit trusted-proxy settings, allowed host/origin checks, request-body limits,
timeouts and rate limits. Do not enable trust for arbitrary forwarded headers.
Document the actual settings after server integration.

Before public deployment: verify a clean build, PostgreSQL migration/restore,
nonroot/read-only operation, TLS and auth failure modes, tenant isolation,
quota/concurrency behavior, cancellation, retention and deletion. Record image
digest and model version. Roll out a small controlled instance before scaling.
Public deployment, billing activation and domains require separate owner approval.
