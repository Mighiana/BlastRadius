# Test configuration worksheet

Tests must create isolated workspaces and disposable databases; do not point them
at a developer's durable history or production.

| Purpose | Test requirement |
|---|---|
| Python | 3.12, `requirements-dev.txt`, `.[server,ui,dev]` after integration |
| Browser | Node 24, checked-in lockfile, `npm ci` |
| Database | Fresh SQLite per test plus PostgreSQL migration/transaction acceptance |
| Identity | Mocks/test issuer; at least two independent tenants and users |
| Payments | Disabled; no live provider credentials or writes |
| GitHub | Fake API client; no live publisher |
| Logs | Redacted request IDs/codes, no full HCL/plans/auth headers |
| Time/limits | Deterministic clocks where appropriate; test oversized and timed-out jobs |

Environment variable names and fixtures come from integrated API/auth/billing
tests. The release worksheet does not introduce an undocumented bypass token.

Run `make check`, `make frontend`, and `make audit` after installation.
CI does not receive repository/provider secrets. Browser acceptance and final
screenshots are owned by the parent release process.

Release verification:

```bash
make wheel
python -m pytest -o addopts='' -q scripts/test_release_*.py
docker compose config --quiet
docker build --check .
sh -n scripts/container-entrypoint.sh
make compose-up
docker compose run --rm migrate
make secret-audit
make container-audit
```

Use the installed virtual environment's Python. Configure local `.env` first;
never point these commands at production. The release tests discover the actual
Alembic head and check packaging, fresh migrations and upgrade-from-`0001`
preservation. An additional server integration test exercises PostgreSQL jobs,
atomic quotas, schema drift and rejection of a second service process:

```bash
# Set BR_TEST_DATABASE_URL through the environment to a fresh disposable database.
.venv/bin/python -m pytest -o addopts='' -q tests/test_server.py::test_postgres_migration_jobs_and_atomic_quotas
```

Without that variable the test explicitly skips; a skipped result is not
PostgreSQL verification. Do not log a database URL or reuse an active app database.
Run the [restore drill](operations.md#backup-and-recovery) independently.
`make promotion-check` is intentionally blocking while the documented HIGH and
CRITICAL upstream OS findings remain. Retain full JSON/SARIF instead of suppressing
them to turn the promotion gate green.
