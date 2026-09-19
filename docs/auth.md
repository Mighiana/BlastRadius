# Authentication and authorization

Production uses Authlib's OIDC authorization-code flow with signed provider ID
tokens, state, nonce and S256 PKCE. There are no local passwords, bearer API keys,
arbitrary identity-selection headers or public membership grants.

## OIDC setup

Register a confidential web application with a trusted OIDC provider:

* Redirect URI: `${BR_PUBLIC_URL}/api/auth/callback`.
* Scopes: `openid email profile`.
* Grant: authorization code; support PKCE S256.
* ID tokens: asymmetric provider-signed JWTs with discovery/JWKS validation.

Set `BR_AUTH_MODE=oidc`, `BR_OIDC_ISSUER`, `BR_OIDC_CLIENT_ID`,
`BR_OIDC_CLIENT_SECRET`, and a stable `BR_SESSION_SECRET` (32+ characters).
Issuer must match the token's `iss` exactly, including a provider-required
trailing slash. The discovery URL is `<issuer-without-trailing-slash>/.well-known/openid-configuration`.
Authlib validates state, token signature, issuer, audience, expiration and nonce;
the callback additionally checks the exact configured issuer and stored nonce.
Missing ID-token claims fail closed. Provider access/refresh/ID tokens are never
stored in the application database or returned to the frontend.

For production also set:

```text
BR_ENV=production
BR_PUBLIC_URL=https://your-application.example
BR_DATABASE_URL=postgresql+psycopg://<service-account>:<secret>@<database>/<database-name>?sslmode=require
BR_AUTO_MIGRATE=false
```

Inject credentials through your secret manager. Run migrations before the service.
Use one ASGI process, same-origin frontend proxying, HTTPS, and `--no-access-log`.
Configure reverse proxies/APM to omit authorization callback query strings,
cookies and request bodies from logs. See [all configuration](api.md).

`GET /api/auth/login` redirects to the provider. After callback success the
service rotates the application session and redirects to `/dashboard`. Failure
returns `400 authentication_failed`, omitting provider exception text. A user is
identified by `(issuer, subject)`, never email alone. Only provider-verified email
is retained. First successful login creates one free workspace with that user
as its only owner. Subsequent logins to the same identity reuse it.

The transient `br_oidc` cookie holds Authlib authorization state/nonce/PKCE data
using Starlette's signed session middleware with a ten-minute expiration. It is
HttpOnly, SameSite Lax and Secure in production. It contains no provider access
tokens. Authorization state is cleared after callback success/failure.

## Application sessions and CSRF

The `br_session` application cookie is an opaque random 256-bit token. Only its
SHA-256 hash is stored, with user ID, separate random CSRF token and expiration.
The cookie is HttpOnly, SameSite Lax, path `/`, and Secure in production.
Sessions are not sliding: default lifetime is eight hours. Expired rows are
removed when new sessions are created. Server-side logout deletes the session,
so a copied old cookie stops working.

Frontend flow:

1. `GET /api/me` with same-origin cookies. This establishes an anonymous session
   and returns `csrf_token`, configuration status and current user/organizations.
2. For OIDC, navigate to `auth.login_url`. For explicit local demo mode, send
   `POST /api/auth/demo` with `X-CSRF-Token`.
3. Fetch `/api/me` again after login for the new session's CSRF token.
4. Add `X-CSRF-Token` to all authenticated POST/DELETE requests and logout.
5. On `401`, clear user state and offer login. On `403 csrf_required`, refresh
   `/api/me`; never retry a mutation indefinitely.

Mutations check CSRF by constant-time comparison, reject mismatched `Origin`
when supplied, and reject `Sec-Fetch-Site: cross-site`. Requests without Origin
still need the unguessable session-bound token. No wildcard credentialed CORS
is configured. Stripe webhook requests instead require a verified provider
signature, timestamp and event validation; they do not trust browser sessions.
GET endpoints do not change organization/project/plan state; `/api/me` can create
an anonymous session for bootstrapping.

Logout affects the BlastRadius session only; provider-global logout and SSO
session revocation are not implemented. OIDC provisioning is first-login signup,
not domain-restricted onboarding. Configure provider policies to restrict who may
sign in. There is no in-app account recovery, owner transfer or user deletion flow.

## Explicit local demo authentication

`BR_AUTH_MODE=demo` is allowed only in `development` or `test`. Production fails
configuration validation with this mode. `POST /api/auth/demo` requires the
anonymous CSRF token from `/api/me`, rotates the cookie, and creates a fresh
random identity/workspace. It accepts no email/user/role/workspace selector.
It is suitable for local validation, not shared public user onboarding. Demo
identities persist in the local DB until the operator resets that disposable DB.

Without configuration, `BR_AUTH_MODE=disabled`; `/api/me` reports it and private
endpoints return `503 authentication_disabled`. Public, fixed Terraform demos
continue to work. The public demos do not share persisted analysis state.

## Tenant and role model

Membership is checked server-side on every request including report downloads
and billing. A guessed valid ID in another tenant returns 404. Membership removal
takes effect on the next request even if the user's login cookie is still valid.

| Capability | Owner | Member | Viewer |
| --- | --- | --- | --- |
| List own projects/history; read/download reports | Yes | Yes | Yes |
| Create project; submit/delete analysis | Yes | Yes | No |
| Delete project and all its analyses | Yes | No | No |
| List/add/remove members | Yes | No | No |
| Read billing details; checkout/portal | Yes | No | No |

Users can create up to five owned free workspaces. Only an owner can add an
already-existing user by opaque ID, and only with `member` or `viewer` role;
member quota is enforced. Owners cannot be removed or created through this API.
There is no global administrator bypass, email-based join, arbitrary tenant
claim, client-selected plan or endpoint to grant ownership.

Tests verify session rotation, hash-at-rest, logout revocation, CSRF/origin
rejection, disabled/production configuration, Authlib's real JWT validation via
mocked HTTP, tenant IDOR and role restrictions. Live provider setup, TLS/proxy
deployment, provider policies and browser SSO are separate operator validation.
