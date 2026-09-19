# Engine coverage, bounds and handoff contract

## Input adapters

`parse_file` and `parse_directory` read local UTF-8 `.tf` files without evaluating
Terraform. Directory parsing is nonrecursive, matching a single Terraform root.
Terraform `.tf.json` inputs are not evaluated; their presence in a source root
is diagnosed. HCL quotations, heredocs and literal resource references retain
the original parser normalization contract. `jsonencode`, variables, locals,
functions, `dynamic`, `count`, `for_each` and unexpanded module calls are
diagnosed when relevant rather than silently establishing safety.

`parse_plan`, `parse_plan_file`, and `parse_plan_pair` read saved Terraform plan
JSON. Prefer full `planned_values` and `prior_state.values` snapshots. The
`resource_changes` fallback remains available but is diagnosed as potentially
partial when a phase snapshot is absent. Unknown security-relevant values in
`after_unknown` and `proposed_unknown` are diagnosed. Unknown identity/computed
fields that do not affect modeled security are not blanket failures.

Plan configuration references recover candidate relationships only. Prior-state
links use prior-state identities and cannot be overwritten by candidate
configuration. Module/indexed addresses remain outside coverage, avoiding
collisions with root addresses. Duplicate resource addresses are diagnosed and
excluded from graph construction. Ambiguous plan identity matches are not
selected arbitrarily; unresolved relationship members remain diagnostic.

## Supported resources

| Resource | Modeled input |
|---|---|
| `aws_security_group` | Inline ingress with known protocol, ports and public CIDRs |
| `aws_instance` | Security group attachments, instance profile |
| `aws_iam_instance_profile` | Role reference |
| `aws_iam_role` | Role node |
| `aws_iam_role_policy` | Role link and JSON policy |
| `aws_iam_policy` | JSON policy for modeled attachments |
| `aws_iam_role_policy_attachment` | Role + modeled policy link |
| `aws_s3_bucket` | Bucket identity, canned ACL, sensitivity tags/name |
| `aws_s3_bucket_acl` | Bucket link + canned ACL |
| `aws_s3_bucket_policy` | Bucket link + anonymous object-read JSON policy |
| `aws_s3_bucket_public_access_block` | Bucket link + four known boolean flags |

Inline legacy bucket `policy` attributes and explicit ACL grant blocks are
diagnosed rather than silently treated as modeled policy documents. The
security model documents the deliberate broad IAM privilege compatibility.

### Explicit exclusions

No VPC routing, public-IP prerequisite, NAT, NACL, peering, transit gateway,
security-group-to-security-group propagation, standalone SG rule resources,
prefix-list evaluation, ALB reachability, RDS, Lambda, ECS/EKS, KMS decryption,
cross-account paths, access-point policies, service-control policies, effective
IAM authorization, drift discovery or live AWS inspection is implemented.
Non-universal public CIDRs and combinations of ranges are not expanded into
internet coverage. A complete result means complete within these rules and the
selected input; it does not mean complete AWS coverage.

## Fixed analysis budgets

| Budget | Limit | Behavior |
|---|---:|---|
| File/root input bytes | 4 MiB | HCL root cumulative; plan file individually; reject over limit |
| HCL files per root | 128 | Reject additional files |
| Resources per root/plan phase | 1,000 | Includes unsupported managed HCL resources; reject over limit |
| Plan resource entries across snapshots/config/change lists | 4,000 | Reject over limit |
| Structural values | 100,000 | Per parsed document; direct graph inputs checked together |
| Input nesting depth | 64 | Lexical guard before parser plus structural guard afterward |
| Analysis graph | 2,500 nodes / 20,000 edges | Oversized direct graphs rejected |
| Graph-builder edges | 20,000 | Stop adding new edges; `GRAPH_TRUNCATED` diagnostic |
| Paths per target | 25 | Mark `PATHS_TRUNCATED`; count becomes a lower bound |
| Paths across all targets | 500 | Mark `PATHS_TRUNCATED` |
| Path depth | 32 edges | Longer paths not enumerated; reachability retained |
| Enumeration work | 100,000 iterator steps total | Includes exhausted iterators and dead ends; mark truncation |

Regular file reads stop at the byte limit plus one, and final-component
symlink inputs are rejected. Nesting checks understand quoted strings,
comments and heredocs. The depth/value guards also apply to embedded JSON
policies. Byte limits do not guarantee a parser CPU/memory bound; hosted
workers must also enforce process limits.

