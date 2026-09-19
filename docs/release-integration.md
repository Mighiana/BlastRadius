# Integrated release verification and acceptance

This commercial-beta integration preserves frontend commit
`36df10877fd9a1d141805f7a7d160acfa4f61b8e` and operations commit
`6364e1f7fb2b2553a93272ae276a31fb28ea898c` through a normal merge.
Historical release-only/browser results are not current acceptance evidence.

## Contracts

- `GET /api/plans` is the only pricing/limits source. Payments are always false.
- `/api/me` uses `owner|admin|developer|viewer` and embeds effective workspace
  usage/features. Organization policy is Team/Enterprise; project policy and
  saved SARIF are Pro/Team/Enterprise. All saved reads enforce current retention.
- History accepts `status`, `decision`, `input_type=hcl|plan|github`, candidate
  `branch`, epoch `since/until`, `limit/offset` and returns `total`.
- Invitation fragments contain 43-character one-time tokens; acceptance POSTs
  only `{token}` and requires matching verified OIDC email. Demo users cannot join.
- Project PATCH supplies complete metadata/archive fields; `updated_at` is nullable.
- Worker inputs include a trusted persisted policy snapshot; candidate files
  cannot supply policy or execute code. GitHub checks verify current base/head
  repository/ref/SHA boundaries and belong to the configured App.
- Alembic head **0003** is packaged; readiness compares actual heads.
- Built assets live in `web/dist`; all documented product routes support direct
  navigation. Unknown `/api` and `/health` routes never fall through to assets.
  Unsupported methods on existing API routes retain 405.
- Runtime uses one Uvicorn process, installed-package isolated Python,
  non-root UID/GID10001, read-only root and explicit bounded writable storage.

## Verification commands

Use Python 3.12.14 and Node 24.19.0:

```bash
source "$HOME/.nvm/nvm.sh"
nvm use "$(cat web/.nvmrc)"
make check
make frontend
make audit
.venv/bin/python -m ruff format --check --exclude fixtures.py blastradius/server scripts \
  tests/test_spa_integration.py tests/test_github_app.py
make wheel
make integration-check
docker compose config --quiet
sh -n scripts/container-entrypoint.sh
bash -n scripts/verify-demo.sh
```

`make check` runs all engine/server/legacy/Actions tests plus release migration
and package-tool tests, Ruff, mypy and local documentation links. Optional
PostgreSQL cases must also run, using a **disposable database**:

```bash
BR_TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:55432/TEST_DB \
  .venv/bin/python -m pytest -o addopts='' -q
```

These tests cover fresh schemas, populated 0001 upgrades through 0003, model
parity, idempotence, readiness, atomic quota/export counters, invitation races
and bounded cleanup. Do not point them at a live database.

After `make wheel`, install the wheel into a fresh venv outside the checkout and
run `python -I -m blastradius.cli` for all three fixture flows and plan JSON/SARIF.
Check expected exit codes and parse a single output document. Repeat with the
server extra, verify packaged migrations and readiness outside the checkout.
The core wheel does not require FastAPI or Streamlit.

For local container verification, copy the development `.env.example`, then
build app/db, start the DB, run migrations twice and start app:

```bash
docker compose build app db
docker compose up -d --wait db
docker compose run --rm migrate
docker compose run --rm migrate
docker compose up -d --wait app
```

Assert container UID/read-only/resource settings, readiness and a real HTTP
analysis/export. Demo auth here is explicitly development-only; it is not
production OIDC acceptance. If Docker Hub rate-limits anonymous pulls, use a
trusted mirror with the **same digests** for local verification and record that
deviation; do not alter the pinned Dockerfile or dependency policy.

## Parent browser acceptance setup

From a clean integration checkout:

```bash
source "$HOME/.nvm/nvm.sh"
nvm install "$(cat web/.nvmrc)"
nvm use "$(cat web/.nvmrc)"
cp .env.example .env
make dev
```

Use `http://localhost:8000` exactly. For a preview origin, set `BR_PUBLIC_URL` to
that exact scheme/host/port and restart before testing; never disable Origin/CSRF.
Do not run two app processes against the same DB.

Create the test user by demo sign-in; it creates a Free workspace. Public demos
require no seed. Create a project and upload `examples/safe/main.tf` before and
`examples/vulnerable/main.tf` after, or upload
`examples/plans/ssh_open_plan.json`. Verify the expected BLOCK report, provenance,
history, graph/path evidence and JSON/Markdown exports.

