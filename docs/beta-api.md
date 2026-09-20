# Commercial beta API contract

This contract covers server-side beta interest, analysis feedback, first-party
product events, and platform operator inspection. It does not enable payments,
email delivery, automatic beta invitations, or infrastructure collection.

## Browser session and errors

Use same-origin requests with the existing `br_session` HttpOnly cookie.
First call `GET /api/me`, including when anonymous, to create a persisted anonymous
session and obtain `csrf_token`. The configured origin is
`response.auth.public_url`. Send `X-CSRF-Token: <csrf_token>` on mutations.
`POST /api/beta-interest` and `PUT /api/analyses/{id}/feedback` also require
`Origin` to equal the configured public origin exactly. Missing, `null`, alternate,
and trailing-slash origins are rejected. Cross-site fetches are rejected.
Refresh `/api/me` after authentication because the session and CSRF token rotate.

All responses use `Cache-Control: no-store`. Times are Unix seconds, including
fractional seconds. IDs are opaque UUID strings. Validation failures return
`422 {"detail":"invalid_request"}` without echoing submitted values. Other errors
use `{"detail":"<code>"}`. Do not render server or submitted text as HTML.

Common statuses: `401 authentication_required`, `403 invalid_origin` or
`csrf_required`, `404 not_found`, `413 body_too_large`,
`415 content_encoding_unsupported`, `429 rate_limit_exceeded`.
Successful submission means the database transaction committed.
Authenticated routes return `503 authentication_disabled` when authentication
is configured off.

## Beta interest

### GET /api/beta-interest/privacy

Public, no login required. Response:

```json
{
  "version": "2026-09-20",
  "retention_days": 90,
  "notice": "We collect these details for operator review of beta interest under a 90-day retention policy. Only authorized platform operators can review them. Submission does not create an account, guarantee access, or send an email. Do not include Terraform, credentials, or private infrastructure details. Optional fields may be left blank."
}
```

Display the notice and an unchecked consent checkbox. Send the fetched version
only after the person consents. Do not silently opt people in.

### POST /api/beta-interest

Anonymous or authenticated, using the anonymous-session bootstrap above.
JSON object; unknown fields are rejected. All strings are stripped. No files,
Terraform, repository URLs, credentials, custom metadata, or infrastructure
input fields exist.

| Field | Required | Type and constraints |
| --- | --- | --- |
| `name` | yes | string, 1–100 characters |
| `email` | yes | syntactically valid email string, at most 320 characters |
| `privacy_version` | yes | exact string `2026-09-20` |
| `privacy_consent` | yes | literal JSON boolean `true` |
| `company` | no | string, at most 120 characters, default `""` |
| `role` | no | string, at most 80 characters, default `""` |
| `team_size` | no | integer 1–100000 or null |
| `repository_count` | no | integer 0–100000 or null |
| `primary_cloud` | no | `aws`, `azure`, `gcp`, `multiple`, `other`, `none`, or null |
| `source_control` | no | `github`, `gitlab`, `both`, `other`, `none`, or null |
| `problem` | no | string, at most 1000 characters, default `""` |

No numeric-string or boolean-to-integer coercion. Optional strings accept omission
or empty string, not null. Newlines are allowed in text; other control characters
are rejected. Email is normalized using the existing server email validator.
Free text is operator-review content, not automatically scrubbed; explicitly ask
users not to paste infrastructure or secrets.

```json
{
  "name": "Example Tester",
  "email": "tester@example.test",
  "privacy_version": "2026-09-20",
  "privacy_consent": true,
  "primary_cloud": "aws",
  "source_control": "github"
}
```

Success is `201`:

```json
{"status":"stored","message":"Your beta interest has been saved."}
```

Do not promise a confirmation email, invitation, wait time, or account creation.
There is no public list, lookup, or deletion route; `GET /api/beta-interest`
returns 405, not a listing. Duplicate submissions are independently stored, subject to
capacity/rate limits; do not retry automatically after an ambiguous network error.

