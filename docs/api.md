# Backend API contract

FastAPI app: `blastradius.server.app:app`; factory: `create_app(settings=None)`.
Run one API process with the existing in-memory bounded job executor. OpenAPI is
at `/api/openapi.json`; development docs at `/api/docs`. `/health/live` is process
liveness; `/health/ready` checks the actual packaged Alembic head and nine loaded
real-engine demo results. There are no fake progress stages.

## Configuration and migrations

Use `.env.example`, [authentication](auth.md) and `Settings` in
`blastradius/server/config.py`. Current settings include `BR_ENV`, `BR_PUBLIC_URL`,
`BR_AUTH_MODE` (`demo`, `oidc`, `disabled`), `BR_DATABASE_URL`, `BR_DATA_DIR`,
`BR_STATIC_DIR`, `BR_AUTO_MIGRATE`, `BR_SESSION_SECRET`, `BR_SESSION_TTL`,
`BR_OIDC_ISSUER`, `BR_OIDC_CLIENT_ID`, `BR_OIDC_CLIENT_SECRET`, body/file/resource/
job/worker/rate limits and the operator-only `BR_ADMIN_ENABLED`. Unknown old
`BR_STRIPE_*` settings have no effect. No payment SDK or payment API remains.

```bash
python -m blastradius.server.migrate
python -m uvicorn blastradius.server.app:app --host 127.0.0.1 --port 8000 \
  --workers 1 --no-access-log --no-proxy-headers
```

Migrations support fresh databases and upgrading existing revision `0001` to
`0002`. Readiness follows Alembic's actual head. Migration Python files and the
autogeneration template ship in wheels. Back up and stop API processes before
schema migration. Reverting 0002 requires restoring the pre-upgrade backup;
lossy schema downgrade is explicitly rejected. Legacy `member` becomes
`developer`; existing roles/data/results are preserved. Existing users must
reauthenticate through verified OIDC to establish verified-email status.

## Authentication and errors

`GET /api/me` creates an anonymous CSRF session if necessary. Authenticated
responses include `user {id,name,email,email_verified,created_at}`,
`organizations [{id,name,role,plan,usage}]`, `csrf_token`, `auth`, and
`billing {enabled:false,mode:"commercial_beta"}`. Mutations require the session
cookie and `X-CSRF-Token`; optional Origin must match `BR_PUBLIC_URL`, and
cross-site browser mutations are rejected. Never put CSRF tokens in URLs.

* `POST /api/auth/demo`: disposable development identity, disabled in production.
* `GET /api/auth/login`, `/api/auth/callback`: OIDC state/nonce/PKCE/signed claims.
* `POST /api/auth/logout`: revoke current session and remove cookie.
* `GET /api/account/sessions`: `{sessions:[{id,created_at,expires_at,current}]}`.
  Migrated sessions may have `created_at:null`; session/token hashes are never exposed.
* `DELETE /api/account/sessions/{id}` or `/api/account/sessions`: revoke one/all
  of the current user's sessions, including the current one; return 204.

Errors are `{"detail":"stable_code"}`: 401 unauthenticated; 403 role/CSRF/origin;
404 absent, expired or foreign-tenant resource; 402 quota/entitlement; 409 last
owner, archived project, unavailable report or invitation conflict; 413 input
size/resource limit; 422 invalid strict request; 429 capacity/rate limit; 503
disabled auth/not ready; 500 sanitized unexpected error. Validation responses
never echo source/token values. Every response has `X-Request-ID` and no-store.

## Catalog, workspaces, usage and invitations

* `GET /api/plans` (public): `{payments_enabled:false,mode:"commercial_beta",plans}`.
  Each plan has `code`, `monthly_price_usd`, `price_status`, `assignment`, `limits`,
  `features` and `configurable`. See [plans](billing.md).
* `POST /api/organizations {name}` → 201 `{id,name,role:"owner",plan:"free"}`.
  Maximum five owned workspaces per user. Names are trimmed, nonempty, ≤100 chars,
  without control characters.
