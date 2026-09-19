# FastAPI service and frontend contract

The optional backend reuses the Python analysis engine. CLI installations retain
their original three core dependencies. Install the service with `.[server]`;
install `.[server,ui,dev]` to run the full repository test suite. Python 3.12 on
Linux is the verified server platform. The worker uses Unix resource limits and
file locks; Windows server execution is not supported by this implementation.

## Start locally

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install ".[server,ui,dev]"
export BR_AUTH_MODE=demo
python -m blastradius.server.migrate
python -m uvicorn blastradius.server.app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

The default database is SQLite at `.blastradius/server.db`. Local startup also
runs migrations automatically unless `BR_AUTO_MIGRATE=false`. No credentials are
needed for public demos or explicit development demo authentication. Without
`BR_AUTH_MODE=demo`, authentication defaults to disabled and only public demos
are usable. Development demo login creates a new isolated workspace on each login;
it does not impersonate or reconnect to another demo user's data.

The ASGI entrypoint is `blastradius.server.app:app`; the factory is
`create_app(settings: Settings | None = None)`. Tests can inject a billing gateway.
The application owns its database pool, job executor, exclusive service lease,
demo cache and shutdown. Importing the module validates configuration and creates
the data directory; connecting/migrating/recovering jobs happens during lifespan.

Serve the frontend and API under the **same origin**. With Vite, proxy `/api` and
`/health` to port 8000 and set `BR_PUBLIC_URL` to the browser's frontend origin
(for example `http://localhost:5173`). Use relative URLs with cookies and do not
enable wildcard CORS. The backend does not serve the frontend build. Frontend
routes `/dashboard` and `/billing` are the configured login/billing return targets.

## Configuration

All application environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BR_ENV` | `development` | `development`, `test`, or `production` |
| `BR_DATABASE_URL` | `sqlite:///./.blastradius/server.db` | SQLite locally; `postgresql+psycopg://…` in production |
| `BR_DATA_DIR` | `.blastradius` | Private local working directory; create with owner-only access |
| `BR_STATIC_DIR` | `web/dist` | Built frontend; served when index.html exists, with fallback only for known app routes |
| `BR_PUBLIC_URL` | `http://localhost:8000` | Exact browser origin, no path, query, credentials or fragment |
| `BR_SESSION_SECRET` | Random per process outside production | At least 32 characters; required and stable in production |
| `BR_AUTH_MODE` | `disabled` | `disabled`, `demo` (development/test only), or `oidc` |
| `BR_OIDC_ISSUER` | Empty | Exact HTTPS issuer, including trailing slash if provider uses one |
| `BR_OIDC_CLIENT_ID` | Empty | OIDC web application client ID |
| `BR_OIDC_CLIENT_SECRET` | Empty | OIDC client secret |
| `BR_STRIPE_SECRET_KEY` | Empty | Optional `sk_test_…` only |
| `BR_STRIPE_WEBHOOK_SECRET` | Empty | `whsec_…`; required when billing enabled |
| `BR_STRIPE_PRICE_PRO` | Empty | Allowlisted recurring test Price ID |
| `BR_STRIPE_PRICE_TEAM` | Empty | Distinct recurring test Price ID |
| `BR_AUTO_MIGRATE` | `true` locally, `false` in production | Only literal `true` enables startup migrations |
| `BR_MAX_BODY_BYTES` | `1048576` | Entire incoming request body limit, including chunked bodies |
| `BR_MAX_FILES` | `30` | Files in each before/after map |
| `BR_MAX_RESOURCES` | `300` | Parsed Terraform resources per snapshot before graph construction |
| `BR_MAX_JOBS` | `8` | Concurrent running plus queued submissions in this process |
| `BR_WORKERS` | `2` | Concurrent isolated analysis subprocesses; not ASGI workers |
| `BR_JOB_TIMEOUT` | `30` | Worker wall-clock and CPU budget in seconds |
| `BR_SESSION_TTL` | `28800` | Application cookie and database session lifetime in seconds |
| `BR_RATE_LIMIT` | `180` | General requests per source IP per 60-second fixed window |
| `BR_AUTH_RATE_LIMIT` | `15` | Separate `/api/auth/` window |
| `BR_DEMO_RATE_LIMIT` | `60` | Separate `/api/demo…` window |

