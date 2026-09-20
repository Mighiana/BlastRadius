# Authenticated SaaS readiness

Assessment: **2026-09-20**. Local verification passed; **public commercial launch
is blocked** by the items below. This is not a production-security certification.

Browser revision: `c9253b9340a35ea61e0ed17262b9113293d84e64`.
Backend failure/role evidence retained from `9b0b5a6` uses identical backend code.
Subsequent changes add persistence regressions and this report without changing
runtime behavior. PR #2 was merged outside this session's actions; the user
approved the separate [verification PR #3](https://github.com/Mighiana/BlastRadius/pull/3).
No follow-up merge, payment activation or public deployment was performed.

## IMPLEMENTED AND VERIFIED

### Measured verification

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

## IMPLEMENTED BUT REQUIRES EXTERNAL CONFIGURATION

| Item / severity | Why it matters | Exact next action |
| --- | --- | --- |
| OIDC — High | Local signed-provider acceptance does not provision real customer identity | Register a confidential web app with callback `${BR_PUBLIC_URL}/api/auth/callback`, `openid email profile`, PKCE and verified email; configure `BR_OIDC_ISSUER`, client ID/secret, stable session secret and provider access policy. Follow [auth](auth.md) |
| GitHub App — High for GitHub beta | Provider ownership, permissions and publication need an installation | Create an App at [GitHub settings](https://github.com/settings/apps/new), selected repositories only; Contents read, Metadata read, Pull requests write, Checks write; subscribe to pull-request/installation events; configure `${BR_PUBLIC_URL}/api/github/webhook`, App ID/slug, private PEM and webhook secret. Verify workspace/account ownership, then run the [operator registration](github.md#operator-setup) command and connect a project |
| Production platform — Critical | Local Compose does not supply secure managed database/ingress or recovery | Provision explicit HTTPS origin/TLS, secret manager, PostgreSQL certificate verification/encryption, separate app/migration roles and restricted network; follow [production worksheet](environment-production.md) |
| Invitations — Medium | The app creates private links but sends no mail | Configure verified-email OIDC; have authorized managers deliver single-use links privately and test acceptance/revocation with two real provider accounts |
| Beta entitlements — Medium | Pro/Team are permissions and quotas, not subscriptions | Choose approved beta workspaces; grant plans through the audited local operator CLI in [plans](billing.md). Do not activate payments |
| Legal/operator identity — High | Placeholder legal pages cannot support commercial commitments | Approve operator identity, jurisdiction, privacy/terms, subprocessors, retention, support/security contacts and beta terms with the responsible reviewer |

## IMPLEMENTED BUT NOT EXTERNALLY ACCEPTANCE-TESTED

| Scope / severity | Evidence boundary and why it matters | Exact next action |
| --- | --- | --- |
| Hosted HTTPS/OIDC — High | Stable identity passed with a local signed provider, not the selected external IdP or real ingress | Repeat login, verified-email invitations, revocation, logout/relogin and persistence on the intended HTTPS domain |
| Devin preview — Medium for review access | The proxy rewrites the correct browser HTTPS Origin to `http://localhost`; strict app validation correctly returns `403 invalid_origin`. This is an environment/proxy limitation, not failed local app authentication | Have the proxy preserve Origin or use an approved ingress that does; repeat authenticated HTTPS acceptance. Never trust arbitrary forwarded headers or disable Origin checks |
| SaaS GitHub App — High for GitHub beta | Local HMAC/provider mocks and real worker tests pass; no hosted App installation/check/comment/redelivery acceptance | Authorize a disposable hosted repository; test installation/revocation, signed delivery/redelivery, private/fork permissions, BLOCK/SAFE/REVIEW, stale head/base retarget and app-owned check/comment updates |
| Current strict Actions gate — Medium | Historical Actions [BLOCK](https://github.com/Mighiana/BlastRadius/actions/runs/35441550348)/[SAFE](https://github.com/Mighiana/BlastRadius/actions/runs/35441968970) and [bot-comment update](https://github.com/Mighiana/BlastRadius/pull/1#issuecomment-5741664556) prove the older same-repository integration; current `--fail-on-review`/base-edit behavior and hosted fork fallback were not reaccepted | Approve the analyzer release/pin, rerun the current consumer workflow on same-repository and fork PRs, and verify REVIEW cannot satisfy the merge gate |
| Production operations — Critical | Local database/container checks do not establish backup recovery, TLS, alerting or capacity | Execute restore/deletion, retention, failure-alert and queue-drain drills in [operations](operations.md) on the real deployment |

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
| Container OS vulnerabilities — Critical release blocker | Trivy 0.74.0, vulnerability DB updated 2026-09-20T07:08:21Z: application **0 CRITICAL / 44 HIGH**; PostgreSQL **1 CRITICAL / 61 HIGH**. Critical: `CVE-2026-6653` in libxml2. No scanner-listed fixes for these HIGH/CRITICAL findings | Monitor vendor fixes, select reviewed patched base digests/packages, rebuild and rescan exact images until the existing promotion gate passes. No suppression or severity reduction was applied |
| Static SAFE meaning — High | SAFE means no new modeled blocking finding under selected policy, not secure infrastructure; scores are heuristics | Display coverage/diagnostics, review unsupported resources and require `--fail-on-review` for strict CLI consumers |
| Coverage omissions — High | Modules/indexed resources, effective IAM deny/conditions/boundaries/SCPs and full routing/public-IP prerequisites are not fully modeled | Follow [coverage](coverage.md) and [threat model](threat-model.md); require security review for unsupported semantics |
| Worker containment — High for hostile multi-tenant workloads | Bounded isolated subprocesses and non-root containers are not a complete kernel sandbox | Assess hostile-input isolation and load on the intended host before expanding beyond a constrained beta |
| Evidence lifecycle — High | Reports reveal architecture; backups/GitHub comments may outlive live retention | Restrict storage access and verify retention, deletion replay and external-copy handling before promising erasure |
| Single-process queue — Medium within a constrained beta | Host/process failure loses input and requires resubmission; readiness failure needs operator response | Alert on readiness/terminal persistence failure, restore DB access and restart; test worst-case drain under configured limits |
| Tooling compatibility — Low | Starlette emits an httpx TestClient deprecation warning; npm reports ESLint 9 support status | Track supported test-client/linter upgrades separately and rerun the suite; do not suppress warnings as a fix |

Source/image secret checks and dependency audits are distinct from OS
vulnerability scans. `make promotion-check` **failed as intended**; passing
application tests does not waive the image gate.

## COMMERCIAL BETA BLOCKERS

| ID / severity | Why it matters | Exact next action / owner |
| --- | --- | --- |
| B1 — Critical | Current container images fail the unchanged promotion policy | Engineering/operator: remediate the HIGH/CRITICAL findings, rebuild and rescan exact deployment images; retain full scan evidence |
| B2 — High | Real user identity and public TLS have not been accepted | Owner/operator: choose domain/hosting/IdP, provision the documented configuration, then authorize full hosted HTTPS/OIDC/invitation acceptance |
| B3 — High if offering GitHub integration | Mocked provider tests do not prove hosted checks enforce merges | Owner: configure the selected-repository App and authorize disposable hosted acceptance; do not offer it as verified until passed |
| B4 — High | A single-process beta still requires recoverable data, alerts and operational ownership | Operator: provision backup/PITR, run a restore drill, schedule retention, assign incident ownership, alert on failed readiness and validate admission/drain capacity |
| B5 — High | Unreviewed terms/data promises and unapproved artifacts block commercial exposure | Owner/legal: approve beta limits, privacy/terms/support/security contacts and final release/deployment scope. Payments stay disabled |

## PRODUCTION V1 BLOCKERS

| ID / severity | Why it matters | Exact next action / owner |
| --- | --- | --- |
| P1 — Critical | All applicable beta security/provider blockers carry forward | Resolve B1–B5 and retain dated acceptance on the exact production build/configuration |
| P2 — High | No demonstrated production capacity, SLO, worst-case shutdown or disaster recovery | Operator/engineering: measure request/queue/worker limits and recovery times, rehearse failure/restore and document the supported operating envelope |
| P3 — High for HA claims | In-memory queue/service lease intentionally forbid rolling replicas | Either formally accept single-process availability limits or implement/test durable queueing, fencing and replica transitions before promising HA |
| P4 — High | Retention and deletion across backups/provider copies are not proven | Operator/engineering: establish a deletion ledger/replay process and test restores cannot resurrect erased tenant evidence beyond approved policy |
| P5 — High | Local defensive tests do not replace an independent hosted security assessment | Owner: commission a scoped review of deployed ingress/identity/database/worker/provider boundaries and remediate findings |
| P6 — Medium | Releases/model changes and same-head GitHub checks need controlled versioning | Release owner: approve immutable analyzer pins/version changes, hosted strict REVIEW/base-retarget acceptance and rollback/runbook procedures |

Actions requiring the user personally: choose/approve the hosting domain and
provider accounts, authorize GitHub installation/test writes, assign operational
and legal owners, and approve a release only after its gates pass. Credentials
belong in the secret manager, never this document or Git. There is no missing
credential blocking the completed local verification.
