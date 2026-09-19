# BlastRadius web application

The React app in `web/` consumes the FastAPI contracts in [api.md](api.md),
[billing.md](billing.md) and [github.md](github.md). Python remains the security
analysis engine. The frontend displays validated nodes, edges, paths, diagnostics,
source evidence and reports; it does not calculate replacement security results.
Public demo comparisons and the landing preview use actual engine fixtures.

## Local setup

Use Python 3.12 and Node **24.19.0** (`web/.nvmrc`). JavaScript dependencies are
exact pins; `web/package-lock.json` is authoritative. Use npm **11.6.2** when
regenerating the dependency tree. Commands below run from the repository root:

```bash
nvm install "$(cat web/.nvmrc)"
nvm use "$(cat web/.nvmrc)"
npm --prefix web run setup
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```

The setup script creates `.venv`, installs `.[server,ui,dev]`, and runs `npm ci`.
To select an interpreter: `PYTHON=/path/to/python3.12 npm --prefix web run setup`.
The requirements files also supply the pinned Python quality tools and type stubs.
For an existing environment, use `npm --prefix web ci`.

Start the backend:

```bash
export BR_AUTH_MODE=demo
export BR_PUBLIC_URL=http://localhost:5173
.venv/bin/python -m blastradius.server.migrate
.venv/bin/python -m uvicorn blastradius.server.app:app \
  --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

In a second terminal, run `npm --prefix web run dev`, then open
`http://localhost:5173`. Vite proxies `/api` and `/health` to port 8000.
`BR_PUBLIC_URL` must match the exact browser Origin, including scheme and port.
Do not mix `localhost` and `127.0.0.1`. The UI detects Origin mismatch before
showing workspace mutations. Never weaken CSRF or accept arbitrary forwarded
headers to work around deployment configuration.

Public pages work without credentials. Demo login creates an isolated local
identity; signing out loses that identity. Demo users cannot accept invitations.
Real accounts require the operator-configured OIDC provider.

## Routes

| Route | Behavior |
| --- | --- |
| `/` | Product, real SSH preview, workflow guidance and FAQ |
| `/demo` | Three engine comparisons, before/after, evidence and public exports |
| `/pricing` | Public API-backed Free/Pro/Team/Enterprise catalog |
| `/guide` | Upload, CLI, Actions/App, model and data guidance |
| `/security`, `/privacy`, `/terms` | Public trust templates with legal-review warning |
| `/dashboard` | Workspace selection, projects, uploads and persisted reports |
| `/history` | Filtered/paginated retained history, report opening and deletion |
| `/settings` | Workspace rename, project metadata, archive/restore, trusted policy |
| `/team` | Owner/admin members, roles, invitations and entitled audit events |
| `/integrations` | Actual GitHub configuration, installations, connection and latest run |
| `/account` | Identity verification and active-session revocation |
| `/billing` | Usage, retention and plan entitlements; no payment processing |
| `/invitations/accept` | Verified-email invitation acceptance from a fragment token |

Workspace selection stays in React memory across client navigation. Changing
workspaces clears the selected report; project/report query parameters support
history and GitHub report deep links. The dashboard resolves a linked project’s
workspace through its authorized project-detail endpoint. Project pickers show
up to 100 projects (the backend list limit); higher Enterprise project counts
need additional project-list pagination.

## Commercial beta and permissions

`GET /api/plans` supplies prices, limits and feature flags; no prices or quota
values are hardcoded in rendering. Current catalog defaults are Free $0, Pro $49
proposed/month, Team $149 proposed/month and Enterprise configurable/contact.
Free onboarding goes to the real configured sign-in/demo entry. Paid actions
are disabled with an operator-beta explanation, not fake checkout.

`GET /api/organizations/{id}/usage` supplies current usage, active project count,
members, pending invitations, exports, limits and entitlements. Read-time
evidence retention defaults to 7/90/365 days for Free/Pro/Team and is configurable
for Enterprise. Physical cleanup and backups remain operator responsibilities.
Accepted jobs count toward UTC monthly usage even if they fail; rejected requests
and public demos do not. Deleting an analysis does not refund usage.

All four lowercase roles are supported: `owner`, `admin`, `developer`, `viewer`.
Owners/admins manage projects and trusted policy; developers can analyze; viewers
inspect evidence. Only managers see team controls. Last-owner/owner protections
are reflected in controls and remain enforced by the server. Both role and
feature gates govern policy editing and invitation creation.