* `PATCH /api/organizations/{id} {name}` → `{id,name,plan}`; owner/admin.
* `DELETE /api/organizations/{id}` → 204; owner only, cascading deletion.
* `GET /api/organizations/{id}/usage` → `{period,analyses,exports,projects,members,
  pending_invitations,limits,features,plan}`; any member.
* `GET /api/organizations/{id}/billing` → `{enabled:false,mode:"commercial_beta",
  plan,usage}`; owner only. Subscription fields are inert
  legacy placeholders. Checkout/portal/webhook routes are removed.
* `GET /api/organizations/{id}/members` → `{members:[{user_id,role,name,email}]}`;
  owner/admin. Public arbitrary user-ID member creation was removed.
* `PATCH /api/organizations/{id}/members/{user_id} {role}` → `{user_id,role}`.
  Team/Enterprise only. Owner/admin, but only owners can grant or modify owners.
* `DELETE /api/organizations/{id}/members/{user_id}` → 204; owner/admin subject
  to owner protection. The last owner cannot be removed or demoted.
* `POST /api/organizations/{id}/invitations {email,role?}` → 201 invitation
  metadata plus one-time `invitation_url` and `delivery:"manual"`; Team/Enterprise
  owner/admin. Role defaults to `developer`; only admin/developer/viewer allowed.
* `GET /api/organizations/{id}/invitations?limit=50&offset=0` → `{invitations}`;
  owner/admin, no tokens or links in subsequent reads.
* `DELETE /api/organizations/{id}/invitations/{invite_id}` → 204; owner/admin.
* `POST /api/invitations/accept {token}` → `{organization_id,role}`; authenticated
  verified matching email only. Tokens are 256-bit, hashed, expire after seven
  days, revocable and single-use. The creator manually delivers the link. The
  browser reads the fragment `#token=...` and sends only a POST body; it must
  clear the fragment and must not send tokens to analytics. Demo identities
  cannot accept invitations even if a local row is modified.
* `GET /api/organizations/{id}/audit?limit=50&offset=0` → `{events:[{id,actor,
  action,target_id,details,created_at}]}`; Team/Enterprise owner/admin.

Invite creation never reports whether an email already has an account. Invalid,
wrong-email, unverified, expired, revoked, consumed or already-member acceptance
returns the same 404 `invitation_unavailable`. See [organizations](organizations.md).

## Projects and policy

* `GET /api/projects?organization_id=&limit=50&offset=0` → `{projects}`; member
  workspaces only. Includes archives. `GET /api/projects/{id}` returns one project.
* `POST /api/projects` → 201 project; owner/admin. Body: `organization_id`, `name`,
  optional `description` (≤2000), `repository` (`owner/name` or empty),
  `repository_provider` (`manual` default or `github`), `default_branch` (`main`),
  `environment` (empty), `terraform_root` (`.`). Repository metadata does not
  connect to GitHub or execute an import. No credential-bearing URLs accepted.
* `PATCH /api/projects/{id}` → updated values; same fields except org ID, plus
  `archived` (default false). This is a complete settings form: send all values
  to preserve them. `name` is required. `archived_at` records archival; restoring
  checks available active-project slots.
* `DELETE /api/projects/{id}` → 204; owner/admin.
* `GET /api/projects/{id}/policy` → `{policy,version,effective}`.
* `PUT /api/projects/{id}/policy` → `{policy,version}`; owner/admin with advanced
  policy entitlement. `DELETE` clears it (204).
* `GET /api/organizations/{id}/policy` → `{policy,version}`.
* `PUT /api/organizations/{id}/policy` → `{policy,version}`; Team/Enterprise
  owner/admin. `DELETE` clears it (204).

Read policies as any member. Clearing a policy is permitted after downgrade.
Policy precedence, exact supported rules, versioning and snapshots: [policy](policy.md).

## Analyses and evidence

`POST /api/analyses` → 202 analysis. Owner/admin/developer; archived projects
return 409. Body:

