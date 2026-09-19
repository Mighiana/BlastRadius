# Test configuration worksheet

Tests must create isolated workspaces and disposable databases; do not point them
at a developer's durable history or production.

| Purpose | Test requirement |
|---|---|
| Python | 3.12, `requirements-dev.txt`, `.[server,ui,dev]` after integration |
| Browser | Node 22, checked-in lockfile, `npm ci` |
| Database | Fresh SQLite per test plus PostgreSQL migration/transaction acceptance |
| Identity | Mocks/test issuer; at least two independent tenants and users |
| Billing | Mock HTTP calls and signed test fixtures; approved sandbox only if explicitly requested |
| GitHub | Fake API client; no live publisher |
| Logs | Redacted request IDs/codes, no full HCL/plans/auth headers |
| Time/limits | Deterministic clocks where appropriate; test oversized and timed-out jobs |

Environment variable names and fixtures come from integrated API/auth/billing
tests. The release worksheet does not introduce an undocumented bypass token.

Run `make check`, `make frontend`, and `make audit` after installation.
CI does not receive repository/provider secrets. Browser acceptance and final
screenshots are owned by the parent release process.
