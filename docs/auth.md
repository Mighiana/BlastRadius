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
BR_AUTO_MIGRATE=false
BR_LEASE_WAIT_SECONDS=0
BR_TRUST_PROXY_HEADERS=false
```

`BR_LEASE_WAIT_SECONDS` opts into waiting for an existing service lease during a
zero-downtime deployment; it accepts values from 0 through 600 seconds. Keep it
at `0` for the default fail-fast startup behavior. Set
`BR_TRUST_PROXY_HEADERS=true` only when a trusted reverse proxy is the sole
network peer, such as the Render deployment described in
[deployment-render.md](deployment-render.md).

Inject `BR_DATABASE_URL` and other credentials through your secret manager; use
PostgreSQL certificate verification (`sslmode=verify-full` and the trusted CA).
Run migrations before the service.
Use one ASGI process, same-origin frontend proxying, HTTPS, and `--no-access-log`.
Configure reverse proxies/APM to omit authorization callback query strings,
cookies and request bodies from logs. See [all configuration](api.md).

`GET /api/auth/login` redirects to the provider. After callback success the
service rotates the application session and redirects to `/dashboard`. Failure
returns `400 authentication_failed`, omitting provider exception text. A user is
identified by `(issuer, subject)`, never email alone. Only provider-verified email
with a valid mailbox shape and at most 320 characters is retained. Missing,
malformed, non-string and overlong claims leave the account without a verified
email; they are never coerced or truncated into a different mailbox. First
successful login creates one free workspace with that user
as its only owner. Subsequent logins to the same identity reuse it.

The transient `br_oidc` cookie holds Authlib authorization state/nonce/PKCE data
using Starlette's signed session middleware with a ten-minute expiration. It is
HttpOnly, SameSite Lax and Secure for HTTPS origins (including preview and production). It contains no provider access
tokens. Authorization state is cleared after callback success/failure.

### Provider registration worksheet

Assign an identity owner and record these nonsecret decisions alongside the
[domain worksheet](environment-production.md#domains-and-origins). Example domains
must be replaced with the actual owned application origin.

| Provider field | Value / application behavior |
|---|---|
| Application type | Confidential server web application; authorization code with S256 PKCE |
| Issuer | Exact provider issuer in `BR_OIDC_ISSUER`, including any required trailing slash; HTTPS is required whenever OIDC is enabled |
| Client ID | Provider-generated identifier in `BR_OIDC_CLIENT_ID`; never substitute the issuer or App ID |
| Client secret | Secret-manager reference supplied as `BR_OIDC_CLIENT_SECRET`; rotate through the provider owner |
| Redirect/callback URI | `https://app.example.com/api/auth/callback`, exactly matching `BR_PUBLIC_URL` |
| Scopes | `openid email profile`; the application does not request `offline_access` |
| Login entry | `https://app.example.com/api/auth/login`; navigate in the browser |
| Application logout | Same-origin `POST /api/auth/logout` with `X-CSRF-Token`; deletes application session/cookie |
| Provider logout URL | Not consumed by the application; no `BR_OIDC_LOGOUT_URL` setting or provider end-session redirect is implemented |
| Provider post-logout redirect | Not needed by this flow; do not claim configuring one enables provider logout |
| Beta access / verified email | Enforce eligibility at the provider. Missing/unverified email is discarded, not a standalone reason to deny a valid issuer/subject login |

Do not register marketing/docs hosts or wildcard callbacks for the application
client. Review discovery/JWKS connectivity and configure the provider's own access,
MFA and recovery policies. App sessions are host-only; the HTTPS application and
OIDC middleware cookies are Secure, HttpOnly and SameSite Lax.