```json
{
  "project_id":"uuid",
  "base_label":"baseline",
  "candidate_label":"candidate",
  "base_ref":"main",
  "candidate_ref":"feature/network",
  "base_sha":null,
  "candidate_sha":null,
  "before_files":{"main.tf":"resource \"aws_s3_bucket\" \"example\" {}"},
  "after_files":{"main.tf":"resource \"aws_s3_bucket\" \"example\" {}"}
}
```

Use either nonempty before/after `.tf` maps or `plan` (Terraform show JSON).
Plan is data, not executed. File names must be simple `.tf` basenames; no archives
or traversal. Refs are optional ≤120 chars; SHA strings are lowercase 40/64 hex.
Client metadata is descriptive, not authenticated Git provenance. No policy
field is accepted from analysis input.

`GET /api/analyses/{id}` returns base/candidate labels, refs/SHAs, input_type
(`hcl|plan|null`), timestamps, status (`queued|running|succeeded|failed`), sanitized
error, decision, scores/risk, critical paths added/removed, policy_snapshot,
normalized_version and `result`. Result remains engine JSON schema 1 (decision,
graph, paths, score, evidence, diagnostics, remediation and reports). Free
workspace result JSON omits nested SARIF; Pro+ includes it. Legacy records retain
their JSON with null new summaries/snapshot/version; no evidence is fabricated.
Succeeded means the analysis ran, **not** that the gate passed.

* `GET /api/projects/{id}/analyses` → `{analyses,total,limit,offset}`. Optional
  `status`, `decision` (exact engine value), `input_type`, `branch` (candidate_ref),
  `since`/`until` (Unix seconds). Default limit 50, max 100. History uses summary
  without full result. Ordered by creation descending and ID.
* `DELETE /api/analyses/{id}` → 204; owner/admin/developer; usage is not refunded.
* `GET /api/analyses/{id}/findings?severity=&limit=50&offset=0` →
  `{normalized_version,findings:[{id,type,severity,title,description,evidence}]}`.
* `GET /api/analyses/{id}/paths?phase=after&limit=50&offset=0` →
  `{normalized_version,paths:[{id,key,phase,severity,nodes,labels,explanation,
  reaches_sensitive,hops}]}`. Phase is before/after; hops contain position and
  existing engine edge evidence.
* `GET /api/analyses/{id}/artifacts` → `{normalized_version,artifacts:[{id,format,
  media_type,created_at}]}`; only entitled formats are listed.
* `GET /api/analyses/{id}/artifacts/{artifact_id}` → serialized report; artifact
  must belong to that authorized, nonexpired analysis.
* `GET /api/analyses/{id}/report?format=web|json|markdown|sarif` → report.
  Pending/failed jobs return 409. SARIF requires entitlement. JSON/web never
  provide a nested SARIF bypass. Exports check current retention and entitlements.

Findings/paths/hops/artifacts are committed with results and summary/status in one
worker completion transaction. Legacy normalized lists are empty with a null
version. Deleting analyses cascades all children.

## Public real-engine demo

`GET /api/demo/scenarios` and `GET /api/demo/{scenario_id}?stage=safe|risky|remediated`
remain public synthetic samples; all formats including SARIF remain available.
They do not create tenant analyses or consume usage. Supported scenarios are
returned by the catalog. They use the same isolated engine and resource limits.

## Execution boundary and verification

Workers use isolated Python (`-I`), minimal environment, unique scratch space,
timeouts and memory/CPU/file limits. No Terraform/provider/Git candidate code is
executed. Logs contain request/analysis/workspace/project ID, duration and
outcome; no source, cookies or tokens. Restart fails abandoned work honestly
(`server_restarted`). The queue and rate limiter are in-process, single replica.

Run `python -m pytest`, `make lint typecheck docs`, and wheel install checks.
`BR_TEST_DATABASE_URL` enables a disposable PostgreSQL integration test.
Mocked signed OIDC tests do not verify an external provider deployment.
See [retention](data-lifecycle.md), [operations](operations.md), and [auth](auth.md).
