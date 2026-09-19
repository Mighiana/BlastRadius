# Coverage and release roadmap

Coverage must be tied to tested relationships and the engine version. This page
records baseline limits and priorities; the engine-owned coverage document is
authoritative after integration.

## Baseline capabilities

Static HCL/plan input, Git snapshots, security-group ingress, EC2 attachment,
instance-profile → IAM-role links, selected IAM → S3 connections, public bucket
exposure and sensitivity tags feed a NetworkX graph and before/after comparison.
Reports include policy decisions, heuristic scores and evidence.
Three synthetic scenarios demonstrate different root causes.

## Unsupported or not verified by this release unit

| Area | Work before claiming coverage |
|---|---|
| VPC/subnets/routes/IGW/NAT | Model actual routing/public-IP prerequisites and test positive/negative paths |
| NACLs and SG-to-SG | Direction/state/port semantics, cycles and incomplete-rule diagnostics |
| Load balancers, RDS, Lambda | Resource-specific network/identity relationships with evidence |
| Secrets Manager/KMS | Precise privilege/data access, key policy/grants and denial handling |
| S3 public access blocks | Validate interaction with ACLs/policies/account settings; unknowns stay explicit |
| IAM conditions/deny/boundaries/SCPs | No simplified “Allow always wins”; report unsupported/unknown semantics |
| Wildcard ARNs/NotAction/NotResource | Tested matching and exclusions; never guess a relationship |
| Terraform modules/count/for_each | Stable indexed addresses, no collapsing resources, safe deterministic inputs |
| Variables/unknown plan values | Track uncertainty without turning unknown into absent or safe |
| Live account/state import | Separate read-only authorization and provenance design |
| Azure/GCP/Kubernetes | Explicitly outside baseline AWS scope |

Some items may be implemented by the parallel engine unit. Update claims only
after its tests and coverage diagnostics are integrated; do not retain this table
as a false claim that new support cannot exist.

## Ordered release priorities

**P0 — correctness/security:** fail closed on invalid inputs/configuration,
bounded parser/graph work, tenant authorization, isolated job storage, trusted
GitHub reporting and redacted errors.

**P1 — product reliability:** integrated React/API onboarding, responsive graph,
real empty/loading/error states, history/exports, clean-install and PostgreSQL
migration/restore tests.

**P2 — commercial foundation:** verified identity, usage quotas, billing test-mode
behavior, approved legal/privacy/retention/support terms and operator runbooks.
No live billing without owner approval.

**P3 — deeper AWS coverage:** expand the relationships above with meaningful
positive/negative tests, evidence and confidence. Prefer accurate incompleteness
to broad invented paths.

**P4 — release polish:** verified screenshots, final readiness report, reviewed
immutable release/distribution pins and approved public deployment.
GitHub App, enterprise API endpoints and multi-root aggregation remain separate work.

No roadmap item is a shipping promise. A valid handoff states unverified areas
instead of marking a product “production ready” merely because files exist.
