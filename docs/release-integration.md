# Integrated release contract

Baseline: `787b0402d5d51acd5fcd437b2be455cd20e19da3`. Five implementation handoffs
are integrated in engine, legacy, server, release and frontend order.
Original tests remain unchanged.

## Contracts that the build uses

| Contract | Consumer | Confirmation |
|---|---|---|
| `web/package.json` and `web/package-lock.json` | `npm ci`, Node image | Frontend unit |
| npm scripts `lint`, `typecheck`, `build` | Make, CI, Docker frontend stage | Frontend unit |
| Vite output `web/dist` | Image `/app/web/dist` | Frontend + server units |
| Python optional extra `server` | Image and Make install | Server-owned `pyproject.toml` |
| `blastradius.server.app:app` | Uvicorn startup | Server unit |
| SQLite local and PostgreSQL production | Environment worksheets/Compose | Server unit |
| Alembic config + migration files available in image | One-shot migration command | Server unit; no path assumed |
| API/static route separation and SPA fallback | Same-origin frontend | Server + frontend units |

`scripts/check_integration.py` fails clearly for missing app/module/package
contracts. It does not verify server behavior, migrations or all imported
dependencies. Build/runtime validation must follow.

## Runtime settings

`BR_DATABASE_URL` selects SQLite locally or `postgresql+psycopg://` in Compose.
`BR_DATA_DIR` is `.local` locally and `/app/.local` in the container.
`BR_STATIC_DIR` defaults to `web/dist`; known browser routes return its index,
while unknown API, health and asset requests remain errors.
`BLASTRADIUS_ALEMBIC_CONFIG=alembic.ini` names the committed config, whose script
location uses packaged resources. The CLI and module migrations share database
settings. `make start` migrates first; `make compose-up` runs a migration job before
the application, with automatic migrations disabled. Readiness is `/health/ready`.

See [auth](auth.md), [API](api.md), [billing](billing.md), and
[deployment](deployment.md) for service and operator responsibilities.

## Required checks after integration

1. Fresh checkout: copy/configure `.env`, `make dev`; confirm static UI and API.
2. Run all original and added tests; no existing test edits to mask changes.
3. `make lint typecheck docs`, `make frontend`, `make audit`.
4. Validate YAML and actionlint; preserve trusted-base analysis and all original
   workflow trust-boundary tests.
5. Build container, migrate real PostgreSQL, run as UID 10001 with read-only root,
   confirm health/readiness, data persistence and clean shutdown.
6. Test migrations from empty/current DB; exercise backup and restore.
7. Verify UI at 320/375/768/1024/1440 widths, graph clipping, errors, history,
   identity and tenant isolation. Parent owns browser evidence.
8. Reconcile README feature/setup claims with the verified final implementation;
   remove pending-integration wording only when verified.

## Tooling scope

Ruff's default rules detect fatal/static issues across the existing engine and
legacy app. `make lint` additionally runs E4/E7/E9/F on new scripts and server.
Strict mypy checks scripts. The engine, legacy app and server use checked function
bodies with silent imports and ignored missing third-party stubs, matching their
handoff contracts; this is not a claim that the whole product is strictly typed.
No audit findings are suppressed.

The baseline had ten standard Ruff findings (unused imports and ambiguous `l`
names). They are outside this unit's source ownership. The default fatal rules
do not pretend these are fixed. Engine/UI owners can remove them independently.
The combined tooling pins agree with `pyproject.toml`.

## Release boundaries

Keep historical CLI consumer pin
`a72c04890640102b315506ab85e5f1ccbe91bb9f` until release approval.
The polished onboarding copy is `docs/github-action.yml`; the existing example
remains unchanged because it is outside this unit's ownership.
No App, live provider calls, merge, public deployment, screenshots or new support
domain/email are claimed.

Parent owns final readiness report, PR, environment blueprint and UI evidence.
No pre-commit configuration was present at baseline. The unit used Python 3.12.13;
tool pins and action pins are documented for the parent's environment setup.

## Handoff verification

On the isolated release branch against the original source baseline:

- All **239 original tests** passed, with **16 additional release-tooling tests**.
- Ruff baseline/strict-new-code checks, strict mypy on three scripts and local
  links/anchors in 23 Markdown documents passed.
- actionlint 1.7.7 with ShellCheck 0.10.0 passed for both repository workflows and
  the new onboarding copy; shell syntax/ShellCheck passed for both scripts.
- Compose configuration and `docker build --check` passed. The latter validates
  Dockerfile rules and metadata, **not a full image build or running service**.
- The pinned PostgreSQL 16.15 service became healthy in an isolated Compose
  project. A SQL row survived stopping and recreating the container through its
  named volume. The isolated test container, network and volume were removed.
- All three synthetic scenarios returned CLI exit sequence 0/1/0; the IAM
  restored baseline still requires review and passes the default gate.
- Wheel build and fresh-venv installation passed; isolated `python -I` loaded
  site-packages and produced safe exit 0 and plan exit 1 without Streamlit.
- The architecture Mermaid diagram parsed successfully with Mermaid 11.9.0 in
  an isolated local documentation-check workspace, not a frontend dependency.
