# Deployment and local environments

Read the [readiness assessment](readiness.md#known-security--model-limitations) before promoting
images. Both the application and local Compose database have outstanding upstream
scan findings; a working local stack is not production security approval.

The integrated application serves Vite assets and the API from one FastAPI
process. No new public deployment, provider write or purchase has been performed.

## Environments

| Environment | Database | Identity | Payments | Network |
|---|---|---|---|---|
| Development | SQLite or local Compose PostgreSQL | Explicit local/demo mode | Disabled | Loopback |
| Test | Disposable isolated database per test run | Test credentials/mocks; cross-tenant negative tests | Disabled | No live write APIs |
| Production | PostgreSQL, encrypted storage/backups, dedicated application role | Verified production identity provider; fail closed | Disabled | TLS through reviewed ingress |

The root [.env.example](../.env.example) contains local development settings.
The [development](environment-development.md), [test](environment-test.md), and
[production](environment-production.md) sheets identify what must be configured.
The full service setting contract is in [authentication](auth.md).
No Vite variable can hold a secret: `VITE_*` values are public browser assets.

## Local commands

Prerequisites: Python 3.12, Node 24, npm, Make; Docker/Compose for PostgreSQL.

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
It copies only the installed environment, built assets, Alembic configuration and
entrypoint, not the repository checkout. Service and migration entrypoints use
`python -I` to load installed packages. Runtime defaults are `BR_ENV=production`
and `BR_AUTO_MIGRATE=false`; starting without production secrets/configuration
fails closed. Local Compose explicitly opts into the development `.env`.
Python package installers, their vendored libraries and bundled `ensurepip`
wheels are removed from the runtime. Install dependencies in the build stage
and rebuild the image when they change.

Image versions and multi-platform manifest digests are explicit. The handoff uses
Node 24.19.0, Python 3.12.14 on Debian 13 and PostgreSQL 16.15 on Debian 13.
The PostgreSQL target removes the unnecessary privileged `gosu` launcher and
upstream's default snake-oil TLS key/certificate, then runs as `postgres` (UID 999).
Root startup is unsupported in that target. PostgreSQL's official non-root
initialization path was exercised with a fresh named volume.
Image rebuilds can be newer than the underlying version release.
Review base-image provenance and scan both build and runtime images before
promotion. Update digests deliberately when security patches become available.
Python direct dependencies are pinned, but the repository does not yet contain
a fully hashed transitive lock; record the actual resolved environment.
Do not call this a bit-reproducible build.

## Scan evidence and promotion gate

Operations handoff Linux/amd64 scan on 2026-09-19: Trivy **0.74.0**, vulnerability database
updated **2026-09-19T07:03:12Z**. Counts include findings without available fixes;
no ignore files, severity overrides, or vulnerability suppressions were added.

| Image | Critical | High | Medium | Low | Unknown | Findings with listed fixes |
|---|---:|---:|---:|---:|---:|---:|
| Final app, Python 3.12.14 Trixie | 0 | 44 | 49 | 57 | 1 | 0 |
| Original PostgreSQL 16.15 Bookworm, OS | 15 | 78 | 172 | 154 | 0 | 0 |
| Original PostgreSQL bundled `gosu` | 1 | 21 | 21 | 2 | 1 | 46 |
| Final PostgreSQL 16.15 Trixie, OS | 1 | 61 | 88 | 119 | 2 | 0 |

Those operations images had no detected secrets or language-package vulnerabilities.
This historical scan does not cover subsequent application integration; rescan
the final integrated images before promotion.
The remaining database critical finding is `CVE-2026-6653` in
`libxml2 2.12.7+dfsg+really2.9.14-2.1+deb13u3`; the scanner lists no fix.
The Python image was retained because replacing the tested runtime does not
establish vulnerability remediation. A missing fixed version is not a safety
claim: **both final images still fail promotion**.

Pinned multi-platform manifests:

| Base | Digest |
|---|---|
| Python 3.12.14 slim Trixie | `sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9` |
| Node 24.19.0 Bookworm slim (build only) | `sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df` |
| PostgreSQL 16.15 Trixie | `sha256:a3b7f434b2dc57ce85a67e171163eb8ab1a1ebcb39d27484661f26b1dfbe30d6` |

Install a verified Trivy release, then run:

```bash
make audit
make secret-audit
make image
make container-audit
make promotion-check
```

`container-audit` writes full JSON/SARIF and scanner/database metadata to ignored
`.local/audit/`, and fails on detected image secrets. `promotion-check` scans both
images and fails on any HIGH/CRITICAL finding, including those with no listed fix.
An expected nonzero promotion result is not a release approval. Keep the reports
with the source SHA, image IDs, architecture and restore-test evidence.

[Release images](../.github/workflows/release-images.yml) builds local images on
trusted delivery-branch/main pushes and manual runs. It verifies PostgreSQL
migrations/readiness and uploads seven-day scan artifacts; it never publishes.
Source/image secret checks fail ordinary runs. Unresolved OS CVEs are fully
recorded without permanently failing ordinary CI; a manual run with `promotion`
enabled enforces the blocking vulnerability gate. This workflow has been linted
and its commands exercised locally, but has not yet been verified on a hosted
runner. Existing dependency audits and Terraform trust boundaries remain.

Docker Hub returned HTTP 429 during local verification. The exact pinned digests
were built through Google's documented [Docker Hub cache](https://cloud.google.com/artifact-registry/docs/pull-cached-dockerhub-images).
This source-preserving fallback was exercised; it neither patches nor changes
image contents:

```bash
sed 's|FROM node:|FROM mirror.gcr.io/library/node:|;s|FROM python:|FROM mirror.gcr.io/library/python:|;s|FROM postgres:|FROM mirror.gcr.io/library/postgres:|' Dockerfile \
  | docker build -f - -t blastradius:local .
sed 's|FROM postgres:|FROM mirror.gcr.io/library/postgres:|' Dockerfile \
  | docker build -f - --target database -t blastradius-postgres:local .
docker compose up -d --wait db
docker compose run --rm migrate
docker compose up -d --wait app
```

If a pinned image is absent from the cache, use an authenticated registry path
approved by the operator; do not substitute an unverified tag.

## PostgreSQL Compose

Compose explicitly overrides `BR_DATABASE_URL` to PostgreSQL at `db:5432` using
`POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD`. The example password is
local-only; use URL-safe values in this local Compose template. Production should
provide a properly encoded managed PostgreSQL URL, TLS, separate roles and secrets.

```bash
docker compose config --quiet
make compose-up
```

`make compose-up` builds both images, starts PostgreSQL, runs one migration job, then starts the
application. `BLASTRADIUS_ALEMBIC_CONFIG=/app/alembic.ini` uses packaged migration
resources and the same `Settings` as `python -m blastradius.server.migrate`.
`BR_AUTO_MIGRATE=false` ensures the service checks the schema instead of changing it.

The database uses `pg_isready`, persists in `postgres-trixie-data`, and exposes no
host port. **Do not attach an existing Bookworm data volume to this image.**
The new volume deliberately leaves the old `postgres-data` volume untouched;
an existing installation must follow the [logical backup/restore procedure](operations.md#backup-and-recovery)
and validate collation/index behavior before switching traffic. A newly empty
database must never be mistaken for a successful upgrade.

App traffic binds only to `127.0.0.1:8000` by default. The app filesystem is
read-only except `/app/.local` and a bounded `/tmp`; all services drop capabilities,
set `no-new-privileges`, and apply CPU/memory/PID and log limits. The database
root filesystem is read-only with writable data and socket mounts.
`app-data` holds the `BR_DATA_DIR` job directories with UID 10001 permissions.
Database records live in PostgreSQL. Exactly one ASGI process per database is
supported; the service lease rejects a second instance. Jobs use a bounded memory
queue and isolated subprocesses, not a distributed durable queue.
See [operations](operations.md#capacity-and-restart-behavior) for sizing and restart behavior.

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

```bash
docker compose exec -T db sh -c 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --command="SELECT version_num FROM alembic_version"'
docker compose run --rm migrate
docker compose run --rm --entrypoint python migrate -I -m alembic -c /app/alembic.ini heads
make wheel
```

`make wheel` verifies every source Python module, including all migration
revisions, is present and current in the wheel. If `dist/` contains several wheels,
select one explicitly with `python scripts/check_integration.py --wheel PATH`.
Release tests upgrade both a fresh SQLite database and an existing `0001`
database to `ScriptDirectory.get_heads()`, repeat the upgrade, preserve existing
data, and assert readiness. Any new revision must update readiness to the actual
packaged head; neither release tooling nor migration commands pin upgrades to
`0001`. PostgreSQL fresh/repeated upgrade and logical restore were also exercised.

For production, use a separately authorized migration database role, then run the
app with only the data permissions it needs. The local Compose role is not that
production privilege design.

## Health, proxy and rollout

The image checks `/health/ready`: the database schema must match the application
and all nine real-engine demo reports must be loaded. At the verified baseline the
head is `0001`; later migrations must advance the readiness contract with the head.
`/health/live` is liveness.
Production host checks use the host from `BR_PUBLIC_URL` in the internal probe.

The entrypoint disables forwarded-header trust. A production TLS ingress needs
explicit trusted-proxy settings, allowed host/origin checks, request-body limits,
timeouts and rate limits. Do not enable trust for arbitrary forwarded headers.
Preserve the public `Host`, keep the backend private, terminate HTTPS at the
reviewed ingress, and set the exact HTTPS origin in `BR_PUBLIC_URL`. OIDC callback
and secure-cookie behavior must be verified through that actual ingress. No TLS
ingress or external OIDC provider was configured or validated in this local test.

Before public deployment: verify a clean build, PostgreSQL migration/restore,
nonroot/read-only operation, TLS and auth failure modes, tenant isolation,
quota/concurrency behavior, cancellation, retention and deletion. Record image
digest and model version. Roll out a small controlled instance before scaling.
Public deployment, billing activation and domains require separate owner approval.
