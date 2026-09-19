# Production configuration worksheet — incomplete until integration

No public production deployment is authorized by this document.
Use managed secrets and the real server setting names; do not copy local
development credentials into a hosted instance.

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
Validate startup refuses insecure combinations. Map and verify each row against
the service docs, then update [.env.example](../.env.example) with safe
non-secret examples and pointers to secret provisioning.
