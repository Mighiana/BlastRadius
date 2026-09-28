# Commercial beta frontend integration

Requires backend commit `97aa2b7b75c181edda221ce27051465ca2b04f0e` or its changes,
including migration `0004`. No new frontend dependencies or secrets.

## Entry points and contracts

- `/beta`: reachable from the landing page and paid-plan early-access links.
  Uses `/api/me` even anonymously and fetches `/api/beta-interest/privacy`.
  Explicit consent and the fetched notice version accompany the bounded form.
  Only a validated successful response produces the saved state; the backend
  returns `201` after committing the request.
  Requests never automatically retry after ambiguous failures. No email,
  invitation, account or payment promise. Optional details remain optional.
- Terminal workspace analyses offer **Give feedback**. Clicking loads the
  current user's feedback; saving sends exactly `{useful, message}` to
  `PUT /api/analyses/{id}/feedback`. Identity/tenant association is server-owned.
  Viewer feedback is supported without granting analysis/project writes.
- `/operator`: navigation is hidden unless authenticated `/api/me` returns
  `capabilities.platform_admin: true`. Direct navigation without that capability
  does not request admin data. Each backend endpoint must independently authorize
  access; client checks do not grant privileges. Demo identities cannot qualify.
- Operator lists use `/api/admin/{resource}?limit=25&offset=0`, selectable limits
  25/50/100, and `next_offset` rather than inferred totals. Schemas strip fields
  outside the contract; unknown failure strings become `analysis_failed`.
  Plans and events consume their aggregate objects directly. Beta requests and
  feedback are visibly separate private-review views. No write controls exist.
- Mutations use the existing in-memory CSRF token and same-origin HttpOnly-cookie
  transport. Native browser Origin is never synthesized by application code.
  Session/CSRF failures refresh the session, not the failed mutation.
- No browser analytics ingestion or third-party telemetry was added. Product
  events remain backend-owned. No source, tokens or review text are put in URLs.

## Product compatibility

Machine decisions, report exports, CLI interfaces and enforcement are unchanged.
SAFE presentation includes “No new modeled blocking findings detected.” with
coverage caveats. Uploads remain independent of GitHub; existing GitHub controls
still depend on actual backend configuration and verified installation access.
The server plan catalog remains authoritative. Primary paid-plan CTAs now open
the beta form; existing disabled checkout status remains for compatibility with
the established acceptance suite.

Lead/feedback review visibility expires at 90 days. Physical deletion is
operator-owned, not automatic. The privacy page describes this distinction and
the bounded server activity summary. Legal review and real support/contact
identity remain deployment-owner work.

## Verification and parent handoff

Run with Node 24 and the repository Python 3.12 virtual environment:

```sh
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
.venv/bin/python -m pytest
.venv/bin/python -m pytest -o addopts='' -q scripts/test_release_*.py
make lint typecheck docs
```

The React commercial-beta regressions cover consent/payload/CSRF, errors and no
retry, foreign feedback IDs, capability gating, backend denial, stripped row
fields, pagination, aggregates, text escaping, and SAFE explanation.

`e2e/commercial-beta.spec.ts` adds real beta persistence and feedback reload,
real ordinary-user operator denial, mocked CSRF failure, and explicitly mocked
operator presentation. Layout checks cover 320/375/430/768/1024/1440px,
no page overflow, and controls of at least 44px. Mocked operator presentation
does not establish signed OIDC or backend operator authorization.

Browser cases are provided for the parent's acceptance stage and have **not**
been run by this frontend contribution session. The existing E2E harness owns
ports 8000/5173 and creates an isolated SQLite database. Do not run it against
customer data or replace strict Origin/CSRF configuration to make it pass.
