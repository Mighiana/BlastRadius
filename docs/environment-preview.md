# Private Devin preview

Use this profile only for a Devin preview protected by session access. It is not
a public production deployment. Demo sign-in creates a disposable identity; it
does not verify OIDC, email delivery or persistent production accounts.

**Current acceptance boundary:** the observed Devin preview proxy rewrites the
browser's HTTPS `Origin` to `http://localhost`. BlastRadius rejects that request
even when configured correctly. Authenticated preview acceptance remains blocked
until the proxy preserves Origin; the profile below does not bypass that boundary.

## Configure the exact origin

1. Obtain the current URL from Devin's `browser_preview` tool for port 8000.
   Use its exact HTTPS origin, with no path, query, fragment or wildcard.
   A new session can have a different origin; never copy a previous session's URL.
2. Copy [.env.preview.example](../.env.preview.example) to `.env.preview`.
   Fill `BR_PUBLIC_URL` with the origin from step 1. An empty value fails startup.
3. Build with `make frontend` if assets are not current. Stop the existing server
   on port 8000, then run:

   ```bash
   make start ENV_FILE=.env.preview
   ```

4. Open that HTTPS preview URL. Confirm `/api/me` reports the same
   `auth.public_url` as the browser's `window.location.origin`; then sign in,
   create a workspace/project, run analysis and reopen the result from History.
   Reissue `browser_preview` after restarting a sleeping machine.

The selected environment file is explicit; the server never infers trust from
`Host`, `Origin`, `Forwarded` or `X-Forwarded-*`. Exact Origin, Fetch Metadata,
session, CSRF, tenant and role checks remain enabled. HTTPS application and OIDC
cookies use Secure, HttpOnly and SameSite Lax even when the internal connection
from the preview proxy to Uvicorn uses HTTP.

The preview template uses a separate ignored SQLite database/data directory.
Keep `.env.preview`, session secrets, identities and database contents out of
Git. Do not reuse a production database. Sign-out ends access to the disposable
demo identity; a new demo sign-in creates a new identity.

## Environment separation

| Environment | Configuration | Origin |
| --- | --- | --- |
| Local | `make start` loads `.env`; `BR_ENV=development` | Defaults to `http://localhost:8000`; Vite uses an explicitly configured port 5173 |
| Devin preview | `make start ENV_FILE=.env.preview`; `BR_ENV=preview` | Explicit exact HTTPS origin returned by the preview tool |
| Production | Managed environment/secrets; `BR_ENV=production` | Explicit HTTPS public origin; OIDC, PostgreSQL, stable secret and explicit migrations required |

`make migrate ENV_FILE=.env.preview` uses the same selected configuration.
Local development retains HTTP cookies and localhost behavior. A browser using
localhost against the **preview-configured** server is deliberately not a trusted
mutation origin; stop it and restart with `.env` to return to local development.
One running instance has one trusted browser origin.

Never fix an origin mismatch by accepting arbitrary headers, wildcarding
preview domains, disabling Secure cookies/CSRF, or relaxing production validation.
See [local setup](environment-development.md), [production](environment-production.md)
and [authentication](auth.md).

## Diagnose a proxy mismatch

Matching the visible URL and `/api/me.auth.public_url` is necessary but does not
prove the proxy preserves the browser's request headers. Compare the browser's
Origin and Fetch Metadata with the values received by the application. Collect
only safe header metadata; never log cookies, CSRF tokens or request bodies.

The 2026-09-20 actual-preview diagnostic captured one sign-in request:

| Header | Browser | Application |
| --- | --- | --- |
| `Origin` | Configured HTTPS preview origin | `http://localhost` |
| `Sec-Fetch-Site` | `same-origin` | `same-origin` |
| `Host` | Not captured | `localhost` |
| `X-Forwarded-Host` | Absent | Preview hostname |
| `X-Forwarded-Proto` | Absent | `http` |

Session-cookie and CSRF-header presence were confirmed at both ends. The
application returned `403 invalid_origin` as intended. Forwarded Host is not
evidence of the original Origin and cannot replace validation. This platform
issue was reported to Cognition; no authenticated workspace/project/history
acceptance is claimed for this preview. Temporary instrumentation was removed.

An ingress used for authenticated acceptance must preserve Origin and cookie
security attributes. Do not change `BR_PUBLIC_URL` to the rewritten internal
origin or reconstruct the browser's Origin from forwarded headers.
