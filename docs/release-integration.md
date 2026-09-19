# Release-unit integration contract

This document is the handoff for the parent integrator. Baseline:
`787b0402d5d51acd5fcd437b2be455cd20e19da3`. No source engine, app, frontend,
server, packaging metadata or original tests are modified by this unit.

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

## Unresolved settings — do not guess

The source baseline has no service settings. Fill these from the integrated
implementation and replace this section with verified values:

- Actual environment-mode and database setting names; PostgreSQL URL/driver
  compatible with the service's SQLAlchemy configuration.
- Auth issuer/audience/key handling, explicit local mode, production fail-closed
  checks, allowed origins/hosts and cookie/CSRF policy.
- Static root setting or fixed path; readiness/liveness paths and dependencies.
- Alembic config location, script location and packaging of migration revisions.
- Durable data and scratch locations compatible with UID 10001, read-only root,
  writable `/app/.local` and bounded `/tmp`.
- Billing disabled/test-mode settings; concurrency and request-size limits.

`BLASTRADIUS_ALEMBIC_CONFIG` is a **release-tooling** variable used by
`scripts/container-entrypoint.sh`, not an invented server setting. It must name
a real file. The app TCP healthcheck is intentionally only liveness.
Compose currently supplies generic PostgreSQL values; it must be connected
explicitly to the service's actual database setting before acceptance.

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
Strict mypy checks scripts and the server once present; it is not a claim that
all historical engine code is strictly typed. No audit findings are suppressed.

The baseline had ten standard Ruff findings (unused imports and ambiguous `l`
names). They are outside this unit's source ownership. The default fatal rules
do not pretend these are fixed. Engine/UI owners can remove them independently.
Type-checking the server may reveal legacy imported-code issues; resolve them
with the owning unit rather than adding global ignores.

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

Frontend npm checks/audit, full image build, real PostgreSQL migrations, service
health/auth/static serving, billing and browser acceptance cannot be verified
without the parallel implementation. CI intentionally requires those contracts
after integration; it does not silently skip a missing frontend.
