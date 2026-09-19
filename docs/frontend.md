# BlastRadius web application

The React application in `web/` consumes the FastAPI contract in [api.md](api.md).
It never computes a substitute security result. Python remains the analysis
engine. Public demo reports come from the nine real backend fixture comparisons.
The landing preview requests the same risky SSH comparison as the demo.

## Local setup

Prerequisites: Python 3.12, Node **24.19.0** (`web/.nvmrc`), npm, and Bash on
Linux/macOS. Windows setup has not been verified. All direct JavaScript
dependencies are exact pins and `web/package-lock.json` records the full tree.
npm **11.6.2** was used to generate the lockfile. npm 10 has a resolver crash when
updating Vitest's optional peer tree; use npm 11.6.2 for dependency changes.

From the repository root:

```bash
nvm install "$(cat web/.nvmrc)"
nvm use "$(cat web/.nvmrc)"
npm --prefix web run setup
```

`web/scripts/setup.sh` creates `.venv`, installs `.[server,ui,dev]`, and runs
`npm ci` in `web/`. To select an installed interpreter:
`PYTHON=/path/to/python3.12 npm --prefix web run setup`. This script installs
dependencies only; it neither starts services nor changes account settings.
For an existing backend environment, just run `npm --prefix web ci`.
To regenerate dependencies, use `npx --yes npm@11.6.2 install` from `web/`.

Start the API from the repository root:

```bash
export BR_AUTH_MODE=demo
export BR_PUBLIC_URL=http://localhost:5173
.venv/bin/python -m blastradius.server.migrate
.venv/bin/python -m uvicorn blastradius.server.app:app \
  --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

In a second terminal:

```bash
npm --prefix web run dev
```

Open `http://localhost:5173`. Vite uses a strict port and proxies `/api` and
`/health` to `http://127.0.0.1:8000`. Set `BR_PUBLIC_URL` to the exact browser
origin, including scheme and port; do not mix `localhost` and `127.0.0.1`.
Cookies and mutation CSRF checks depend on the origin. Public landing/demo pages
work with `BR_AUTH_MODE=disabled` and without any credentials.
Development demo login explicitly creates an isolated local identity. Signing
out loses that identity; it is unsuitable for real users or sensitive inputs.

## Routes and behavior

| Route | Purpose |
| --- | --- |
| `/` | Product landing page and backend-generated SSH preview |
| `/demo` | Network, IAM, and storage comparisons; safe baseline → risky → remediation |
| `/dashboard` | Authenticated workspace, projects, uploads and saved reports |
| `/history` | Open, export and delete analyses; project and page selection |
| `/pricing` | Free/Pro/Team limits, clearly marked test billing |
| `/billing` | Organization usage, subscription state, owner-only test checkout/portal |
| `/guide` | Setup, CLI, Actions, coverage, privacy and security boundaries |

