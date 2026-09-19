# Production configuration worksheet

No public production deployment is authorized by this document.
Use managed secrets and the real server setting names; do not copy local
development credentials into a hosted instance.

Required: `BR_ENV=production`, `BR_AUTH_MODE=oidc`, `BR_AUTO_MIGRATE=false`,
`BR_DATABASE_URL=postgresql+psycopg://…`, `BR_PUBLIC_URL=https://…`,
a stable `BR_SESSION_SECRET` of at least 32 characters, `BR_OIDC_ISSUER`,
`BR_OIDC_CLIENT_ID` and `BR_OIDC_CLIENT_SECRET`. Invalid combinations fail startup.
See [auth](auth.md) for cookies, CSRF and OIDC validation, [API](api.md) for quotas,
and [billing](billing.md) for optional test-only Stripe settings.

| Purpose | Required production decision |
|---|---|
| Database | PostgreSQL connection/TLS, application role, migration role, backups and restore owner |
| Identity | Trusted issuer/audience/JWKS or documented provider config; fail closed if absent |
| Session/browser security | Secure cookies if used, CSRF defense, exact origins/hosts, TLS proxy trust |
| Static files | `/app/web/dist` integration verified; no secrets in `VITE_*` |
| Limits | Input bytes/files/resources/path count, timeout, per-tenant usage and concurrent jobs |
| Scratch | Isolated bounded directories; cleanup and crash recovery policy |
| Logging | Structured redacted logs, access policy and approved retention |
| Billing | Off until owner approval; never auto-upgrade from test to live credentials |
| Operations | Real readiness endpoint, alarms, operator access and incident owner |
| Legal | Controller/entity, subprocessors, geography, retention, support and terms approved |

Do not enable local/demo auth, public filesystem selectors or debug tracebacks.
Provision and test the operator controls in each row before public use.
The local [.env.example](../.env.example) is deliberately unsuitable for production.