All numeric limits must be positive; workers cannot exceed job capacity. Billing
settings are all-or-none. Production startup rejects demo/disabled auth, SQLite,
plain HTTP, missing OIDC settings, a missing/short secret, and automatic migrations.
No code path accepts live Stripe secret keys. Use a secret manager; do not put
credentials into source control or command history.

Before starting production, run `python -m blastradius.server.migrate` with the
same environment as the service. This applies packaged Alembic revisions
idempotently. Readiness requires revision `0001`. Migration files are included in
the wheel; no repository checkout or Terraform fixture paths are needed.
Back up the database before migrations. Configure database TLS in the connection
URL for non-local PostgreSQL. Never use SQLite over network storage.

## Common protocol

JSON errors use `{"detail":"machine_readable_code"}`. Invalid request fields,
types, filenames or JSON return `422 {"detail":"invalid_request"}` without
reflecting uploaded content. Status codes:

* `401`: authentication required/expired.
* `403`: CSRF, origin or membership role rejected.
* `404`: missing object or no membership in its organization.
* `402`: plan quota exceeded (UI should show upgrade/usage information).
* `409`: report pending, membership/subscription conflict, or portal required.
* `413`: body or file count limit; `415`: compressed request bodies unsupported.
* `429`: rate limit or job capacity exhausted; retry with backoff.
* `502`: billing provider unavailable; `503`: auth/billing disabled or not ready.
* `500`: sanitized internal failure. Show the returned `X-Request-ID`.