The body limit is 8 KiB (or the configured global body limit if smaller).
Dedicated limits are 5 submissions/minute per direct network peer and
60/minute per process, counting rejected attempts. Forwarded IP headers are not
trusted. Rate buckets are in-memory abuse controls, reset on restart, and are
not persisted analytics. At 10000 stored requests the route returns
`503 submission_storage_full`; expired records count until operator cleanup.

## Analysis feedback

### GET /api/analyses/{analysis_id}/feedback

Authenticated; uses the same tenant membership and plan-retention visibility
checks as the analysis. Returns `200 {"feedback":null}` when the current user has
no unexpired feedback. Otherwise returns the object below. It never lists other
users' feedback through this tenant route. Foreign, deleted, or expired analyses
return `404 not_found`.

### PUT /api/analyses/{analysis_id}/feedback

Authenticated plus CSRF and exact Origin. All workspace roles, including viewer,
can submit their own feedback for an analysis they can see. This grants no
analysis, project, plan, or membership mutation privileges.

```json
{"useful":false,"message":"The explanation could be clearer."}
```

`useful` must be a literal JSON boolean; `message` is optional, defaults to empty,
and is bounded to 1000 characters. Unknown fields and control characters other
than newline are rejected. The body limit is 4 KiB (or the global limit if
smaller). Dedicated limits are 30 attempts/minute per direct peer and 120/minute
per process. Never send user, project, organization, time, or decision fields.

Both create and update return `200`:

```json
{
  "feedback": {
    "id": "<feedback UUID>",
    "analysis_id": "<analysis UUID>",
    "project_id": "<project UUID>",
    "organization_id": "<workspace UUID>",
    "user_id": "<current-user UUID>",
    "useful": false,
    "message": "The explanation could be clearer.",
    "created_at": 1789905600.0,
    "updated_at": 1789905600.0
  }
}
```

IDs and times come exclusively from the server. There is one row per
`(analysis_id,user_id)`. Updating preserves `id` and `created_at`; it does not
generate another submission event. Only succeeded/failed analyses accept
feedback; queued/running returns `409 analysis_not_terminal`. New rows return
`503 submission_storage_full` at 50000 stored feedback rows; existing unexpired
rows remain editable. Feedback expires 90 days after creation, even on plans
with longer history. Expired feedback is hidden from GET; updating an expired
row returns `409 feedback_expired` until operator cleanup removes it.

## Platform operator authorization

The only web operator allowlist is `BR_WEB_ADMIN_USER_IDS`: a comma-separated
list of at most 50 canonical UUIDs from persisted `users.id`. Empty/unset means
no web operators. Invalid UUIDs fail configuration validation.

Every operator request independently requires:

1. `BR_AUTH_MODE=oidc` and a currently valid persisted session.
2. That session was issued by the successful signed/validated OIDC callback.
3. The persisted user's issuer matches the configured OIDC issuer.
4. The current persisted email is nonempty and verified.
5. The persisted user UUID is in `BR_WEB_ADMIN_USER_IDS`.

`BR_ADMIN_ENABLED=true` enables the existing trusted local CLI only. It grants
no web access. Organization owner/admin/developer/viewer roles grant no platform
access. Demo sessions never qualify. Legacy sessions migrated from earlier
versions have `oidc_authenticated=false`; allowlisted operators must sign in
again. Existing OIDC state/nonce/signature/issuer/audience/expiry checks remain
in force.

`GET /api/me` adds:

```json
{"capabilities":{"platform_admin":false}}
```

Use this boolean for navigation visibility, but never as a substitute for API
authorization. A qualifying operator sees `true`. When authentication is enabled,
anonymous admin requests return `401`; signed-in nonoperators receive
`403 platform_admin_required`.
Read-only GET routes below are the entire web operator surface. No web plan
assignment, cleanup, or admin-write route exists.

## GET /api/admin/{resource}