Persisted Free reports omit `result.reports.sarif` server-side. The export view
uses that omission to disable SARIF and explain the restriction. JSON/Markdown
remain available. Operator-granted Pro/Team/Enterprise reports and public demos
retain their engine-generated SARIF. Every persisted download still calls the
server’s authorization/retention/entitlement-checked export route.

No payment SDK, checkout, portal, webhook, subscription activation or billing
callback exists in the frontend. See [billing.md](billing.md) for operator grants.

## API integration details

`web/src/api.ts` uses Zod to validate successful JSON before display. Unknown
error codes fall back to sanitized messages; arbitrary backend exception text is
not exposed. Requests use same-origin cookies, `cache: no-store` and the in-memory
CSRF token on POST/PATCH/PUT/DELETE. Session fetches are coalesced to avoid cookie
rotation races. No session, invitation or CSRF tokens use browser storage.

* **Identity:** `GET /api/me`; explicit demo login/logout and OIDC redirect.
  `GET /api/account/sessions`, `DELETE /api/account/sessions/{id}` and
  `DELETE /api/account/sessions` provide device revocation. Session rows contain
  safe IDs and timestamps, never token hashes.
* **Settings:** `PATCH /api/organizations/{id}` renames the workspace.
  `PATCH /api/projects/{id}` always sends the complete update object:
  `name`, `description`, `repository`, `repository_provider`, `default_branch`,
  `environment`, `terraform_root`, `archived`. Archive/restore preserves metadata.
  Archived projects keep retained history and cannot submit new analyses.
* **Policy:** GET/PUT/DELETE on `/api/projects/{id}/policy` and
  `/api/organizations/{id}/policy`. Version-1 fields are the three `gate` booleans,
  `allowed.public_https`, and nullable `thresholds.minimum_security_score`.
  Project forms show inherited effective rules where supplied. Empty defaults
  are explicitly labeled a draft. Saved analysis policy snapshots remain
  historical evidence and do not change when current policy changes.
* **Team:** GET/PATCH/DELETE members; POST/GET/DELETE invitations; paginated
  GET audit events. Only the creation response returns `invitation_url`, for
  private manual delivery. No email sending is claimed. The URL is displayed
  only in memory and can be dismissed.
* **Invitation:** `/invitations/accept#token=...` reads a 43-character base64url
  token, immediately clears the fragment with `history.replaceState`, and sends
  only `{token}` in the acceptance POST body. It validates identity verification
  and blocks demo identities locally; server matching/expiry/single-use checks
  remain authoritative. Signed-out users sign in then reopen the original link.
  There is no analytics or token persistence.
* **History:** GET `/api/projects/{id}/analyses` with `status`, `decision`,
  `input_type`, `branch` (candidate ref), epoch-second `since`/`until`, `limit`
  and `offset`. Dates are entered in browser local time then converted to epoch.
  Next uses response `total`, `limit` and `offset`, not page length.
* **Reports:** POST analysis, bounded polling, history deletion and
  GET `/api/analyses/{id}/report?format=json|markdown|sarif`. Retained details show
  input provenance, base/head refs and SHAs and the trusted policy snapshot.
  Upload validation preserves flat-file, plan-shape, NUL, count and size checks.

### GitHub App

The page reads `GET /api/github/config`,
`GET /api/organizations/{id}/github/installations` and
`GET /api/projects/{id}/github`. Missing credentials produce an explicit
unavailable reason. Installation requires independent operator registration;
opening the installation link is never treated as connection success.

Only active registered workspace installations appear in the connection selector.
The operator supplies a stable numeric repository ID because no repository
discovery endpoint exists. The PUT sends exactly `{installation_id,repository_id}`;
the backend verifies access with GitHub. DELETE disconnects the project after
confirmation, without claiming to uninstall the App or erase retained reports.

PR/check links are constructed only from the backend’s validated repository name,
PR number and check ID. Analysis links use the returned analysis ID. Status and
publication state always come from the backend. Permission requirements are read
from configuration: contents/metadata read and PR/check write. No contributor
workflows, scripts or Terraform providers are run. External integration behavior
requires operator acceptance; local mocks do not verify GitHub or OIDC.

## Graph and responsive behavior

The bounded path viewport follows actual engine nodes and edges, with a path
selector, per-hop disclosures, all-relationship evidence and a node inspector.
An off-path node is not labeled safe. Fit/reset and bounded 100–180% canvas-width
zoom use local scrolling; pan buttons and a focusable scroll region support
keyboard/touch access. This is a path viewer, not a force-directed whole-graph
layout. Before/after uses distinct actual snapshots.

