# Authenticated SaaS readiness

Assessment: **2026-09-20 — INTERNAL ALPHA**. Private/public beta promotion remains
blocked. Local shell verification of the integrated commercial-beta implementation
passed; final browser/responsive acceptance on this implementation is **pending**
and owned by the parent session. This is not a security certification.

Integrated implementation revision: `5be27d0` on
`devin/1789903228-saas-verification`; subsequent changes to this assessment and
the container evidence document do not change runtime code.
The existing [draft PR #3](https://github.com/Mighiana/BlastRadius/pull/3) remains
unmerged. PR #2 was previously merged outside this integration stage. No new PR,
merge, force push, provider provisioning, payment activation or public deployment
was performed.

Prior browser revision: `c9253b9340a35ea61e0ed17262b9113293d84e64`.
Its retained backend failure/role evidence from `9b0b5a6` used identical backend
code **at that time**. The new beta, feedback, events, operator and container
changes require acceptance again; prior browser evidence below is historical.

## Final status by area

| Area | Integrated status and evidence boundary |
| --- | --- |
| Technical | Python 3.12.14 / Node 24.19.0 shell validation passes; single-process bounded queue remains the supported architecture |
| Authenticated flow | SQLite/PostgreSQL API and signed mocked OIDC regressions pass; final integrated browser flow and hosted identity remain pending |
| PostgreSQL | Disposable PostgreSQL 16.15 acceptance passes; fresh/upgrade/idempotent migrations reach `0004`; logical recovery and commercial retention verified |
| RBAC / tenant isolation | Authorization matrix and beta/feedback/operator regressions pass in full backend suite; workspace ownership does not grant platform access |
| Fail-closed analysis | Engine/worker/restart regressions pass; errors/incomplete results never become SAFE; SAFE means “No new modeled blocking findings detected.” |
| Container security | Promotion blocked: database 1 CRITICAL / 54 HIGH; app reports zero but retains assessed zlib MEDIUM risk; [full inventory](container-security.md) |
| CI | First integrated push `5be27d0`: 2 passed, 4 pending, 1 skipped when inspected. Final documentation push requires its own CI result; local promotion check is deliberately red |
| Responsive / browser | **0 browser cases executed in this integration stage**; 29 collected (19 existing + 10 new). Six requested widths and new beta/feedback/operator flows await parent acceptance |
| Onboarding | Demo/HCL/plan choices, result guidance, beta/pricing/trust wording implemented; 141 frontend unit tests pass; browser usability and time-to-value not measured here |
| Beta access | Persisted consent-based intake, strict schema, exact Origin/CSRF, bounded storage/rate limits and privacy notice verified by API/unit tests; no invitation/email promise |
| Feedback | Authenticated terminal-analysis feedback derives tenant/user context server-side; isolation, persistence, expiry and operator review verified by shell tests |
| First-party product metrics | Fixed event names and UUID references only; no browser ingestion or fingerprints; bounded 90-day activity summaries, not evidence of customer intent |
| Admin | Read-only operator API/UI; web access requires validated OIDC session, verified email/issuer and UUID allowlist; trusted CLI remains separate; hosted operator acceptance pending |
| Pricing / entitlement | Central Free 1/25/7, Pro 5/500/90, Team 25/5000/365 project/monthly-analysis/history limits; Enterprise custom; proposed prices and checkout disabled; manual audited plan grants |
| GitHub Actions | Local event/base-policy/immutable-SHA/publication regressions pass; historical hosted evidence retained below; current strict REVIEW/fork behavior needs authorized hosted acceptance |
| GitHub App | Signed-webhook/provider mocks pass; real installation/check/comment/redelivery acceptance requires owner configuration |
| OIDC | Signed callback/session validation tested locally; legacy operator sessions must reauthenticate after `0004`; selected external IdP remains unverified |
| Deployment | Hardened images and provider-neutral runbooks prepared; nothing hosted or provisioned |
| Backups / restore | Disposable logical dump/restore matches schema/data, preserves source/usage and verifies bounded deletion/cascades; encrypted off-host backup/PITR and disaster recovery remain unverified |
| Monitoring | Health/readiness, bounded logs and alert/scheduling runbooks exist; delivery of real alarms and deployed schedules not verified |
| Legal / trust | Explicit static-analysis/model/retention boundaries and synthetic customer materials exist; legal entity, contacts, terms/subprocessors and beta approval remain owner work |
| Test counts | 1,140 backend/engine; 42 release with opt-in Docker drill; 141 frontend; 5 additional isolated-wheel CLI cases; 9 container worker cases; 0 new browser executions |
| Commits pushed / PR #3 | Contributor integration and recovery/docs glue pushed through `5be27d0`; [delivery branch](https://github.com/Mighiana/BlastRadius/tree/devin/1789903228-saas-verification) carries the later evidence-only commit. PR #3 remains draft/unmerged |

## IMPLEMENTED AND VERIFIED

### Measured verification

These are integrated shell results at `5be27d0`, not the historical browser run.

| Check | Result and scope |
| --- | --- |
| Backend/engine/PostgreSQL | **1,140 passed, zero skipped** in 166.61s using `.venv/bin/python -m pytest` through `make check` with disposable PostgreSQL 16.15; SQLite/PostgreSQL parameterized variants are included, not every test duplicated |
| Release | Default **41 passed, 1 opt-in skip**; explicit `BR_RUN_OPS_DRILL=1` run **42 passed, zero skipped** including real PostgreSQL recovery |
| Frontend | **141 tests across 10 files**, ESLint/TypeScript/build passed through `make frontend` |
| Security | Full suite includes tenant/IDOR/RBAC/CSRF/Origin, untrusted input, upload/resource limits, OIDC/session/invitation, worker, GitHub webhook/publication and commercial-operator regressions; no live attack or provider write |
| Python/docs | Ruff and mypy passed; links validated in **48 Markdown files**; shell syntax and Docker build checks passed |
| Engine/CLI/package | Wheel/content check and fresh isolated wheel installation passed; five explicit `python -I` CLI cases exit **1/0/0/1/2**; canonical demo script and nine customer-sample regressions pass (the latter are included in the 1,140) |
| Migrations | Fresh and upgrade-from-`0001` to `0004`, repeated migration, existing sentinel preservation and readiness passed; packaged commercial singleton present |
| Container | Both images built; read-only/nonroot UID, dropped capabilities, package metadata, missing build tools, entrypoint exit 2, psycopg binary, nine installed-worker cases, migration/restore, health and static asset checks passed |
| Audits | Python/npm dependency audits and repository/both-image secret checks passed. Trivy image ledger retains all 428 baseline + 245 rebuilt rows, with 673 unique row IDs and one separate carried-forward residual |
| Promotion | Unchanged `make promotion-check` **failed as required**, make exit 2; no HIGH/CRITICAL exemption, suppression or severity reduction |
| Browser collection | `playwright test --list` collected **29** cases; no browser execution or new responsiveness claim |

Python emits one Starlette/httpx TestClient deprecation warning. It is not
suppressed. The [integration evidence bundle](https://app.devin.ai/attachments/96cb7ebd-c2e4-48a7-b4f5-b7f9e1bed6e5/integration-evidence.tar.gz)
contains shell/build/audit logs, raw scans, ledger and restore JSON; database dumps,
environment files and installed virtual environments are excluded.
Reproduce with Python 3.12 and Node 24.19.0:

```bash
BR_TEST_DATABASE_URL=<disposable-postgresql-url> make check
BR_RUN_OPS_DRILL=1 .venv/bin/python -m pytest -o addopts='' -q scripts/test_release_*.py
make frontend
make audit wheel
make secret-audit container-audit
bash scripts/verify-containers.sh
make promotion-check  # expected to fail until image HIGH/CRITICAL findings are fixed
```

### Integrated recovery and commercial contracts

The [machine-readable recovery evidence](https://app.devin.ai/attachments/33eb96c3-6a5e-4647-ab40-519c65a2e59c/evidence.json)
records migration `0004`, schema/data equality, unchanged source, refusal of a
nonempty restore target, runtime-role restrictions, integrity checks, health
200/200, analysis deletion cascades and preserved usage. It took **7.811 seconds**
on this disposable local fixture, not a production RTO. Commercial cleanup with
`--limit 1` deleted one expired lead/feedback/event per call twice, then zero
from each table; one current row per table remained and all calls were audited.
The disposable container was removed after the drill. No customer data was used.

Migration `0004` adds `beta_interest`, `analysis_feedback`, `product_events`,
`commercial_lock` and `sessions.oidc_authenticated`. Configure
`BR_WEB_ADMIN_USER_IDS` separately from CLI-only `BR_ADMIN_ENABLED`. Existing
operator sessions require fresh OIDC authentication. Expired data is hidden
immediately; schedule both bounded `cleanup` and `cleanup-commercial` jobs for
physical deletion. See the exact [operator/migration procedure](owner-setup.md#web-operator-and-commercial-data-setup)
and [API contract](beta-api.md). No new secrets/dependencies, web admin writes,
email transport, payment activation or automatic invitations were added.

Customer material includes [reproducible synthetic reports](customer-samples.md),
[three demo scripts](demo-sales.md), a [beta guide](beta-guide.md),
[neutral interview questions](customer-interview.md) and
[persona hypotheses](buyer-personas.md). CLI-produced reports are tested for
reproduction; these are not customer testimonials or willingness-to-pay evidence.

### Historical pre-integration verification

The following counts and browser details belong to `c9253b9` and its explicitly
retained evidence. They are not added to the integrated test totals above.

| Check | Result and scope |
| --- | --- |
| Backend/engine | **1,010 tests passed**, zero skipped, with `BR_TEST_DATABASE_URL` pointing to disposable PostgreSQL 16.15; includes SQLite and PostgreSQL parameterized cases, not every test repeated on both engines |
| Release tooling | **23 tests passed** |
| Frontend | **94 unit tests passed** across nine files; ESLint, TypeScript and production build passed |
| Repository browser suite | **19/19 distinct cases passed**, zero skipped, unexpected or flaky; earlier runs are not added to this count |
| Authenticated responsive | **72/72 width × surface checks** at 320, 375, 430, 768, 1024 and 1440px; no page/panel overflow, measured visible controls at least 44 × 44px |
| Browser role/security checks | Four real local OIDC identities; **82/82 role API expectations**, **22/22 tenant/CSRF/anonymous expectations**, **7/7 failure-input cases** |
| Python quality | Ruff, mypy and documentation link checks passed |
| Packaging | Wheel build and packaged-module/migration checks passed; application and database container builds passed |
| Dependency audits | `pip-audit` and npm audit found no known dependency vulnerabilities; container OS findings remain blocking below |
| Fresh install | Clean isolated installation passed on the preceding productionization revision: dependencies → frontend build → migration → startup → sign-in → workspace/project → analysis. Current revision was rebuilt/reinstalled in the isolated OIDC/PostgreSQL acceptance environment, not installed again using untouched default ports |

Reproduce shell checks with Python 3.12 and Node 24.19.0:

```bash
BR_TEST_DATABASE_URL=<disposable-postgresql-url> make check
make frontend
make audit
make wheel
```

Browser setup and prior package/container scope are in
[release integration](release-integration.md). The browser harness adapted
API/frontend ports to preserve existing services; OIDC/PostgreSQL acceptance
used an explicit private environment file. This is not a claim that the default
demo profile supplies stable OIDC identity.

### Local authenticated browser acceptance

1. Open the trusted local app in Devin Desktop; sign in through a disposable
   HTTPS OIDC provider with signed RS256 tokens, stable subject, state/nonce and
   PKCE. TLS and application Origin validation remain enabled.
2. Create a new workspace, confirm selection and owner membership, create a
   project, and upload supported baseline/candidate HCL.
3. Submit a real predecessor and target under a temporarily bounded one-worker
   configuration. Observe **QUEUED → RUNNING → succeeded**; `succeeded` is the
   persisted completed-state name. No mocked progress or production sleeps.
4. Inspect **BLOCK**, score **100 → 20**, risk **LOW → CRITICAL**, one new critical
   path, newly sensitive/exposed resources, responsible SSH change, before/after
   attack graph, node/per-hop evidence, remediation and coverage diagnostics.
5. Download real Free JSON/Markdown and remediation patch. Confirm Free SARIF
   gating; grant Team through the operator CLI and download SARIF 2.1.0.
6. Navigate to Settings and History, reopen and reload the analysis. Sign out
   and verify authenticated reads return 401, then sign in with the same OIDC
   subject. Restart the backend and sign in again.
7. Confirm unchanged user/workspace/project/analysis/artifact IDs, owner
   permission and **byte-identical post-Team JSON/Markdown/SARIF**. Free→Team
   legitimately adds SARIF; comparisons use the post-grant baseline.

The worker setting was restored to two, readiness returned 200, injected fault
triggers were removed, and installed worker/app/jobs matched current source.
The user's original local demo identity/database was preserved.

Recordings, full screenshots, the detailed acceptance report and sanitized
evidence bundle are delivered in the
[session](https://app.devin.ai/sessions/43f88b66eb154704bcc13f7cabb8d478).
The bundle separates current evidence from retained backend-identical evidence.
Screenshots and measured results also accompany PR #3.

### Responsive regression

Actual accepted invitation addresses overflowed the Team page at 320px
(`scrollWidth=331`). Management text now inherits wrapping inside its flex item.
A browser-only old-style override reproduced overflow for accepted, pending and
revoked invitations; corrected content measured 305px in all three states.
The committed regression creates and revokes an invitation through real APIs
and checks all six widths.

| Width | Authenticated surfaces | Result |
| --- | --- | --- |
| 320 | 12 | Passed |
| 375 | 12 | Passed |
| 430 | 12 | Passed |
| 768 | 12 | Passed |
| 1024 | 12 | Passed |
| 1440 | 12 | Passed |

Surfaces include navigation, workspace/project forms and selection, HCL/plan
inputs, expanded analysis/graph/evidence/remediation/coverage/exports, History,
Settings, Team/invitation states, member/archive confirmation cancellation,
usage and pricing.

### Authorization, tenant isolation and security

`tests/test_authorization_matrix.py` inventories authenticated routes and checks
role/session/CSRF/Origin boundaries, including direct and nested identifiers.
Owner-only workspace deletion/billing/ownership actions are protected. Admins
manage projects, policies and non-owner membership. Developers analyze and
manage allowed analysis work; they cannot manage projects/policies/members.
Viewers read permitted evidence and cannot mutate these resources. Last-owner
concurrency, revocation and invitation identity/expiry/single-use checks pass.

Two independent tenants cannot retrieve or mutate foreign organizations,
projects, analyses, reports or artifact IDs: authorized-looking swapped IDs
return 404. Anonymous/revoked sessions return 401; missing/invalid CSRF and
mismatched/cross-site Origin return 403. Browser role identities were established
through actual local OIDC and verified-email invitations.

Focused regressions passed for tenant IDOR, broken authorization, CSRF/Origin,
XSS output handling, SQL-shaped identifiers, SSRF/provider URL restrictions,
path traversal, unsupported archive input, static handling of malicious
Terraform, bounded upload/graph/path expansion, webhook forgery/replay, stale
base/head publication, session/invitation token handling and secret sanitization.
Candidate Terraform, providers and contributor code are never executed.
These are scoped defensive tests, not an exhaustive independent penetration test.

### PostgreSQL, persistence and queue decision

Disposable PostgreSQL acceptance passed clean/populated migrations through
0003, readiness, signed OIDC, workspace/project creation, real worker persistence,
RBAC, tenant-negative reads, History and exports. SQLite/PostgreSQL regressions
also prove identity uniqueness, foreign keys, role constraints and atomic
rollback; quotas, concurrent owner protection and lease fencing are covered.

`tests/test_identity_persistence.py` captures and compares persisted rows across
application teardown/recreation for **users, sessions, organizations,
memberships, projects, analyses, findings, paths/hops, artifacts, usage and audit
events**. Both workspace/project policies and versions, immutable analysis
policy snapshots, Team assignment and its audit event survive. The existing
session still authenticates and authorizes a mutation; report bytes are equal.
Policies and plan assignments are organization/project fields and audit events,
not separate policy/subscription tables.

The real browser process restart separately confirmed one completed analysis's
four findings, one path, five hops and three artifacts. This is application
restart acceptance, not a PostgreSQL backup/PITR restore drill.

**Retain the bounded in-memory queue for a constrained, single-process private
beta.** It does not promise durable input recovery or high availability.
Uploaded input buffers, queue reservations, rate-limit counters, worker scratch
and OIDC-provider tokens are intentionally not durable. Completed evidence,
sessions, quotas and policy/plan state are persisted.

- Parser/graph/worker exceptions, timeout, invalid plans/HCL, missing inputs and
  malformed/inconsistent worker output fail or require review; incomplete
  analysis cannot persist SAFE. Validation rejects contradictory SAFE data.
- Startup recovery marks queued/running rows `failed/server_restarted`.
  A real SIGKILL during RUNNING and subsequent restart passed this behavior.
- Terminal writes retry three times. A deliberately injected, label-limited
  PostgreSQL write fault exhausted retries: readiness/new admission and affected
  unfinished reads returned 503; the UI removed stale RUNNING and showed
  **Analysis incomplete**. Completed evidence remained readable and authorization
  still applied. Removing the fault and restarting finalized the interrupted
  record and allowed a new real BLOCK analysis.
- Loss of the PostgreSQL service lease fences writes and stops workers; a
  successor waits for old transactions to roll back. Do not run multiple replicas.

See [operations](operations.md) for restore/restart, shutdown and queue limits.
An unhealthy Docker healthcheck alone does not restart the container.

<a id="implemented-but-requires-external-configuration"></a>
## IMPLEMENTED BUT REQUIRES OWNER CONFIGURATION

| Item / severity | Why it matters | Exact next action |
| --- | --- | --- |
| OIDC — High | Local signed-provider acceptance does not provision real customer identity | Register a confidential web app with callback `${BR_PUBLIC_URL}/api/auth/callback`, `openid email profile`, PKCE and verified email; configure `BR_OIDC_ISSUER`, client ID/secret, stable session secret and provider access policy. Follow [auth](auth.md) |
| GitHub App — High for GitHub beta | Provider ownership, permissions and publication need an installation | Create an App at [GitHub settings](https://github.com/settings/apps/new), selected repositories only; Contents read, Metadata read, Pull requests write, Checks write; subscribe to pull-request/installation events; configure `${BR_PUBLIC_URL}/api/github/webhook`, App ID/slug, private PEM and webhook secret. Verify workspace/account ownership, then run the [operator registration](github.md#operator-setup) command and connect a project |
| Production platform — Critical | Local Compose does not supply secure managed database/ingress or recovery | Provision explicit HTTPS origin/TLS, secret manager, PostgreSQL certificate verification/encryption, separate app/migration roles and restricted network; follow [production worksheet](environment-production.md) |
| Invitations — Medium | The app creates private links but sends no mail | Configure verified-email OIDC; have authorized managers deliver single-use links privately and test acceptance/revocation with two real provider accounts |
| Beta entitlements — Medium | Pro/Team are permissions and quotas, not subscriptions | Choose approved beta workspaces; grant plans through the audited local operator CLI in [plans](billing.md). Do not activate payments |
| Legal/operator identity — High | Placeholder legal pages cannot support commercial commitments | Approve operator identity, jurisdiction, privacy/terms, subprocessors, retention, support/security contacts and beta terms with the responsible reviewer |
| Web operator / commercial data — High | CLI enablement does not authorize browser review; unscheduled cleanup does not delete physical records | Apply `0004`, configure verified-OIDC UUID allowlist, reauthenticate, validate denial paths and install both cleanup jobs using [seven setup steps](owner-setup.md#web-operator-and-commercial-data-setup) |

<a id="implemented-but-not-externally-acceptance-tested"></a>
## IMPLEMENTED BUT NOT HOSTED-VERIFIED

| Scope / severity | Evidence boundary and why it matters | Exact next action |
| --- | --- | --- |
| Hosted HTTPS/OIDC — High | Stable identity passed with a local signed provider, not the selected external IdP or real ingress | Repeat login, verified-email invitations, revocation, logout/relogin and persistence on the intended HTTPS domain |
| Devin preview — Medium for review access | The proxy rewrites the correct browser HTTPS Origin to `http://localhost`; strict app validation correctly returns `403 invalid_origin`. This is an environment/proxy limitation, not failed local app authentication | Have the proxy preserve Origin or use an approved ingress that does; repeat authenticated HTTPS acceptance. Never trust arbitrary forwarded headers or disable Origin checks |
| SaaS GitHub App — High for GitHub beta | Local HMAC/provider mocks and real worker tests pass; no hosted App installation/check/comment/redelivery acceptance | Authorize a disposable hosted repository; test installation/revocation, signed delivery/redelivery, private/fork permissions, BLOCK/SAFE/REVIEW, stale head/base retarget and app-owned check/comment updates |
| Current strict Actions gate — Medium | Historical Actions [BLOCK](https://github.com/Mighiana/BlastRadius/actions/runs/35441550348)/[SAFE](https://github.com/Mighiana/BlastRadius/actions/runs/35441968970) and [bot-comment update](https://github.com/Mighiana/BlastRadius/pull/1#issuecomment-5741664556) prove the older same-repository integration; current `--fail-on-review`/base-edit behavior and hosted fork fallback were not reaccepted | Approve the analyzer release/pin, rerun the current consumer workflow on same-repository and fork PRs, and verify REVIEW cannot satisfy the merge gate |
| Production operations — Critical | Local database/container checks do not establish backup recovery, TLS, alerting or capacity | Execute restore/deletion, retention, failure-alert and queue-drain drills in [operations](operations.md) on the real deployment |
| Integrated commercial frontend — High | Prior browser evidence predates intake/feedback/operator UI and hardened images | Parent must run the 29 collected browser cases and full authenticated Desktop flow at the final revision, including requested widths, error states, persistence and signed-OIDC operator access |

## NOT YET IMPLEMENTED

These gaps are not invitations to expand this verification pass.

| Gap / severity | Why it matters | Exact next action |
| --- | --- | --- |
| Durable/distributed jobs and automatic redelivery — High when requiring HA | Process loss fails input closed; jobs are not resumed | Constrain beta to one process with documented resubmission; design/test durable admission and idempotent execution before promising HA |
| Payments/subscriptions — Not a beta blocker | Proposed prices cannot collect money | Keep disabled; require a separate approved billing scope before monetized subscriptions |
| Provider-global logout, SAML/SCIM, API tokens, account recovery/erasure UI — Medium | BlastRadius logout revokes its session, not the IdP's SSO session; enterprise identity expectations differ | Document provider/operator procedures and scope required enterprise lifecycle features before selling them |
| Mail transport/self-service GitHub ownership/GHES — Medium | Invitation delivery and installation verification require an operator; GitHub.com only | Use the documented manual process; implement and accept additional providers only for an approved need |
| Automated retention/backup scheduling, durable deletion ledger and external-copy erasure — High | Live read-time retention is not guaranteed physical erasure or backup deletion | Install/test the operator schedule; implement deletion replay/ledger where retention promises require it |
| Live cloud/effective IAM/full routing/multi-cloud — High model limitation | Static supported-resource reachability is incomplete cloud authorization evidence | Require manual review outside [coverage](coverage.md); do not market unsupported guarantees |
| Public report sharing, auto-apply patches, PDF, exact totals on all lists — Low | These capabilities are unavailable | Use protected exports/manual review and current pagination; prioritize only after launch blockers |

## KNOWN SECURITY / MODEL LIMITATIONS

| Limitation / severity | Why it matters | Exact next action |
| --- | --- | --- |
| Container OS vulnerabilities — Critical release blocker | Integrated Trivy 0.74.0 scan: database **1 CRITICAL / 54 HIGH / 80 MEDIUM / 104 LOW / 6 UNKNOWN**, including libxml2 `CVE-2026-6653`. App scan reports zero but zlib `CVE-2026-85091` remains assessed MEDIUM. [Ledger, vendor evidence and exact digests](container-security.md) preserve baseline comparisons | Monitor vendor fixes, select reviewed compatible patched bases/packages, rebuild and rescan exact images until the existing promotion gate passes. Scanner silence is not proof of remediation |
| Static SAFE meaning — High | SAFE means no new modeled blocking finding under selected policy, not secure infrastructure; scores are heuristics | Display coverage/diagnostics, review unsupported resources and require `--fail-on-review` for strict CLI consumers |
| Coverage omissions — High | Modules/indexed resources, effective IAM deny/conditions/boundaries/SCPs and full routing/public-IP prerequisites are not fully modeled | Follow [coverage](coverage.md) and [threat model](threat-model.md); require security review for unsupported semantics |
| Worker containment — High for hostile multi-tenant workloads | Bounded isolated subprocesses and non-root containers are not a complete kernel sandbox | Assess hostile-input isolation and load on the intended host before expanding beyond a constrained beta |
| Evidence lifecycle — High | Reports reveal architecture; backups/GitHub comments may outlive live retention | Restrict storage access and verify retention, deletion replay and external-copy handling before promising erasure |
| Single-process queue — Medium within a constrained beta | Host/process failure loses input and requires resubmission; readiness failure needs operator response | Alert on readiness/terminal persistence failure, restore DB access and restart; test worst-case drain under configured limits |
| Tooling compatibility — Low | Starlette emits an httpx TestClient deprecation warning; npm reports ESLint 9 support status | Track supported test-client/linter upgrades separately and rerun the suite; do not suppress warnings as a fix |

Source/image secret checks and dependency audits are distinct from OS
vulnerability scans. `make promotion-check` **failed as intended**; passing
application tests does not waive the image gate.

<a id="commercial-beta-blockers"></a>
## PRIVATE BETA BLOCKERS

| ID / severity | Why it matters | Exact next action / owner |
| --- | --- | --- |
| B1 — Critical | Current container images fail the unchanged promotion policy | Engineering/operator: remediate the HIGH/CRITICAL findings, rebuild and rescan exact deployment images; retain full scan evidence |
| B2 — High | Real user identity and public TLS have not been accepted | Owner/operator: choose domain/hosting/IdP, provision the documented configuration, then authorize full hosted HTTPS/OIDC/invitation acceptance |
| B3 — High if offering GitHub integration | Mocked provider tests do not prove hosted checks enforce merges | Owner: configure the selected-repository App and authorize disposable hosted acceptance; do not offer it as verified until passed |
| B4 — High | A single-process beta still requires recoverable data, alerts and operational ownership | Operator: provision backup/PITR, run a restore drill, schedule retention, assign incident ownership, alert on failed readiness and validate admission/drain capacity |
| B5 — High | Unreviewed terms/data promises and unapproved artifacts block commercial exposure | Owner/legal: approve beta limits, privacy/terms/support/security contacts and final release/deployment scope. Payments stay disabled |
| B6 — High | Integrated commercial UI and hardened runtime lack final browser acceptance | Parent: rerun authenticated workflow and six-width responsive acceptance, real beta persistence/feedback and authorized/unauthorized operator paths on the final delivery revision; retain exact revision and evidence |

## PUBLIC BETA BLOCKERS

| ID / severity | Why it matters | Exact next action / owner |
| --- | --- | --- |
| U1 — Critical | Private-beta security/identity/operational gates remain open | Resolve B1–B6 before a public invitation; record the exact build/configuration accepted |
| U2 — High | Broad intake exceeds the demonstrated single-process operating scope | Operator: measure admission, request/queue/worker limits and abuse rates; test alerts, exhaustion recovery and support escalation under the intended concurrency |
| U3 — High | Public data collection needs approved legal/support and deletion commitments | Owner: approve notice/contact/retention wording, test physical cleanup and backup deletion replay, publish support/security routes and assign response owners |
| U4 — Medium | Synthetic samples and activity counts do not establish product value | Owner: run the [neutral interviews](customer-interview.md) with authorized private-beta users and record usability/missing-coverage/return-use evidence before widening access; do not infer payment intent from event counts |

## PRODUCTION V1 BLOCKERS

| ID / severity | Why it matters | Exact next action / owner |
| --- | --- | --- |
| P1 — Critical | All applicable beta security/provider blockers carry forward | Resolve B1–B5 and retain dated acceptance on the exact production build/configuration |
| P2 — High | No demonstrated production capacity, SLO, worst-case shutdown or disaster recovery | Operator/engineering: measure request/queue/worker limits and recovery times, rehearse failure/restore and document the supported operating envelope |
| P3 — High for HA claims | In-memory queue/service lease intentionally forbid rolling replicas | Either formally accept single-process availability limits or implement/test durable queueing, fencing and replica transitions before promising HA |
| P4 — High | Retention and deletion across backups/provider copies are not proven | Operator/engineering: establish a deletion ledger/replay process and test restores cannot resurrect erased tenant evidence beyond approved policy |
| P5 — High | Local defensive tests do not replace an independent hosted security assessment | Owner: commission a scoped review of deployed ingress/identity/database/worker/provider boundaries and remediate findings |
| P6 — Medium | Releases/model changes and same-head GitHub checks need controlled versioning | Release owner: approve immutable analyzer pins/version changes, hosted strict REVIEW/base-retarget acceptance and rollback/runbook procedures |

## OWNER ACTIONS REQUIRED

Perform these in order; each linked runbook has concrete commands, configuration
fields and acceptance checks. No external setup was performed by this stage.

1. **Approve scope and owners.** Choose a [deployment pattern](deployment-patterns.md),
   geography and a constrained single-process beta. Assign release, identity,
   database, GitHub, incident, support and legal owners using
   [release/hosting checklist](owner-setup.md#1-release-and-hosting-decision).
2. **Clear promotion before deploying.** Engineering must apply a supported
   compatible vendor remediation, rebuild both images, run
   `bash scripts/verify-containers.sh`, `make container-audit` and
   `make promotion-check`, then retain full ledger/digests. Do not waive the
   remaining HIGH/CRITICAL findings. Repeat final parent-owned browser acceptance
   on that reviewed build; the current integration remains INTERNAL ALPHA.
3. **Configure owned HTTPS infrastructure.** Use the
   [production worksheet](environment-production.md) and
   [domain steps](owner-setup.md#2-domain-and-tls): owned DNS, certificate/renewal,
   exact `BR_PUBLIC_URL`, preserved Host/Origin, private DB network, verified DB
   TLS, migration/runtime role separation, stable secret-manager references.
   Verify live/ready and wrong-host/cross-origin denial through the real ingress.
4. **Register and verify identity.** Follow the
   [OIDC registration worksheet](auth.md#provider-registration-worksheet) for
   issuer/client/secret, exact callback, scopes and logout behavior. Restrict beta
   access at the provider. Test signed login, verified-email invitation,
   logout/relogin, revocation, persistence and denied accounts on actual HTTPS.
5. **Migrate and enable reviewed operators.** Back up, close admission, migrate
   idempotently to `0004` and reapply runtime grants. Follow the
   [seven web-operator steps](owner-setup.md#web-operator-and-commercial-data-setup)
   to verify persisted UUIDs, set `BR_WEB_ADMIN_USER_IDS`, reauthenticate and check
   anonymous/nonoperator denial. Review consent notice; assign beta plans only
   with the audited CLI. Keep checkout disabled.
6. **Authorize GitHub separately if offered.** Complete the
   [App owner checklist](owner-setup.md#4-github-app) and
   [exact registration/CLI setup](github.md#operator-setup). Use selected repos
   and minimum permissions. Separately authorize a disposable repository for
   live signed delivery/check/comment, stale-head/base, REVIEW, fork-permission,
   redelivery and revocation acceptance; do not claim mocks prove live behavior.
7. **Install and exercise operations.** Follow
   [operations/cutover](owner-setup.md#5-operations-and-cutover): encrypted off-host
   backup/PITR with recovery access, provider restore and deletion replay,
   measured RPO/RTO, both bounded cleanup schedules, log retention, certificate/
   readiness/storage/WAL/scratch alarms and incident routes. Trigger an alarm and
   a controlled restore/failure drill; retain receipts, not just configured jobs.
8. **Approve customer-facing commitments.** Legal/support owners approve the
   entity, terms/privacy, subprocessors, geography, 90-day commercial collection,
   plan-based history, deletion/backups and support/security contact routes.
   Use [beta guide](beta-guide.md), [demo script](demo-sales.md) and
   [interview questionnaire](customer-interview.md) for synthetic-first onboarding.
   Record explicit go/no-go only after the applicable gates pass.

Credentials belong in the secret manager, never this document or Git. No missing
credential prevented the completed local shell verification.