Resources: `users`, `organizations`, `projects`, `plans`, `usage`, `failures`,
`beta-requests`, `feedback`, `events`.

Queries: `limit` defaults to 50, range 1–100; `offset` defaults to 0,
range 0–1000000. Invalid bounds return 422. `plans` and `events` return bounded
objects directly. All other resources return:

```json
{"items":[],"limit":50,"offset":0,"next_offset":null}
```

When a page is full, `next_offset` is `offset + limit`; a subsequent empty page
ends pagination. Never assume a total count or stable snapshot across concurrent
writes.

| Resource | Whitelisted row fields |
| --- | --- |
| `users` | `id`, `email_verified`, `created_at` |
| `organizations`, `usage` | `id`, `created_at`, `period`, `analyses`, `exports`, `projects`, `members`, `pending_invitations`, `limits`, `features`, `plan` |
| `projects` | `id`, `organization_id`, `archived_at`, `created_at` |
| `failures` | `id`, `organization_id`, `project_id`, `status` (always `failed`), `error` (allowlisted category), `created_at`, `completed_at` |
| `beta-requests` | `id`, all submitted fields except the consent boolean, `created_at` |
| `feedback` | the same feedback object defined above, across tenants |

`period` is UTC `YYYY-MM`; usage counts come from the existing centralized
quota implementation. User/project/workspace display names, email addresses,
Terraform, labels, report evidence, raw worker errors, source, policies, session
data, and tokens are omitted from ordinary inspection. Only `beta-requests`
and `feedback` intentionally expose bounded private review text. Protect these
views and never copy their content into telemetry, URLs, or logs.

`plans` reuses the public centralized plan catalog:

```json
{
  "payments_enabled": false,
  "mode": "commercial_beta",
  "plans": [{
    "code": "free",
    "monthly_price_usd": 0,
    "price_status": "free",
    "assignment": "signup",
    "limits": {"projects":1,"analyses_per_month":25,"retention_days":7,"members":1},
    "features": {"advanced_policy":false,"sarif":false,"team":false,"organization_policy":false,"audit":false,"json":true,"markdown":true,"payments":false,"priority_queue":false,"saml":false},
    "configurable": false
  }]
}
```

The actual array includes Free, Pro, Team, and Enterprise. Project/monthly-analysis/
history limits remain Free 1/25/7, Pro 5/500/90, Team 25/5000/365. Enterprise
customization and beta plan assignments remain trusted-CLI operations. Pro/Team
prices remain proposed; ordinary users cannot self-upgrade or activate billing.

Each successful inspection writes existing `AuditEvent` action
`operator.inspect`, the operator UUID (or `operator` for CLI), resource name,
and `{limit,offset}`. It does not copy the inspected content. Operator events
have no tenant organization, so tenant audit feeds do not expose review activity.

## Product events and bounded storage

No browser ingestion endpoint exists. The server emits this exact allowlist:

`account_created`, `workspace_created`, `project_created`, `analysis_started`,
`analysis_completed`, `analysis_failed`, `block_result`, `review_result`,
`safe_result`, `report_exported`, `github_connected`,
`beta_interest_submitted`, `feedback_submitted`.

Each row has only UUID `id`, fixed `name`, optional UUID `user_id`,
`organization_id`, `project_id`, `analysis_id`, and `created_at`. There is no
metadata payload, source, email, name, IP, fingerprint, token, or Terraform.
Beta-interest events have no identity linkage. Foreign-key references cascade
when the referenced user/tenant/project/analysis is deleted.

Terminal analysis state and events commit in one transaction. Repeated or racing
terminal writes do not duplicate events. Failed/incomplete/invalid workers never
emit `safe_result`. The frontend's nonblocking decision wording should remain
“No new modeled blocking findings detected.”

`report_exported` counts successful download/export routes, not viewing the web
report. `feedback_submitted` counts the first persisted feedback row, not edits.
Events describe activity and cannot establish customer intent or willingness to
pay. `active_workspaces` means distinct workspace UUIDs with any retained event.