Below 901px paths become vertical. Resource IDs/evidence wrap; code and tables
stay within their panels. Controls use minimum 44px targets, visible focus and
reduced-motion support. The acceptance matrix remains
**320/375/430/768/1024/1440/1920px**.

“SAFE TO MERGE” does not imply secure infrastructure or absence of existing
exposure. Scores are heuristic; incomplete modeling and policy diagnostics must
be reviewed. The real IAM fixture can remain SAFE at score 85 with existing
public compute exposure. Its remediation is a reviewed fixture, not generated
IAM repair.

## Verification

```bash
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
npm --prefix web run test:e2e -- --list
make lint typecheck docs
.venv/bin/python -m pytest -o addopts='' -q -rs
```

Unit/component tests cover API/CSRF validation, session coalescing, upload guards,
backend verdict preservation, plan gates, role permissions, account revocation,
full archive payloads, inherited policy editing, invitation fragment handling in
StrictMode, member protections, history filters/total pagination, GitHub states,
node evidence and bounded graph controls.

Browser acceptance belongs to the parent testing agent after integration:

```bash
cd web
npx playwright install chromium
npm run test:e2e
```

The Playwright harness starts a real API on 8000 and Vite on 5173; neither port
may be occupied. It uses isolated SQLite/data under ignored `web/.e2e/`, demo
auth, no GitHub provider credentials and raised local test request-rate limits.
A database locator under that ignored directory lets the test call the actual
operator `assign-plan` CLI for Pro/Team fixtures. The helper rejects database
locations outside that isolated harness. Never point these tests at a shared
workspace. No payment endpoint or browser-only entitlement is substituted.

Definitions preserve real demo/report/upload/history/deletion/logout and
seven-width containment coverage, and add archive/restore, Free policy/team
gates, unavailable GitHub, account sessions, trust pages, operator-granted Pro
SARIF, Team policy save, invitation creation/revocation and demo-acceptance
rejection. Successful OIDC invite acceptance and live GitHub publication still
need separate configured-provider acceptance. Failure artifacts stay ignored.

## Parent integration requirements and limitations

This frontend scope leaves backend files unchanged. At upstream commit
`1110797b10cde8d2bc931f44b8190e170f5254da`:

1. `blastradius/server/static.py` must add `account`, `settings`, `team`,
   `integrations`, `security`, `privacy`, `terms` to the known SPA route allowlist.
   `invitations/accept` is already included. Client navigation/Vite works; direct
   production deep links to the seven new paths return 404 until corrected.
   Do not add a catch-all that serves HTML for missing API routes.
2. History’s `input_type` query literal accepts only `hcl|plan`, while GitHub
   records have `input_type=github`. The UI therefore offers HCL/plan filters and
   “All inputs (including GitHub)”; a dedicated GitHub filter awaits the focused
   server correction. No unsupported request is fabricated.
3. With built static assets present, unknown API POST requests reach the mounted
   `StaticFiles` handler and return **405**, not the **404** required by
   `test_tenant_isolation_reports_history_and_mutations` and
   `test_payments_cannot_be_activated_and_catalog_is_authoritative`. Both failures
   reproduce on the unchanged upstream commit with a static build present.
   The integration stage must reserve unknown `/api/*` paths before the SPA
   static mount; do not loosen security tests or revive removed billing routes.
   The API-only suite passes before assets are built. Always verify again with
   production assets present after correcting routing.
4. Invitations/audit lists expose limit/offset but no total; those pagers use
   returned row count, so an exact multiple can lead to one empty final page.
   Analysis history has a total and does not have this limitation.

Build output is `web/dist`, served by `BR_STATIC_DIR`. Set `BR_PUBLIC_URL` to the
production HTTPS origin. Bundle icons/fonts locally; never put secrets in
`VITE_*`. Use appropriate CSP/TLS/headers, cache hashed assets and do not cache
HTML/session/API responses across users. Vite is for development, not production.

Trust pages are templates marked **LEGAL REVIEW REQUIRED BEFORE COMMERCIAL
LAUNCH**. They identify missing operator/controller/contact/SLA/legal decisions
without inventing them. This scope does not deploy, configure providers, verify
external services, change backend tenant/Origin/CSRF controls, or run browser
acceptance. Accessibility behavior still needs the parent’s actual seven-width
browser check and an assistive-technology/cross-browser audit.