The graph renders a selected engine-reported path, offers a selector for other
paths, and exposes all relationships as native keyboard-operable disclosures.
Before/after snapshots use their actual nodes, edges, score and reachability.
At widths below 901px the path becomes vertical. Resource IDs, source changes
and evidence wrap without a horizontally scrolling document or clipped graph.
The heuristic score is not a risk probability. A SAFE comparison does not
assert that existing exposure is absent (the IAM fixture's SAFE score is 85).
The IAM remediation is explicitly a reviewed fixture, not a generated IAM fix.

Uploads accept flat `.tf` snapshots or `terraform show -json` output. The
frontend validates file names, duplicates, NUL bytes, plan structure, file count,
and the 1 MiB serialized request limit. The server independently enforces all
limits. There is no arbitrary server-path field, Git execution, repository
connection, or cloud deployment. Terraform text is always rendered as text.

## API integration

`web/src/api.ts` validates successful JSON responses with Zod before rendering.
Malformed responses and sanitized backend error codes have actionable UI states.
The client includes same-origin cookies and keeps CSRF/session data in memory;
it does not use localStorage, sessionStorage, an access-token URL, or analytics.
Concurrent initial session fetches are coalesced to avoid racing cookie rotation.

* Public: `GET /api/demo/scenarios`, `GET /api/demo/{id}?stage=…`.
* Session: `GET /api/me`, `POST /api/auth/demo`, `POST /api/auth/logout`.
  OIDC uses the documented `/api/auth/login` browser redirect.
* Workspace: `POST /api/organizations`, `GET/POST /api/projects`.
* Analysis: `POST /api/analyses`, poll `GET /api/analyses/{id}` with bounded
  backoff, paginated `GET /api/projects/{id}/analyses`, `DELETE /api/analyses/{id}`.
  Project and analysis IDs are carried in route query parameters; changing a
  project/workspace clears the selected report. Pending jobs do not show a verdict.
* Export: `GET /api/analyses/{id}/report?format=json|markdown|sarif`.
  Public demo exports serialize the validated real report or its engine-produced
  Markdown/SARIF. Exported diffs/patches can contain sensitive source.
* Billing: owner-only `GET /api/organizations/{id}/billing` and documented
  `POST /billing/checkout` / `POST /billing/portal` suffixes. Returned redirect
  URLs must use HTTPS and exactly `checkout.stripe.com` or `billing.stripe.com`.
  Use Refresh status after returning to read webhook-confirmed entitlements;
  the return URL never marks a subscription paid.

Viewer membership hides project/analysis mutation controls. The server is the
authorization boundary. See [auth.md](auth.md) and [billing.md](billing.md).

## Verification

From the repository root:

```bash
npm --prefix web ci
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
.venv/bin/python -m pytest -o addopts='' -q
```

Unit/component tests cover runtime response validation, CSRF, provider URL
validation, malicious report text, upload guards, real-request demo transitions,
session coalescing, viewer controls and queued/failed job states. Only tests use
mock responses; no fixture results are bundled in the application.

Automated acceptance tests run against a **real local API and engine**:

```bash
cd web
npx playwright install chromium
npm run test:e2e
```

Playwright starts its own API on 8000 and Vite on 5173, refuses to reuse existing
services, and stops them afterward. Keep these ports free. The API harness uses
an isolated SQLite directory under ignored `web/.e2e/`, test/demo auth, and no
billing provider credentials. It increases only the test server's request-rate
limits for the matrix. Do not point these mutating tests at a shared workspace.
Retained databases and failure traces may contain test uploads; remove ignored
artifacts when no longer needed.

The suite exercises all three baseline → BLOCK → remediation scenarios, evidence keyboard
disclosures, before/after snapshots, JSON/SARIF downloads, HCL/plan submissions,
history deletion/opening, usage, sign-out, invalid input, and document/graph
containment at **320, 375, 768, 1024 and 1440px**. Failure traces/screenshots live
in ignored `web/test-results/`; HTML reports in `web/playwright-report/`.
Final parent integration testing/recordings remain a separate acceptance step.

Verified on Linux with Node 24.19.0 and Python 3.12.11:

| Check | Result |
| --- | --- |
| Setup script, `npm ci`, `pip check` | Passed |
| ESLint, TypeScript, Vite production build | Passed |
| Vitest | 33 passed |
| npm audit | 0 reported vulnerabilities |
| Python regression suite, including legacy Streamlit smoke tests | 293 passed, 1 optional PostgreSQL test skipped |
| Playwright real-engine acceptance | 11 passed, 1 backend requirement failure below |

### Integration blocker found against the server handoff

At server commit `afaa7893b6c1fcd06e67f02bced7bbba5ba851fe`,
`GET /api/demo/broad_iam?stage=remediated` returns **REVIEW REQUIRED**, not SAFE.
Its score improves from 20 to 85, one critical path is removed, and the engine
reports one new noncritical path. The UI preserves that backend verdict and the
existing exposure. It must never relabel it SAFE.

The responsive UI tests assert the actual backend remediation report, zero new
critical paths and zero sensitive reachability. A separate mandatory acceptance
test, `required IAM remediation ends in SAFE`, retains the original product
requirement and fails on this inherited backend. This is an engine/demo
comparison integration task for the parent, outside `web/**` ownership.
The requested three complete SAFE → BLOCK → SAFE loops remain unfulfilled until
that backend requirement is resolved. Do not omit this test from final acceptance.

## Production integration and current boundaries

`npm run build` produces `web/dist/`. Serve these static assets over HTTPS with
SPA fallback to `index.html` for app routes; reverse-proxy `/api` and `/health`
to FastAPI under the same origin **before** the fallback. Never return the SPA
HTML for a missing API route. Set `BR_PUBLIC_URL` to that HTTPS origin. Cache
hashed assets, but do not cache HTML/session/API responses across releases/users.
All icons and fonts are bundled locally; no external font/analytics request is
required. Configure CSP, TLS and other security headers on the static host.
Vite dev/preview servers are local development tools, not production hosting.
Never put secrets in `VITE_*` variables: those are public browser bundle values.

This handoff does not deploy or change the server's operational guarantees.
PostgreSQL, OIDC, backups, data retention, secret provisioning, HTTPS, edge
limits and subprocess sandboxing remain operator responsibilities. See
[api.md](api.md) for the single-ASGI-process/queue limitations.

* Billing is Stripe **test mode only**; plan prices are configured by the
  operator. No invented prices, live checkout, production SLA or payment claims.
* Live OIDC/provider browser redirects and configured Stripe provider writes
  require separate acceptance with an operator's sandbox. Local demo auth and
  disabled-billing behavior are available without credentials.
* There is no GitHub App or repository-connect endpoint. The UI links to CLI
  and Actions guidance rather than presenting a nonfunctional connect button.
* Membership administration and project deletion exist in the API but have no
  UI in this scope. User/org offboarding, invite email and scheduled retention
  are not server features.
* Browser errors do not expose server stack traces or machine paths. Model
  diagnostics and source evidence are displayed verbatim as escaped text and
  should still be treated as potentially sensitive.
* Accessibility uses semantic controls, focus states, route focus, reduced
  motion and keyboard evidence. Automated Chromium checks do not substitute
  for a full assistive-technology or cross-browser audit.