`GET /api/admin/events` returns:

```json
{
  "retention_days": 90,
  "max_records": 100000,
  "counts": {
    "account_created": 0, "workspace_created": 0, "project_created": 0,
    "analysis_started": 0, "analysis_completed": 0, "analysis_failed": 0,
    "block_result": 0, "review_result": 0, "safe_result": 0,
    "report_exported": 0, "github_connected": 0,
    "beta_interest_submitted": 0, "feedback_submitted": 0
  },
  "active_workspaces": 0
}
```

The summary includes all allowlisted names, including zero counts, within the
last 90 days. There is no raw event-list endpoint. Storage is capped at 100000
events; capacity pressure evicts the oldest events, so this is a bounded activity
summary, not a durable accounting or compliance ledger.

Expired leads/feedback/events are hidden from review/summary after 90 days.
Physical time-based deletion is explicitly operator-owned; there is no scheduled
purge created by this change. The operator must run `blastradius-admin
cleanup-commercial --limit 100` regularly. Each invocation removes at most
`limit` expired rows from EACH of the three tables (at most `3 * limit` total),
with `limit` 1–1000, and audits counts only. Repeat bounded invocations to drain
a backlog. Analysis/tenant retention deletion also cascades dependent feedback
and product events. Beta-interest records have no account relationship.

The trusted CLI uses `BR_ADMIN_ENABLED=true`, the same migrated database, and:

```text
blastradius-admin inspect users --limit 100 --offset 0
blastradius-admin inspect organizations --limit 100 --offset 0
blastradius-admin inspect projects --limit 100 --offset 0
blastradius-admin inspect plans
blastradius-admin inspect usage --limit 100 --offset 0
blastradius-admin inspect failures --limit 100 --offset 0
blastradius-admin inspect beta-requests --limit 100 --offset 0
blastradius-admin inspect feedback --limit 100 --offset 0
blastradius-admin inspect events
blastradius-admin cleanup-commercial --limit 100
```

CLI list resources return a JSON array; `plans` and `events` return the object
directly. Existing CLI row shapes are preserved: users include `id`, `name`,
`email`, `email_verified`; organizations/usage include `id`, `name` plus usage;
projects include `id`, `organization_id`, `name`, `archived_at`; failures include
`id`, `organization_id`, `project_id`, `error`. Failure errors in both interfaces
use fixed categories; unknown/untrusted error strings become `analysis_failed`.
The trusted CLI retains identity fields for existing operator workflows; the web
API omits them. CLI `limit` is 1–1000 and `offset` 0–1000000.
Cleanup returns `{"removed":{"beta_interest":0,"analysis_feedback":0,"product_events":0}}`.

## Migration and isolated test helpers

Migration `0004` follows `0003`, adding `beta_interest`, `analysis_feedback`,
`product_events`, a singleton `commercial_lock`, and the session OIDC marker.
Use the existing migration entry point; no extra dependencies or secrets were
added. A downgrade removes these new records and the session marker.

Backend tests live in `tests/test_beta_api.py`. They reuse `test_server.settings`,
`demo_results`, and `backend_client`. `backend_client` runs SQLite and PostgreSQL
variants when `BR_TEST_DATABASE_URL` points at a disposable local PostgreSQL
database; each PostgreSQL case uses a separate schema.

```bash
.venv/bin/python -m pytest -o addopts='' -q tests/test_beta_api.py
.venv/bin/python -m pytest
```

For local integration tests, use the anonymous `/api/me` bootstrap for beta
interest. Use the repository's test-only `login`, `project`, `submit`, and
`terminal` helpers for feedback. `operator_client` in the new regression module
creates a synthetic verified OIDC identity, configures its persisted UUID, and
issues a server-side test session. This fixture does not prove a live provider
connection; signed OIDC callback validation is exercised with local signed JWTs
and a mocked provider in the backend suite. No test requires live AWS, live
GitHub publication, a customer identity, or private infrastructure.
