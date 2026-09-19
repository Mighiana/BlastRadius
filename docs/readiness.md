# Product readiness assessment

Assessment date: 2026-09-19. Delivery branch: `devin/productionize-blastradius`.
[Delivery PR](https://github.com/Mighiana/BlastRadius/pull/2) remains subject to
owner review and merge approval.

**Verdict:** the integrated product is verified for local evaluation,
demonstrations and technical review. Public production operation and charging
customers require the provider, security and operational acceptance listed below.
Feature implementation alone does not establish production readiness.

## Before and after

| Area | Before | After | Verification |
| --- | --- | --- | --- |
| Product experience | CLI and Streamlit MVP; observed mobile overflow and clipped paths | React/TypeScript landing page, onboarding, workspace, history, billing and coverage guide | 12 browser tests; recorded inspection at 320, 375, 768, 1024 and 1440px |
| Analysis correctness | Useful narrow AWS path model; unsupported constructs could be missed | Explicit coverage diagnostics, incomplete decisions, conservative S3 controls and evidence-bearing edges | Positive/negative engine cases; incomplete exports cannot claim PASSED |
| Demonstration | Legacy simulation workflow | Three real-engine SAFE → BLOCK → SAFE demos with before/after graphs and exports | SSH 100→20→100; IAM 85→20→85; S3 100→35→100 |
| Hosted execution | Session-local demo with filesystem access risks | Bounded inputs, isolated subprocess jobs, CPU/memory/time/output budgets, sanitized failures | Worker, path traversal, resource limit, concurrency and real HTTP job tests |
| Identity and tenancy | No product account boundary | OIDC integration, secure sessions, CSRF, organizations, roles, projects and tenant-scoped storage | Local authorization/session tests and independent browser identities; live OIDC outstanding |
| Persistence | Ephemeral demo state | SQLite evaluation mode, PostgreSQL migrations, analysis history, exports and deletion APIs | Database tests, container recreation, history reopening and deletion |
| Billing | No monetization integration | Free/Pro/Team quotas; Stripe test checkout, portal and signed replay-protected webhooks | Mock provider and quota tests; disabled billing browser path; real provider outstanding |
| Distribution | Source CLI and existing trusted-base GitHub workflow | Isolated wheel verification, Docker/Compose, integrated CI, setup and deployment docs | Clean clone, wheel, CLI, build, migration and container HTTP checks |
| Operations | No documented service operating contract | Readiness/liveness, metrics/logging, threat model, backup/restore and lifecycle guidance | Local startup and recovery checks; production infrastructure outstanding |
| Commercial readiness | Hackathon narrative | Product positioning, demonstration guide, pricing UI and legal/support templates | Documentation checked; pricing, license, entity and legal terms need owner decisions |

## Implemented and verified

- CLI, HCL/plan ingestion, graph/path differences, responsible-change evidence,
  scores, remediation guidance and JSON/Markdown/SARIF exports remain integrated.
  The original one-line SSH fixture and all original tests are preserved.
- Security-relevant unsupported input produces structured diagnostics and REVIEW,
  not an unqualified SAFE result. A review-required Markdown export uses a
  warning heading even when the configured CI gate permits REVIEW.
- Users can create a local disposable identity and project, upload HCL or a plan,
  observe queued/running/completed jobs, inspect evidence, export, reopen and
  delete analyses. Malformed inputs fail without a SAFE verdict or traceback.
- React rendering treats malicious labels as text. Graphs and evidence controls
  remained contained across all five requested widths; keyboard interaction,
  loading, empty and error states were exercised.
- Tenant authorization, CSRF, sessions, quotas, webhook signatures/replays and
  concurrency have tests. Independent browser identities cannot read each
  other's reports. No candidate Terraform/provider or contributor code is run.
- Legacy Streamlit still supports simulation/remediation, Demo Mode and
  independent sessions. Arbitrary local directory/Git controls are hidden in
  default hosted mode.
- The hardened application image runs as UID 10001 with a read-only root,
  dropped capabilities and no pip/ensurepip. PostgreSQL migration, real
  subprocess jobs, all nine demo states and report exports passed in Compose.

## Implemented but not fully verified

- OIDC state, nonce, PKCE, token handling and session behavior have local tests.
  Login/logout with an owner's real identity provider and HTTPS callback remains
  unverified.
- Stripe checkout, portal and webhook behavior have test-mode implementation and
  mocked tests. No real Stripe account, sandbox checkout, subscription or webhook
  delivery was exercised.
- Production TLS, proxy limits, secret rotation, persistent identity,
  database encryption, backup restoration, alert routing and incident response
  need verification in the selected hosting environment.
- GitHub trusted-base, stale-head and permission fallback tests pass locally.
  Existing hosted same-repository evidence predates this work; fork publication
  fallback remains mocked. No new live publisher write or GitHub App was created.

## Known limitations

- Static modeling cannot prove exploitability, effective AWS authorization or
  cloud safety. See the [coverage matrix](coverage.md) and
  [security model](security-model.md). Broad routing/VPC/NACL, load-balancer,
  service and IAM/module semantics remain outside coverage.
- The IAM reviewed baseline/restored score is intentionally 85. Existing public
  compute exposure remains; restoration uses a reviewed fixture, not a generated
  IAM policy patch.
- The service requires one ASGI process per database and uses an in-memory
  queue. There is no distributed queue/HA deployment, scheduled retention job,
  GitHub App connection, membership administration UI or project-deletion UI.
  Membership and project-deletion APIs enforce roles.
- Previously stored Markdown is not regenerated by an upgrade. Reports created
  before the review-heading correction retain their original export; rerun the
  analysis to obtain the corrected report.
- The retained Streamlit UI has legacy presentation defects: hidden branding,
  a missing decision glyph and the old reachability heading above an eliminated
  path after remediation. Its mobile visuals were not re-certified; the React
  product is the demonstrated frontend.
- Strict typing covers the new service/scripts and checked engine modules;
  this is not a claim that every historical Python module is fully typed.

## Security limitations

Dependency audits and secret scanning passed, but container scanning did **not**
establish a clean production image. Trivy 0.74.0, without suppression, reported:

| Scanned component | Critical | High | Medium | Low | Unknown | Fix availability in scan |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Hardened application: Debian 13 OS packages | 0 | 44 | 49 | 57 | 1 | No listed fixes |
| Hardened application: Python packages | 0 | 0 | 0 | 0 | 0 | No findings |
| Compose PostgreSQL 16.15 Bookworm OS packages | 15 | 78 | 172 | 154 | 0 | No listed fixes |
| Compose PostgreSQL bundled `gosu` Go dependencies | 1 | 21 | 21 | 2 | 1 | Upstream version fixes listed for 46 findings |

Counts are scanner findings, not demonstrated reachable exploits. Conversely,
absence of an available Debian fix does not establish acceptability. The
application moved from Bookworm to pinned Python 3.12.14/Trixie, upgraded its build
tooling and removed runtime installers. The local PostgreSQL image still needs a
reviewed replacement/rebuild or a maintained managed database before promotion.
Do not expose this Compose example as an approved production stack.

Re-scan both application and database images at deployment time, investigate
affected package use, and document fixes or explicit risk decisions. Preserve
scanner output as release evidence; Python/npm audits do not cover these OS/Go
components. Isolation also requires production infrastructure protections; a
resource-limited Python subprocess is not a complete hostile-code sandbox.

## Commercial / billing limitations

- Billing accepts test keys only. Live billing activation and real purchases
  were not performed.
- Pricing is a product proposal. Taxes, refunds, cancellation, payment disputes,
  support commitments and service-level terms require owner decisions.
- Privacy, terms, billing and support documents are clearly marked legal-review
  templates. No legal entity, final data processing terms or guaranteed retention
  promise has been invented.
- No standalone open-source license was selected. Public source availability
  alone is not an open-source license grant. Resolve licensing before promoting
  licensed distribution or accepting external contributions on that basis.

## Deployment status

- Local integrated service, fresh-clone setup and PostgreSQL Compose were
  exercised. A private Devin preview is available only while the session machine
  is awake.
- No public site, domain, DNS, registry package, GitHub App or paid service was
  deployed. No production data or credentials were used.
- Work is delivered through the requested branch and PR; `main` was not changed.
- A repository environment blueprint and reusable browser-testing skill are
  proposed for owner approval. A proposal is not a completed future snapshot.

## Test results

| Check | Result |
| --- | --- |
| Baseline suite before changes | 239 passed |
| `make check` | 440 passed, 1 optional PostgreSQL test skipped; 16 release tests; Ruff, mypy and documentation links passed |
| Full suite with disposable PostgreSQL | 441 passed, including schema parity, worker execution, service lease, concurrent quotas and tenant deletion on PostgreSQL 16.15 |
| `make frontend` | ESLint, TypeScript, 34 Vitest tests and production build passed |
| Browser acceptance | 12/12 existing Playwright cases; recorded workspace, adversarial, demo and legacy checks passed within the boundaries above |
| Packaging | Wheel built, isolated core/server installation and CLI/plan/report paths verified outside checkout |
| Fresh clone | Installation, checks/build, SQLite migrations, local startup and real HTTP analysis verified |
| Dependency and secret audits | pip-audit and npm audit: no known vulnerabilities; Gitleaks: no secrets |
| Container | Hardened build, non-root/read-only runtime, health, migrations, nine demos, real PostgreSQL jobs and exports passed; scan findings remain above |

Starlette emits a TestClient/httpx compatibility deprecation warning and npm
reports ESLint 9's support deprecation. These did not fail their checks; upgrade
planning is still warranted. CI status belongs to the current PR checks, not this
static report.

Synthetic engine performance in this VM (three measurements per size; no hosted
service SLA):

| Resources per snapshot | Median comparison | Peak RSS |
| ---: | ---: | ---: |
| 6 | 0.016 s | 60.7 MiB |
| 60 | 0.167 s | 63.9 MiB |
| 300 | 1.569 s | 77.2 MiB |
| 600 | 6.885 s | 94.6 MiB |

All measured cases completed with the expected regression decision. Dense IAM
graphs, larger real estates and concurrent hosted workloads require separate
capacity testing; budgets intentionally reject excessive work.

## Next priorities

1. Resolve application/database image findings and choose hosting, TLS and
   persistent secrets before a public pilot.
2. Configure one OIDC provider and Stripe sandbox; record real callback,
   logout, checkout, portal and signed webhook acceptance.
3. Choose license/entity/terms and data retention policy; implement scheduled
   retention and validate backup restoration and monitoring.
4. Pilot with reviewed, supported Terraform inputs and clear coverage warnings.
   Measure workload/concurrency before extending quotas or adding multiple workers.
5. Extend model coverage with positive/negative fixtures and evidence before
   claiming additional AWS relationships; see the [roadmap](roadmap.md).