For Team acceptance, keep the browser session and run in a second terminal,
from the same checkout/database:

```bash
set -a; . ./.env; set +a
export BR_ADMIN_ENABLED=true
.venv/bin/blastradius-admin inspect organizations --limit 100
.venv/bin/blastradius-admin inspect users --limit 100
.venv/bin/blastradius-admin inspect projects --limit 100
.venv/bin/blastradius-admin inspect failures --limit 100
.venv/bin/blastradius-admin inspect usage --limit 100
.venv/bin/blastradius-admin assign-plan WORKSPACE_UUID team
```

Replace `WORKSPACE_UUID` with the inspected workspace ID. Refresh the session
in the browser. Test policies, manual invitation creation/revocation, audit,
SARIF and downgrade behavior. Repeat assignment with `free` to restore default
limits. This changes only the disposable test DB and never activates payment.

Demo login intentionally cannot impersonate an invited identity. Test real
acceptance only with [configured OIDC](auth.md), or use the existing
provider-mocked server regressions for identity binding. Do not add fake
email/role grant endpoints or pretend local demo acceptance worked.

For automated browser acceptance:

```bash
npm --prefix web run test:e2e -- --list
npm --prefix web run test:e2e
```

The existing Playwright harness owns its isolated database/server and operator
plan command. The parent testing agent owns actual browser execution/recording,
including the seven widths, sessions, roles, state/error handling and trust pages.
This integration does not claim browser results.

## Evidence and remaining boundaries

The integration ran on Linux/amd64, Python 3.12.14 and Node 24.19.0:

| Check | Result |
| --- | --- |
| `BR_TEST_DATABASE_URL=<disposable PostgreSQL 16.15> make check` | 561 Python tests, no skips; 22 release tests; Ruff, mypy and 38-document link check passed |
| `make frontend` | Clean npm install, lint, types, 75 tests across 8 files and production build passed |
| `make audit`; `python -m pip check` | No known dependency vulnerabilities; no broken requirements |
| Ruff formatting | 39 server/script/integration-test files passed; canonical generated fixtures excluded |
| Wheel | Every packaged module checked; clean core installation outside checkout ran 9 scenario cases plus plan JSON/SARIF with isolated Python and expected exits; no FastAPI/Streamlit dependency |
| Installed server wheel | Repeated packaged SQLite migrations through 0003 and readiness passed outside checkout |
| Container/Compose | Same-digest mirror builds, double PostgreSQL migration, healthy app/db, UID10001/999, read-only roots, dropped capabilities and bounded CPU/memory/PIDs verified |
| Real HTTP → frontend Zod | 31 actual container responses across 17 schemas; all public demo states, isolated analysis, operator inspection/grants, Free/Team export gates, policies, sessions, history and deletion passed |
| Fresh local clone | No inherited environment/build artifacts; Node24 `cp .env.example .env && make dev` installed, checked/built, migrated and started; the same 31-response API smoke passed |
| Trivy 0.74.0 | Source/image secret checks passed; app 0 CRITICAL/44 HIGH and DB 1 CRITICAL/61 HIGH reproduced, no listed fixes. Existing promotion gate failed as intended; full severities retained |
| Browser inventory only | 18 Playwright definitions listed; no browser test executed by this integration |

The fresh clone was a full local Git clone of the integration branch with
`--no-hardlinks`; it did not reuse ignored venv, Node, assets or database files.
The container registry fallback changed only the registry hostname supplied to
the local build; committed digests and Dockerfile remain unchanged.
Starlette warns about its httpx TestClient compatibility path and npm warns about
ESLint 9's support status; checks pass, with no suppressions.

The final handoff includes image IDs and complete scan evidence. Provider tests
use mocked HTTP; no live App/OIDC writes are part of these commands. External
TLS, managed PostgreSQL/PITR, production retention jobs, email delivery and
load/SLO acceptance remain unverified.
The [readiness report](readiness.md) is authoritative for launch blockers.

## Tooling scope

Ruff checks fatal/static errors and E4/E7/E9/F in server/scripts. Mypy checks
scripts strictly and engine/server/legacy function bodies under the existing
configuration; the entire product is not claimed to be strictly typed.
Formatting checks cover server/scripts and the integration regression files.
The generated `server/fixtures.py` retains its generator's canonical formatting;
regenerate it with `python -m blastradius.server.bundle_demos`, not a formatter.
No advisory suppressions, hook bypasses or weakened security tests are used.