- The [sample report](sample-report.md) was generated by the CLI from the
  repository's safe/vulnerable fixtures, returning the expected exit 1.
- `pip-audit --skip-editable` reported no known vulnerabilities after updating
  development pip to 26.2 and pytest to 9.0.3. Both releases were checked on PyPI
  and older than seven days. No vulnerability ignores were added.

Initial audit found seven advisories across pip 25.0.1 and pytest 8.4.2.
The fixed tool pins are in `requirements-dev.txt`; the Docker build also upgrades
its virtualenv pip. Re-audit the integrated server's dependencies and actual image.
The audit result is a point-in-time check, not a guarantee of no vulnerabilities.

The preceding results describe the isolated release handoff only. Integrated
verification is recorded separately below; parent owns final browser acceptance.

## Integration fixes

- Path deltas check graph edges when analyzer target selection changes from
  sensitive data to compute. An existing public compute prefix is not a new
  path merely because remediation removed its sensitive-data suffix.
- API schema v1 carries `analysis_complete`, per-snapshot coverage/work limits,
  structured phase diagnostics and edge confidence/category/source/remediation.
  Older stored schema v1 reports remain readable; new incomplete results have
  a visible warning and expanded diagnostics. All results come from the engine.
- Static serving, migrations, settings, Compose and readiness share one contract.
- Dependency audits found advisories in Authlib 1.6.5 and Starlette 0.47.3.
  Authlib 1.6.12, Starlette 1.3.1 and compatible FastAPI 0.136.3 are pinned.
  PyPI publication timestamps for these pins are at least seven days old.

## Integrated verification, 2026-09-19

Linux, Python 3.12.13, Node 24.19.0, Docker 29.7.2, Compose 5.4.0:

| Command / check | Result |
| --- | --- |
| `make check` | 438 tests passed, one optional PostgreSQL case skipped; 16 release tests; Ruff, strict script mypy, engine/legacy/server mypy and links in 30 Markdown documents passed |
| `BR_TEST_DATABASE_URL=<disposable PostgreSQL URL> .venv/bin/python -m pytest -o addopts='' -q` | 439 passed, including schema parity, service lease, concurrent quotas, worker execution and tenant cascade deletion on PostgreSQL 16.15 |
| `make frontend` | Clean npm install, ESLint, TypeScript, 34 Vitest tests and Vite production build passed |
| `.venv/bin/python -m pip_audit --skip-editable` and `npm --prefix web audit --audit-level=moderate` | No known vulnerabilities; local editable project was outside the dependency audit, with no advisory suppressions |
| `.venv/bin/python -m pip check` | No broken requirements |
| `.venv/bin/python scripts/check_integration.py` | Passed |
| `.venv/bin/python -m pip wheel . --no-deps --wheel-dir dist` | Wheel built and installed in a fresh venv outside the checkout |
| Isolated `python -I -m blastradius.cli` from the core-only wheel | All three scenarios: baseline 0, risky 1, restored 0; plan JSON and SARIF 1, each one parseable document without checkout paths; no FastAPI/Streamlit installed |
| Same installed wheel with server extra | Packaged migrations and all nine real demo states passed outside the checkout without Streamlit; auth disabled by default |
| `docker compose config --quiet` and `docker build --check .` | Passed |
| Compose app/migration image builds, `up -d --wait db`, `run --build --rm migrate`, `up --build -d --wait app` | Non-root/read-only application and PostgreSQL healthy; migrations ran through committed Alembic config |
| Real HTTP requests against Compose | Health, SPA routes, all nine demos, CSRF/demo login, project creation, subprocess job and JSON/Markdown/SARIF exports passed |
| Compose app recreation | Stored report and session survived; project deletion removed its analyses |
| `cp .env.example .env` then `make dev` | Installed, checked/built frontend, migrated SQLite, started Uvicorn; HTTP health/static routes and demo login passed, billing disabled |

The only Python suite warning is Starlette's deprecation of the httpx-backed
TestClient; its current compatibility path remains working. npm also reports
ESLint 9's support deprecation; lint passes and npm audit reports no vulnerability.

## Remaining acceptance and operational boundaries

- Parent must run the unchanged Playwright suite and final browser/mobile/legacy
  recordings on the integrated revision. This integration session did not drive
  a browser or produce screenshots.
- Real OIDC browser authentication and configured Stripe provider flows remain
  unverified. Their local signature/state/nonce/PKCE/webhook and authorization
  tests pass; provider calls are mocked. Billing accepts test keys only.
- Static coverage is not a cloud-safety proof. IAM reviewed baseline/restored
  score is 85, preserving public compute exposure; no automatic IAM patch exists.
- Exactly one ASGI process per database, in-memory queue, no distributed HA,
  scheduled retention, membership-administration UI or project-deletion UI.
  The underlying membership and deletion APIs enforce ownership/roles.
- Container OS/base-image vulnerability scanning is still required before
  deployment; Python/npm dependency audits do not cover OS packages.
- Production TLS, persistent identity, secrets, database encryption/backups,
  reverse-proxy limits, legal/license decisions and public release remain owner
  responsibilities. No PR, merge, public deployment, purchase, registry
  publication or live provider write was performed during integration.
