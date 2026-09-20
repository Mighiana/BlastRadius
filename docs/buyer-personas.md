# Early buyer and user hypotheses

Internal product research, not established customer segments or market claims.
These are hypotheses to test with the [interview guide](customer-interview.md).
No market sizes, purchase rates, prices or existing customers are inferred.
A likely user is not necessarily the budget holder.

## 1. DevOps / platform engineer

| Area | Hypothesis to validate |
|---|---|
| Pain | A small Terraform edit can require chasing relationships across networking, compute and IAM before a reviewer understands its impact. |
| Current workflow | Terraform plan, GitHub review, static checks and escalation to security for difficult changes. |
| Potential value | A before/after path and the responsible line may help explain a change in the PR where the engineer already works. |
| Likely objections | Incomplete module coverage, noisy gates, extra CI latency, duplicated tools and maintenance of policies or exceptions. |
| Features they may care about | Clear per-hop evidence, trusted-base policy, useful diagnostics, fast bounded analysis, local reproduction and reviewed patch suggestions. |
| Buying role / question | Likely evaluator or champion; a platform lead or budget owner may approve. Ask which recent PR would have changed with this evidence. |

## 2. Cloud security engineer

| Area | Hypothesis to validate |
|---|---|
| Pain | Reviewing isolated misconfigurations may not show which changes connect reachable compute to sensitive resources. |
| Current workflow | IaC checks, cloud posture/identity tools, manual review and consultation with infrastructure owners. |
| Potential value | Change-specific path evidence could focus review on newly introduced reachability rather than an undifferentiated inventory. |
| Likely objections | Effective-IAM and routing exclusions, missing cross-account paths, unknowns presented as safety, and insufficient evidence to challenge a result. |
| Features they may care about | Explicit confidence/coverage, fail-closed REVIEW handling, reproducible reports, policy control, auditability and sensitivity classification. |
| Buying role / question | Possible technical approver; security leadership may own budget. Ask where this adds information their current tools cannot already provide. |

## 3. Small SaaS CTO

| Area | Hypothesis to validate |
|---|---|
| Pain | A small team may lack time or specialist coverage to review the security consequences of every infrastructure change. |
| Current workflow | Engineers review each other's plans; the CTO or a consultant handles unusual changes and risk decisions. |
| Potential value | A readable explanation might support a focused review and help decide when outside expertise is needed. |
| Likely objections | Paying for another tool, setup overhead, narrow AWS coverage, false assurance, data handling and an unproven support model. |
| Features they may care about | Quick local evaluation, clear limits, useful GitHub evidence, predictable access/retention controls and straightforward support. |
| Buying role / question | May be both evaluator and buyer, subject to company approval. Ask what outcome would justify spending versus using existing checks or a consultant. |

## 4. Cloud / security consultancy

| Area | Hypothesis to validate |
|---|---|
| Pain | Consultants may need to explain change impact reproducibly while keeping client environments and evidence separate. |
| Current workflow | Authorized repository review, assessment tooling, manual relationship analysis and written recommendations for clients. |
| Potential value | Portable evidence and synthetic reproduction could support an assessment discussion or a client handoff. |
| Likely objections | Coverage misses, client-data restrictions, contractual obligations, attribution/licensing questions and insufficient isolation or repeatability. |
| Features they may care about | Local execution, Markdown/JSON/SARIF exports, provenance, explicit model bounds and controlled access/retention per engagement. |
| Buying role / question | Practice lead or firm owner may approve; clients may separately approve data processing. Ask what evidence their deliverables require and where this would fail that standard. |

## How to use these hypotheses

Start with one recent workflow from each relevant respondent. Test whether the
problem is frequent enough to matter, whether existing tools already solve it,
whether the current [coverage](coverage.md) fits, and who can approve evaluation
and purchase. Features above are possible priorities, not promises that all exist.

Record adoption blockers as carefully as interest. For example, a team dominated
by unexpanded modules or unmodeled services may be a poor current fit despite
liking the concept. Do not turn a requested capability, an agreeable interview
or a successful synthetic demo into a revenue forecast or validated buyer claim.