Acceptance requires real provider login, invalid-state/nonce/issuer denial,
session rotation, CSRF/Origin rejection and logout through the actual TLS ingress.
The local tests use controlled identity data and do not prove provider policy,
SSO revocation or external acceptance. Keep callback queries and state out of logs.
See the [OpenID Connect Core specification](https://openid.net/specs/openid-connect-core-1_0.html)
for issuer/ID-token requirements; the implementation's settings and route contracts
above are the supported integration surface.

## Application sessions and CSRF

The `br_session` application cookie is an opaque random 256-bit token. Only its
SHA-256 hash is stored, with user ID, separate random CSRF token and expiration.
The cookie is HttpOnly, SameSite Lax, path `/`, and Secure for HTTPS origins.
Sessions are not sliding: default lifetime is eight hours. Expired rows are
removed when new sessions are created. Server-side logout deletes the session,
so a copied old cookie stops working.

Frontend flow:

1. `GET /api/me` with same-origin cookies. This establishes an anonymous session
   and returns `csrf_token`, configuration status and current user/organizations.
2. For OIDC, navigate to `auth.login_url`. For explicit local demo mode, send
   `POST /api/auth/demo` with `X-CSRF-Token`.
3. Fetch `/api/me` again after login for the new session's CSRF token.
4. Add `X-CSRF-Token` to all authenticated POST/PUT/PATCH/DELETE requests and logout.
5. On `401`, clear user state and offer login. On `403 csrf_required`, refresh
   `/api/me`; never retry a mutation indefinitely.

Mutations check CSRF by constant-time comparison, reject mismatched `Origin`
when supplied, and reject `Sec-Fetch-Site: cross-site`. Requests without Origin
still need the unguessable session-bound token. No wildcard credentialed CORS
is configured. Payment webhooks and other active payment routes are removed.
GET endpoints do not change organization/project/plan state; `/api/me` can create
an anonymous session for bootstrapping.

Logout affects the BlastRadius session only; provider-global logout and SSO
session revocation are not implemented. OIDC provisioning is first-login signup,
not domain-restricted onboarding. Configure provider policies to restrict who may
sign in. There is no in-app account recovery or user deletion flow. Owners can
promote another member before demoting themselves; the last owner is protected.
Account session APIs list opaque session IDs and creation/expiry times, and
support revoking one or all own sessions. Migrated sessions have unknown creation
times. No hash, cookie or CSRF value is exposed by the session list.

## Explicit local demo authentication

`BR_AUTH_MODE=demo` is allowed in `development`, `test` or the explicit private
[preview profile](environment-preview.md). Production fails
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

Roles are owner/admin/developer/viewer; migration converts legacy member to
developer. See the [permission matrix](organizations.md). All four can read
entitled, nonexpired evidence. Developers can analyze; admins manage settings,
projects and nonowner members; only owners manage owners and delete workspaces.
No HTTP endpoint can assign a plan.

Users can create up to five owned Free workspaces. Team-only invitations replace
arbitrary user-ID grants. Links contain 256-bit random tokens; only hashes are
stored. Acceptance is atomic, email-bound and requires the OIDC provider's
`email_verified: true`. Reauthentication refreshes email and verification state.
Invitation matching ignores ASCII letter case and preserves every non-ASCII
character exactly. It does not merge Unicode spellings such as `straße` and
`strasse`, or translate Unicode domains to ASCII aliases. Invite the exact
provider-verified spelling for internationalized addresses.
Demo/local identities cannot accept invitations. No email provider is installed;
authorized creators manually deliver the one-time copyable link.

If upgrading a database that already accepted email claims under the previous
truncation/Unicode-casefold rules, revoke pending invitations and reissue them
using the intended address. Clear existing users' `email_verified` flags before
reopening invitation acceptance and have recipients sign in again. Previously
truncated claims and normalized invitation spellings cannot be reconstructed
from the stored values. Review previously accepted invitations if that release
was exposed; this change does not remove existing memberships.

## Configure verified email and invitation delivery

In the provider's application configuration, include `email` and the boolean
`email_verified` in the signed ID token. Require the provider's email-verification
flow for accounts that will accept invitations; an email string alone is
insufficient. Use `openid email profile`, register the exact callback above, and
restrict signup in provider policies if the beta is invite-only.

For a real acceptance check, sign in as a manager in an operator-granted Team
workspace, create an invitation to the recipient's verified provider email, and
send the one-time copied link through your existing approved private channel.
The recipient signs in with that identity and opens the link. The fragment is
cleared immediately and the token submitted once in the authenticated POST body.
Do not put invitation URLs in tickets, analytics, access logs or public chat.
Lost/expired links require revocation and a new invitation.

No SMTP/API-key setting is consumed and no email delivery service is installed.
Adding automatic mail requires a separate transport, secret configuration,
delivery/retry design and abuse controls; merely configuring an email provider
does not make this release send messages. Local tests use signed provider mocks
and exercise identity mismatch, unverified email, expiration, replay and races.

Tests verify session rotation, hash-at-rest, logout revocation, CSRF/origin
rejection, disabled/production configuration, Authlib's real JWT validation via
mocked HTTP, tenant IDOR and role restrictions. Live provider setup, TLS/proxy
deployment, provider policies and browser SSO are separate operator validation.
