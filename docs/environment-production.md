# Production configuration worksheet

No public production deployment is authorized by this document.
Use managed secrets and the real server setting names; do not copy local
development credentials into a hosted instance.

Required: `BR_ENV=production`, `BR_AUTH_MODE=oidc`, `BR_AUTO_MIGRATE=false`,
`BR_DATABASE_URL=postgresql+psycopg://…`, `BR_PUBLIC_URL=https://…`,
a stable `BR_SESSION_SECRET` of at least 32 characters, `BR_OIDC_ISSUER`,
`BR_OIDC_CLIENT_ID` and `BR_OIDC_CLIENT_SECRET`. Invalid combinations fail startup.
See [auth](auth.md) for cookies, CSRF and OIDC validation and [API](api.md) for quotas.
Payments stay disabled; do not provision payment-provider credentials.
`BR_PUBLIC_URL` has no default in production and must name the explicitly trusted
HTTPS origin. Request headers never select it. The separate
[private preview profile](environment-preview.md) does not change production's
OIDC, PostgreSQL, secret, host-validation or migration requirements.

| Purpose | Required production decision |
|---|---|
| Database | PostgreSQL connection/TLS, application role, migration role, backups and restore owner |
| Identity | Trusted issuer/audience/JWKS or documented provider config; fail closed if absent |
| Session/browser security | Secure cookies if used, CSRF defense, exact origins/hosts, TLS proxy trust |
| Static files | `/app/web/dist` integration verified; no secrets in `VITE_*` |
| Limits | Input bytes/files/resources/path count, timeout, per-tenant usage and concurrent jobs |
| Scratch | Isolated bounded directories; cleanup and crash recovery policy |
| Logging | Structured redacted logs, access policy and approved retention |
| Payments | Disabled; no checkout, payment credentials or automatic activation |
| Operations | Real readiness endpoint, alarms, operator access and incident owner |
| Legal | Controller/entity, subprocessors, geography, retention, support and terms approved |

Do not enable local/demo auth, public filesystem selectors or debug tracebacks.
Provision and test the operator controls in each row before public use.
The local [.env.example](../.env.example) is deliberately unsuitable for production.

The image itself defaults to production and explicit migrations. Missing required
settings make even the migration command fail. Inject secrets at runtime from the
operator's secret manager; never use Docker build arguments, Dockerfile `ENV`,
committed dotenv files, or `VITE_*` variables for secrets. The image's public
configuration defaults are not credentials.

Use PostgreSQL with certificate verification (`sslmode=verify-full` and the
provider's CA configuration), encrypted storage, and separately scoped migration
and application roles. This is a deployment requirement, not evidence that a
managed service or its certificates have been tested. The Compose database has no
TLS setup, runs a local initialization superuser, and is not that production role
or network design.

Run the same reviewed image once with `migrate`, then with `serve`; allow traffic
only after `/health/ready` succeeds. Keep exactly one ASGI service process for the
database. Do not use rolling replicas, `--workers > 1`, or autoscaling while
the in-memory queue and database service lease remain.

Before promotion, resolve the [image security gate](deployment.md#scan-evidence-and-promotion-gate),
test backup/restore and tenant isolation, install the approved retention schedule,
and validate HTTPS/OIDC using the actual ingress. Local fail-closed and database
tests do not verify those external services. Use the
[operations runbook](operations.md) for ownership, capacity and recovery.
