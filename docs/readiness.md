# Commercial-beta readiness

Assessment updated: 2026-09-20, origin configuration regressions and an actual
HTTPS preview diagnostic; earlier local browser acceptance of `ce77f98`, following integration of frontend
`36df10877fd9a1d141805f7a7d160acfa4f61b8e` and operations
`6364e1f7fb2b2553a93272ae276a31fb28ea898c`.
This assessment supersedes the earlier sandbox-billing/12-browser-test snapshot.
It does not certify public production operation or cloud security.

## IMPLEMENTED AND VERIFIED

| Area | Implementation and evidence |
| --- | --- |
| Architecture | Independent Python engine/CLI; React/Vite + FastAPI; SQLAlchemy; isolated worker. Full Python and frontend checks, package checks and model fixtures |
| Onboarding/auth | Demo mode only outside production; OIDC state/nonce/PKCE and signed claims with mocked provider HTTP; server sessions, revocation and CSRF/Origin tests |
| Workspaces/RBAC | Owner/admin/developer/viewer, project metadata/archive/restore, last-owner protection, tenant-negative and role matrix tests |
| Invitations | Random hash-at-rest tokens, expiry/revocation, verified-email identity binding, atomic seat reservation/acceptance; demo identities cannot accept |
| Schema | Alembic 0001→0002→0003, actual-head readiness, populated upgrade preservation and SQLite/PostgreSQL parity tests |
| Jobs/policy | Persisted states, bounded queue/subprocess, trusted policy snapshot reaches real worker; Free/Pro/Team policy behavior and candidate-policy rejection |
| Evidence/history | Findings, path hops, provenance, summaries, filtered/paginated retained history; JSON/Markdown and plan-gated SARIF including nested exports |
| Plans/usage | Singular backend catalog, UTC monthly reservations, active project and invitation/member limits, read-time retention, audited local operator grants |
| GitHub | Tenant installation mappings, signed/idempotent events, bounded file snapshots, quota, policy, PR freshness, app-owned publication; mocked GitHub API with real worker |
| Browser acceptance | 18/18 cases on `ce77f98`; 90 inspected geometry states across seven widths, including mobile menus, graph/evidence and lifecycle pages; local invitation/role/session fixtures and actual origin rejection |
| Compatibility | Original one-line fixture, demo, CLI exit/report, trusted Actions and legacy functional tests retained |
| Payment removal | No payment SDK or active checkout/portal/payment-webhook routes; hostile legacy environment flags cannot activate payments |

Exact commands, installed-package/container checks and downstream acceptance
instructions are in [release integration](release-integration.md).
Provider-mocked tests do not establish real external service behavior.

Latest local checks passed: **609 Python tests with disposable PostgreSQL and no
skips**, **23 release tests**, **78 frontend tests**, Ruff/mypy/ESLint/TypeScript,
production frontend build and documentation links. Independent recorded acceptance
verified the workspace URL-context and persistent save-feedback regressions.
Unchanged core-flow evidence from `d36c9ed` covers HCL BLOCK → manual repair → SAFE,
plan analysis, exports, quota/archive lifecycle and policy effects on future
analyses while historical reports remain unchanged.

Supplemental issued-session fixtures verified email-bound single-use invitations,
role controls and denied viewer mutations, protected ownership, individual/global
session revocation and alternate-origin rejection. These fixtures are application
tests, not real OIDC acceptance. The browser pass did not repeat Docker or live
provider acceptance; earlier package/container evidence retains its original scope.

### HTTPS preview configuration and acceptance boundary

Local development retains the localhost default. Preview and production require
an explicit HTTPS `BR_PUBLIC_URL`; the [separate preview profile](environment-preview.md)
uses an ignored environment file and isolated database. Application and OIDC
cookies are Secure for HTTPS. Regression coverage includes exact/mismatched
origins, forwarded-header spoofing, CSRF, authorization, logout, environment
selection and migrations without modifying local configuration.

Actual HTTPS preview acceptance is **blocked**, not passed. After Devin login,
the browser and `/api/me` matched the configured preview origin, but a correlated
sign-in diagnostic found the proxy replaced the browser's HTTPS Origin with
`http://localhost` before delivery to the application. The existing strict check
correctly returned `403 invalid_origin`. Cookie and CSRF-header presence were
confirmed at both ends; no secret values were recorded. The issue was reported
to Cognition, and temporary instrumentation was removed.

The requested authenticated workspace → project → analysis → persisted history
flow remains unverified through that HTTPS proxy. Prior local acceptance and
passing API regressions do not substitute for it. Neither Origin checks nor
authorization were weakened to accommodate the proxy.