Path enumeration uses lexically sorted targets/successors and iterative DFS.
A deterministic breadth-first predecessor map supplies a shortest witness
before DFS explores alternatives, so dead ends cannot conceal the first
reachable target merely by delaying the first path yield. BFS and reachability
work are linear in the bounded graph size and are separate from the DFS work
counter. Exact threshold hits conservatively mark truncation even if no further
paths exist. No call to `networkx.all_simple_paths` remains in the analyzer.

## Additive Python contracts

All existing constructor arguments and existing model fields remain usable.

```python
@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: str = "warning"
    resource: str = ""
    attribute: str = ""
    source_file: str = ""
    blocks_analysis: bool = True

# ParsedConfig
diagnostics: list[Diagnostic]       # new list per instance
complete: bool                     # property: no blocking diagnostics

# AnalysisResult
diagnostics: list[Diagnostic]       # parser/coverage plus graph/path diagnostics
paths_truncated: bool = False
path_work: int = 0                  # DFS iterator work, not total runtime
complete: bool                     # no blocking diagnostics or path truncation

# GraphEdge
confidence: str = "modeled"
category: str = "reachability"
source_file: str = ""
remediation: str = ""

# GraphDiff
complete: bool                     # before.complete and after.complete
# Verdict.INCOMPLETE.value == "INCOMPLETE ANALYSIS"
```

`parse_*` adapters populate config diagnostics. A directly constructed
`ParsedConfig` contains only caller-supplied diagnostics until
`config_diagnostics(config)` or `build_graph(config)` validates it. Use the
`AnalysisResult.complete` property for downstream gating, not the default
empty list on an unvalidated hand-built config.

`build_graph` stores diagnostics and sanitized `source_files` in graph metadata.
`analyze` copies diagnostics to its result; it does not mutate the config.
Missing source evidence uses an empty string rather than guessed locations.

### JSON and SARIF contracts

CLI JSON adds:

```json
{
  "analysis_complete": false,
  "analysis": {
    "before": {"complete": true, "paths_truncated": false, "path_work": 0},
    "after": {"complete": false, "paths_truncated": false, "path_work": 0}
  },
  "coverage_diagnostics": [{
    "phase": "after",
    "code": "UNKNOWN_PLAN_VALUE",
    "message": "Plan contains an unknown security-relevant value.",
    "severity": "warning",
    "resource": "aws_security_group.web",
    "attribute": "ingress",
    "source_file": "plan.json",
    "blocks_analysis": true
  }],
  "edge_evidence": []
}
```

`edge_evidence` contains serialized newly added `GraphEdge` values, including
legacy evidence and new properties. Existing keys, including the legacy
`diagnostics` list of source/transport strings, remain unchanged. JSON and
SARIF stdout remain one parseable document on successful analysis.

SARIF adds rule BR004, one result per phase/diagnostic, structured diagnostic
properties, `runs[0].properties.analysisComplete`, and `pathsTruncated`.
Attack-path results include `properties.edgeEvidence`. Physical locations are
relative file paths; logical locations preserve resource addresses.

UI/service consumers must display incompleteness independently of the score or
path count. A REVIEW result has legacy `passed=True` and exit 0 unless strict
review gating is selected; do not equate `passed` with coverage completeness.

## Verification and integration boundary

Meaningful regression cases live in `tests/test_engine_hardening.py` and
`tests/test_coverage.py`. They cover public-access-block flag distinctions,
bucket scoping, conditional policies, anonymous principals, wildcard actions,
object resource scope, write-only IAM evidence, unknown plan values, malformed
policies and plan structures, duplicate addresses, unresolved relationships,
isolated/concurrent analyses, deterministic traversal, exponential dead ends,
depth/output/work/edge budgets, default byte/file/resource/value budgets,
symlinks, diagnostics in all CLI formats, strict review exits, and path privacy.

The original 239 tests remain unchanged, including the safe score 100, vulnerable
single critical path, remediation, plan relinking, CLI, report and demo fixtures.

Run:

```sh
python -m pytest -o addopts='' -q
ruff check blastradius/parser blastradius/graph \
  blastradius/security/{decision,explain,rules,risk_score}.py \
  blastradius/{cli,report,sarif}.py \
  tests/test_engine_hardening.py tests/test_coverage.py
mypy --follow-imports=silent --ignore-missing-imports \
  blastradius/parser blastradius/graph \
  blastradius/security/{decision,explain,rules,risk_score}.py \
  blastradius/{cli,report,sarif}.py
python -m pip wheel . --no-deps --wheel-dir dist
```

Mypy checks the engine modules under the repository's existing dynamic typing;
untyped third-party dependencies are ignored. No new runtime dependencies or
changes to project packaging are required. This handoff owns only the engine,
the two new regression files and these docs. Parent integration owns server/UI
serialization, public onboarding behavior, final UI-driven tests, deployment,
PR publication and the environment blueprint.