Every response passing the request guard has a generated `X-Request-ID`,
`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, and `X-Frame-Options: DENY`.
Production adds HSTS and validates the Host header against `BR_PUBLIC_URL`.
The structured `blastradius.http` logger emits request ID, method, status and
duration only, without URL/query strings, headers, identity, plans or Terraform.
Configure the process log level to INFO to retain these records. Start Uvicorn
with `--no-access-log`; default access logs and reverse proxy query-string logs
can otherwise expose OIDC authorization codes. Disable query/body/header logging
in the reverse proxy, APM and error-reporting integrations too.

Timestamps are Unix seconds in UTC. IDs are opaque UUID strings. Do not infer
authorization from IDs. Membership is checked in the database for every project,
analysis, export, member-list and billing request. There is no public arbitrary
analysis route. Mutations use `X-CSRF-Token` and same-origin cookies; see
[authentication](auth.md).

## Public demos

`GET /api/demo/scenarios`:

```json
{"scenarios":[{"id":"public_ssh","title":"Public SSH exposure","root_cause":"network","change":"SSH ingress CIDR 10.0.0.0/24 -> 0.0.0.0/0","stages":["safe","risky","remediated"]}]}
```

The actual list contains `public_ssh`, `broad_iam`, and `public_bucket`.

`GET /api/demo/{scenario_id}?stage=safe|risky|remediated` returns the **unwrapped
report object** below. Default stage is `risky`. All nine results are computed at
startup using the real engine in constrained workers over the bundled, generated
copies of committed Terraform fixtures. Requests only read this bounded cache;
they cannot specify HCL, paths or arbitrary jobs, and persist no user data.
To update the fixture bundle after reviewed example changes:
`python -m blastradius.server.bundle_demos`.

Safe compares the baseline with itself; risky compares baseline to changed
fixture; remediated compares risky with the supported generated patch (SSH/S3),
or the reviewed least-privilege IAM baseline. The IAM engine has no automatic IAM
patch; `demo.remediation_kind` is `reviewed_fixture` for that case. IAM safe and
remediated scores are 85, because its baseline deliberately contains exposure;
both have no new critical path. SSH/S3 safe/remediated scores are 100.
Use `passed` and the evidence rather than assuming every safe score is 100.

## Authentication and organizations

`GET /api/me` is public and creates an anonymous CSRF session when needed:

```json
{
  "authenticated":false,
  "user":null,
  "organizations":[],
  "csrf_token":"opaque-value",
  "auth":{"enabled":true,"mode":"demo","public_url":"http://localhost:8000","login_url":null},
  "billing":{"enabled":false,"test_mode":true}
}
```

After authentication, `user` is `{id,name,email}` and each organization is
`{id,name,role,plan,usage}`. `usage` is
`{period:"YYYY-MM",analyses,limits:{analyses_per_month,projects,members},plan}`.

* `GET /api/auth/login`: browser redirect to OIDC provider when enabled.
* `GET /api/auth/callback`: provider redirect target; success redirects to
  `${BR_PUBLIC_URL}/dashboard` with a new application session.
* `POST /api/auth/demo`: explicit non-production demo login, CSRF required.
  Returns `{"authenticated":true}`. It accepts no identity selection.
* `POST /api/auth/logout`: CSRF required; invalidates database session and clears
  cookie. Returns `{"authenticated":false}`.

Fetch `/api/me` again after login because both session and CSRF token rotate.
`auth.public_url` is the configured canonical browser origin. The UI checks it
before offering workspace mutations. The server independently enforces Origin,
CSRF, authentication and membership on every protected operation.

`POST /api/organizations {"name":"Platform"}` creates a new free organization
with the authenticated caller as its only owner. Limit: five owned organizations
per user, including the initial workspace. There is no endpoint to claim another
organization, set a plan, grant owner rights or join by an unverified email.

Owner-only membership management:

* `GET /api/organizations/{id}/members` → `{"members":[{"user_id","role"}]}`.
* `POST /api/organizations/{id}/members {"user_id":"existing-user-id","role":"member|viewer"}`
  → `201 {user_id,role}`. Target must already be a user. Enforces member quota.
  The owner must obtain the target's user ID directly; there is no public user
  enumeration or invitation-email service.
* `DELETE /api/organizations/{id}/members/{user_id}` → `204`. Cannot remove owner.
  To change a non-owner role, remove and add again.

Owners can manage members, billing and project deletion. Members can create
projects, submit/delete analyses and read reports. Viewers can read only.
All roles can read their own `/api/me` organization/usage list.

## Projects and analyses

`GET /api/projects?organization_id={optional}&limit=50&offset=0` returns
`{"projects":[{id,organization_id,name,created_at}]}` for authorized organizations.
`limit` is 1–100. Newest first with ID tie-breaker.

`POST /api/projects {"organization_id":"uuid","name":"Infrastructure"}`
returns `201 {id,organization_id,name,created_at}`. It never clones repositories.
Use the project name to associate an upload with a repository or infrastructure
scope. The current service accepts content uploads, not repository connections.

`DELETE /api/projects/{id}` is owner-only and returns `204`. It cascades deletion
of all stored analyses/reports for the project. Jobs already executing may finish
their bounded work but cannot recreate deleted records.

`POST /api/analyses` accepts exactly one input mode:

```json
{
  "project_id":"uuid",
  "base_label":"main@abc123",
  "candidate_label":"feature@def456",
  "before_files":{"main.tf":"resource \"aws_s3_bucket\" \"data\" { bucket = \"example\" }\n"},
  "after_files":{"main.tf":"resource \"aws_s3_bucket\" \"data\" { bucket = \"example\" }\n"}
}
```

Or `{project_id,base_label?,candidate_label?,plan:{…terraform show -json output…}}`.
Labels default to `baseline` and `candidate`. Files must have simple ASCII `.tf`
basenames, no slashes, `..`, NUL bytes, paths or duplicate resource addresses.
Nested directories, `.tf.json`, ZIP archives, URLs, host paths, repository
credentials and execution commands are unsupported. Additional fields are
rejected. Terraform, providers, external data sources and shell commands are
never executed. Resource bounds are applied after parsing and before graph work;
parser work itself is bounded by process CPU/memory/wall time.

Submission returns `202` immediately after persistence:

```json
{
  "id":"uuid","project_id":"uuid","organization_id":"uuid",
  "base_label":"main@abc123","candidate_label":"feature@def456",
  "created_at":1780000000.0,"started_at":null,"completed_at":null,
  "status":"queued","error":null,"result":null
}
```

`GET /api/analyses/{id}` returns the same shape. Poll with backoff (for example
one second initially); `status` transitions `queued → running → succeeded|failed`.
Use a loading state for the first two. `result` is the report on success.
`error` on failure is a safe code such as `invalid_analysis_input`,
`analysis_timeout`, `resource_limit_exceeded`, `analysis_failed`, `worker_failed`,
`result_too_large`, or `server_restarted`; raw parser exceptions are not exposed.
The result is stored as JSON with findings, paths and all report formats, not as
cross-tenant filesystem paths.

`GET /api/projects/{id}/analyses?limit=50&offset=0` returns `{"analyses":[…]}`.
History entries omit `result`; completed entries include
`summary:{decision,score,verdict}`. Ordering and bounds match project listing.

`DELETE /api/analyses/{id}` returns `204` and deletes the report. Deletion does not
refund submitted analysis quota. Deleting a queued job prevents execution if it
has not started; deleting a running job removes persistence immediately, while
the subprocess may run until its normal timeout.

## Stable report version 1

Both demos and successful analyses share this shape:

* `schema_version: 1`, `decision` (engine display string), `passed` (boolean),
  `analysis_complete` (boolean within the documented static model),
  `headline`, `verdict`, `score:{before,after,delta}`.
* Decisions include `SAFE TO MERGE`, `BLOCK CHANGE`, and `REVIEW REQUIRED`.
  The engine is the source of truth; use `passed` for acceptance and treat unknown
  future display strings conservatively.
* `before` and `after`: `{label,score,risk_level,score_breakdown,exposed_resources,
  reachable_sensitive,attack_paths,graph,complete,paths_truncated,path_work}`.
* `graph.nodes`: `{id,name,type,sensitive,risk}`; stable IDs are resource addresses,
  synthetic sensitive-data addresses or `INTERNET`.
* `graph.edges`: `{source,target,relationship,reason,evidence,severity,
  terraform_resource,metadata,confidence,category,source_file,remediation}`.
  Do not infer real exploitability from an edge.
* Paths: `{id,nodes,labels,edges,severity,explanation,reaches_sensitive}`.
* Delta lists: `new_attack_paths`, `removed_attack_paths`, `new_critical_paths`,
  `removed_critical_paths`, `newly_exposed`, `newly_reachable_sensitive`,
  `new_nodes`, `removed_nodes`, `new_edges`, `removed_edges`.
* `findings`: `{label,detail,delta,severity}`.
* `responsible_change`: engine summary; `responsible_changes`: `{file,diff}` for
  changed source files. Plans have no source patches/diffs.
* `diagnostics`: `{code,severity,message}` including unsupported model items.
  Engine diagnostics additionally include `{phase,resource,attribute,source_file,
  blocks_analysis}`; resource/attribute/file may be empty when unknown.
  `limitations`: string list.
* `remediation`: `{recommendations,patched_files,diff,can_autofix}`;
  recommendations contain `{title,detail,current,recommended,severity,resource}`.
  Patched files are a name-to-content map of supported edits only. Merge them
  into the original candidate files and submit a new analysis; never apply edits
  automatically to real infrastructure.
* `reports:{markdown,sarif}`: existing engine report and SARIF 2.1.0 payload.
* Public demos additionally contain
  `demo:{scenario_id,stage,remediation_kind,note}`.

These coverage/evidence fields are additive within schema version 1. Older stored
reports may omit them. A missing coverage field is not evidence of completeness.
Incomplete analysis never receives `SAFE TO MERGE`; the frontend exposes the
diagnostics rather than substituting a safe result.

`GET /api/analyses/{id}/report?format=web|json|markdown|sarif` requires membership
and a succeeded job, otherwise `409 report_not_ready`. Default `web` returns the
report JSON inline. `json`, `markdown`, and `sarif` add fixed attachment filenames
(`report.json`, `report.md`, `report.sarif`). Reports can contain user-supplied
Terraform text: escape it in the frontend and sanitize rendered Markdown. Never
inject report/graph labels as HTML.

## Quotas, operations and limitations

| Plan | Analyses/month | Projects | Members |
| --- | ---: | ---: | ---: |
| Free | 20 | 3 | 1 |
| Pro | 500 | 20 | 5 |
| Team | 5000 | 100 | 25 |

Counters use UTC calendar months and increment transactionally when a job is
accepted, including jobs that subsequently fail. Rejected inputs/capacity requests
do not consume quota. PostgreSQL locks the organization row; SQLite serializes
writes with `BEGIN IMMEDIATE`. Downgrading does not delete existing data or kick
out members; creating more objects is blocked until usage is below quota.
Only verified provider events change plans through the HTTP API.

`GET /health/live` reports process liveness; `GET /health/ready` checks database
migration revision and the nine precomputed demo results. Both are rate-limited.
Development OpenAPI UI is `/api/docs`, specification `/api/openapi.json`; the UI
is disabled in production.

Run exactly **one ASGI process per database**. An exclusive PostgreSQL advisory
lock or SQLite file lock rejects a second process. `BR_WORKERS` controls analysis
subprocess concurrency inside that service. There is no distributed queue, retry
scheduler, HA deployment, or horizontal scaling. Restart marks queued/running
jobs failed and cleans abandoned job directories. Graceful shutdown drains accepted
jobs; allow a shutdown budget of `ceil(BR_MAX_JOBS / BR_WORKERS) * BR_JOB_TIMEOUT`
plus overhead. A database connection loss should restart the service rather than
attempting a rolling failover. Do not share `BR_DATA_DIR` between unrelated services.

Each job uses a private random directory, isolated Python (`-I`), a minimal
environment without application/provider secrets, 768 MiB address-space cap,
CPU/wall time limits, disabled core dumps, 16 MiB file-size cap and 8 MiB result
cap. Workspaces are removed on success/failure/timeout. These are resource and
input controls, **not an OS security sandbox against a parser zero-day**. Production
should run as a non-root account/container with read-only code, no cloud instance
credentials, restricted egress, private temporary storage and database access
limited to this service.

TLS termination, trusted proxy configuration, database backups, encryption at
rest, monitoring, user/organization offboarding, retention policies, identity
provider deployment and operational incident handling remain operator work.
Results include source diffs and patched files; do not submit secrets. Database
and backups contain that sensitive content until deleted/expired by your policy.
HTTP deletion does not purge external backups. Sessions expire automatically;
analysis, demo-user, usage and webhook-event retention are not scheduled.
Rate limits are per-process/per-source-IP fixed windows. Configure Uvicorn to
trust forwarded addresses only from the actual trusted proxy; a shared proxy IP
otherwise shares a bucket. Add edge limits before exposing the service.

The simplified AWS model does not cover every Terraform construct, network
control or policy condition. A path is not proof of exploitation; no path is not
proof of safety. Source repositories are not fetched or executed. There is no
GitHub App, invitation service, password store, durable distributed queue,
payment collection or commercial SLA in this backend. Existing GitHub Actions
remains the repository integration. A future GitHub App would require signed
webhooks, installation-to-organization binding, least-privilege installation
tokens, a durable queue and explicit per-repository authorization before ingest.

## Verification commands

```bash
python -m pytest -o addopts='' -q
python -m ruff check blastradius/server tests/test_server.py
python -m mypy --check-untyped-defs --follow-imports=silent --ignore-missing-imports blastradius/server
python -m pip wheel . --no-deps --wheel-dir dist
```

The optional PostgreSQL test uses `BR_TEST_DATABASE_URL` pointing at a dedicated
disposable database; it creates persistent test records. Do not point it at a
production or shared application database. Without that test-only variable the
PostgreSQL integration case is explicitly skipped. Stripe tests use the official
SDK's real signature verifier with locally signed mock events; OIDC tests use
RSA-signed tokens and Authlib with mocked HTTP endpoints. These tests do not
constitute a live-provider or end-to-end browser verification.