## IMPLEMENTED BUT REQUIRES EXTERNAL CONFIGURATION

- **OIDC:** confidential provider app, issuer/client credentials, callback, exact
  HTTPS origin, verified email and provider access policies. See [auth](auth.md).
  Verify browser callback/logout/session revocation with the chosen provider.
- **Invitations:** authorized managers manually deliver the one-time private
  invitation link. No mail transport is installed. OIDC must assert the matching
  verified email; real delivery/provider acceptance remains external.
- **GitHub App:** selected-repository installation, PEM/webhook secret, permissions,
  event endpoint and independently verified workspace/account ownership.
  See [setup](github.md). Real checks/comments/redelivery require provider acceptance.
- **Deployment:** TLS ingress, secrets, PostgreSQL TLS/encryption, backups/PITR,
  restore/deletion replay, retention schedule, monitoring, alerting and rate limits.
  Local hardened-container checks do not install these services.
- **Paid-plan entitlements:** an operator can grant Pro/Team/Enterprise using the
  local CLI; proposed prices are informational and create no subscription.
- **Legal:** all trust/legal copy is marked **LEGAL REVIEW REQUIRED**; operator
  identity, jurisdiction, support contacts, subprocessors and terms need approval.

## NOT YET IMPLEMENTED

- Payments, checkout, card collection, billing provider events or subscriptions.
- Durable/distributed jobs, multi-replica availability, priority queues,
  production SLO/capacity validation, automatic GitHub redelivery.
- SAML, SCIM, enterprise API tokens, domain-restricted signup, in-app account
  recovery/user erasure, provider-global logout or installed mail delivery.
- Automatic retention/backup scheduling, durable deletion ledger, automatic
  cleanup of GitHub delivery/run tombstones, external-copy erasure.
- Self-service GitHub ownership verification, GitHub Enterprise Server,
  multi-root aggregation, arbitrary repository URL fetching or archive uploads.
- Live AWS discovery, effective IAM evaluation, full network routing, Terraform
  execution, Azure/GCP/Kubernetes analysis, compliance certification.
- Public share links, automatic Terraform patch application, PDF reports.
- Browser project-list pagination beyond 100 projects; invitation/audit
  pagination has no backend total and may show an empty final page.

## KNOWN SECURITY / MODEL LIMITATIONS

SAFE means no new modeled blocking findings under the selected policy. Scores
are heuristics. Unsupported/unknown inputs and truncation require review;
no path found is not proof of no path. CLI REVIEW exits 0 by default; strict
consumers must use `--fail-on-review`. GitHub App success additionally requires
a literal complete SAFE result.

Supported [coverage](coverage.md) omits full routing/public-IP prerequisites,
effective IAM deny/conditions/boundaries/SCPs, modules/indexed resources and many
AWS services. Reports expose architecture despite sanitization. Backups and
GitHub comments may outlive live evidence. Shorter plans hide expired data
immediately but do not guarantee physical secure erasure.

Worker limits and non-root containers reduce exposure; they are not a complete
sandbox or kernel boundary. One process and in-memory queues remain explicit
operational constraints. See [threat model](threat-model.md).

The integration's Trivy 0.74.0 rescan (database dated
2026-09-19T07:03:12Z) reproduced application **0 CRITICAL / 44 HIGH** and PostgreSQL
**1 CRITICAL / 61 HIGH**, without scanner-listed fixes. The critical finding is
`CVE-2026-6653` in libxml2. Source/image secret scans passed; the existing
HIGH/CRITICAL promotion gate failed as intended. No suppressions or reduced
severity policy were added. Rescan each final release image before promotion;
these results are not a waiver.

## COMMERCIAL LAUNCH BLOCKERS

1. Resolve or obtain an explicitly approved risk disposition for container OS
   findings under the existing promotion policy; rebuild/rescan exact final images.
2. Real OIDC verified-email login/invitation acceptance and GitHub installation,
   signed delivery, stale PR and publication acceptance in an approved environment.
3. Production TLS/secrets/database configuration, backup/PITR restore drill,
   deletion replay, retention scheduling, monitoring, incident response and load
   validation for the documented single-process operating envelope.
4. **LEGAL REVIEW REQUIRED:** approve privacy/terms/support/security contacts,
   data lifecycle promises and commercial-beta terms. No payment activation is
   part of this release.
5. Owner approval of release artifacts and public deployment. No new deployment,
   DNS change, purchase or registry publication was performed by this integration.

Next phase: finish external acceptance, remediate promotion blockers,
and approve a constrained beta. Add enterprise capability or payment processing
only through separate reviewed scopes.
