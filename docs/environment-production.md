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

## Domains and origins

Use one origin for the integrated app and its API. These reserved example domains
are a worksheet, not configured infrastructure: replace them with real owned DNS
names **before** provider registration or deployment. Record the final strings
in the release's nonsecret configuration inventory.

| Surface | Example | Boundary |
|---|---|---|
| Application and API | `https://app.example.com` | `BR_PUBLIC_URL`; same-origin sessions, `/api/*`, `/dashboard` and assets |
| Marketing, optional | `https://www.example.com` | Static public content links/navigates to the app; no credentialed cross-origin API calls |
| Documentation, optional | `https://docs.example.com` | Public docs only; no application cookies or customer reports |
| OIDC callback | `https://app.example.com/api/auth/callback` | Register this exact URI with the provider; no wildcard |
| GitHub webhook | `https://app.example.com/api/github/webhook` | Signed provider requests; not a second browser origin |

The simplest beta can serve public pages and application from the one integrated
origin. Separate marketing/docs hosts are optional external hosting choices,
not implemented multi-origin application configuration. Do not add a broad cookie
Domain, CORS allowlist or wildcard origin to make separate hosts share sessions.

`BR_PUBLIC_URL=https://app.example.com` is an HTTPS **origin** (no credentials,
path, query or fragment). The app uses it for callbacks, cookie security and
mutation Origin checks; request `Host`, `Origin` or forwarded headers cannot
replace it. Production trusted-host validation permits the configured hostname.
Use a matching Host on ingress/internal readiness probes. Preserve the public
Host at the private backend; the entrypoint disables proxy-header trust.
An HTTPS ingress does not require trusting arbitrary `X-Forwarded-*` values.

Nonsecret configuration skeleton:

```text
BR_ENV=production
BR_AUTH_MODE=oidc
BR_PUBLIC_URL=https://app.example.com
BR_AUTO_MIGRATE=false
BR_DATA_DIR=/app/.local
BR_STATIC_DIR=/app/web/dist
BR_ADMIN_ENABLED=false
```

This skeleton intentionally cannot start by itself. Supply `BR_DATABASE_URL`,
`BR_SESSION_SECRET`, `BR_OIDC_ISSUER`, `BR_OIDC_CLIENT_ID` and
`BR_OIDC_CLIENT_SECRET` from approved configuration/secret references. Preserve
an issuer's exact trailing-slash form. Use different `BR_DATABASE_URL` credentials
for the migration job and service; configure PostgreSQL `sslmode=verify-full`
and its trusted CA, not certificate-validation bypass. Neither identity should
be a PostgreSQL superuser.

Optional GitHub settings and private-file requirements are in
[GitHub App setup](github.md#operator-setup). Keep `BR_ADMIN_ENABLED` disabled in
the serving process; enable it only in a restricted operator job when needed.
Keep a secret inventory of owner, purpose, expiry, rotation/revocation procedure
and reference name, never secret values. Rehearse rotation before beta; changing
the session signing key invalidates transient OIDC state, not automatically all
opaque DB-backed application sessions. Use session revocation for those.

### Database role handoff

Have the database administrator create a database owned by a dedicated migration
role and a separate login runtime role, each without superuser, role/database
creation, replication or bypass-RLS privileges. Use private credential injection
and the provider's documented role-creation procedure. Do not make runtime a
member of the migration role. Neither credentials nor role provisioning are
performed by this repository.

Run migrations as the owner role. Then apply the following grant pattern as that
owner, replacing `br_runtime` with the actual reviewed runtime role. This is the
pattern exercised by the local restore drill:

```sql
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO br_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO br_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO br_runtime;
REVOKE ALL ON TABLE alembic_version FROM br_runtime;
GRANT SELECT ON TABLE alembic_version TO br_runtime;
```

Review access for other approved operator/backup roles before revoking public
schema access. Repeat/review grants after migrations introduce tables; do not
grant future migration metadata writes through a blanket default-privilege rule.
Verify runtime can acquire the advisory service lease, recover unfinished jobs,
read readiness, write authorized application data and run bounded cleanup while
public-schema table creation and migration-metadata writes fail. PostgreSQL roles
separate operational privileges; tenant authorization is enforced in the app,
not by one database user per tenant.

## Verification through the real ingress

After the owner approves/configures hosting, run against the chosen real origin:

```sh
curl --fail --silent --show-error https://app.example.com/health/live
curl --fail --silent --show-error https://app.example.com/health/ready
```

Expected JSON is `{"status":"ok"}` and `{"status":"ready"}`. Do not use `-k`,
dump auth headers, or include callback queries in diagnostics. These commands
are owner acceptance steps, not claims that a real domain was tested here.
Complete the [owner checklist](owner-setup.md) and retain redacted evidence for
TLS renewal, OIDC login/logout, Origin/Host rejection, tenant isolation and
GitHub delivery before opening beta traffic.
