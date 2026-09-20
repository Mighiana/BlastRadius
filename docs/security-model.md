# BlastRadius static security model

## Meaning of a result

BlastRadius compares two finite, directed graphs constructed from Terraform source
or saved `terraform show -json` data. It never applies Terraform, evaluates HCL,
loads providers, downloads modules, calls AWS, or proves exploitability.

The modeled chain is:

```
INTERNET -> SECURITY_GROUP -> EC2 -> IAM_ROLE -> S3_BUCKET -> SENSITIVE_DATA
INTERNET -------------------------------------> S3_BUCKET -> SENSITIVE_DATA
```

An edge means a possible relationship supported by the documented rules below.
An attack path is a simple directed path starting at `INTERNET`. A critical path
ends at a bucket's sensitivity marker. Sensitive-resource reachability uses a
full graph traversal independently of bounded path enumeration. It therefore
remains available when a path is too long or enumeration stops.

These are conservative attack hypotheses: public ingress does not prove an
instance has a public IP, a usable route, a vulnerable service, or exploitable
software. An instance profile does not prove metadata credentials are accessible.
A tag-based sensitive classification does not inspect bucket contents.

The 0–100 score is a deterministic heuristic over modeled findings. **100 is
not a security certification**, including when the model is incomplete.

## Rules and evidence

| Edge | Evidence and limitations |
|---|---|
| `INGRESS_ALLOWS` | Inline security-group ingress with literal `0.0.0.0/0` or `::/0`. SSH/RDP and all-protocol rules have elevated severity. Other source CIDRs, prefix lists, routes, NACLs and SG hops are outside the reachability model. |
| `PROTECTS` | Instance references a modeled security group. This is an attachment, not an effective routing determination. |
| `ASSUMES_ROLE` | Instance -> instance-profile -> modeled IAM-role references (the legacy direct role-reference form also remains accepted). Credential theft is conditional on compromise and metadata access. Trust policy evaluation is not implemented. |
| `CAN_ACCESS` | An inline or attached modeled IAM policy allows an S3 action targeting a modeled bucket or a wildcard. An upper bound on possible privilege, not AWS's effective permission decision. |
| `PUBLIC_ACCESS` | Anonymous object-read bucket ACL or bucket policy, subject to the limited public-access-block rules below. |
| `CONTAINS` | Existing sensitivity heuristics over tags/names create a marker. No content inspection or data discovery occurs. |

Every graph-builder edge retains `terraform_resource`, `evidence`, `reason`,
`risk`, and `metadata`, and adds `confidence`, `category`, `source_file`, and
`remediation`. `source_file` is a relative filename/path, never an absolute
worker path. `confidence` is `modeled`, `conditional`, or `conservative`; these
are qualitative labels, not numeric probability estimates. Categories include
`exposure`, `reachability`, `privilege`, `data_access`, and `impact`.

The graph remains a `networkx.DiGraph`: parallel reasons for one source/target
pair collapse to the highest-risk edge; ties preserve the first reason. The
retained evidence is an explanation, not an exhaustive list of every grant.

### IAM compatibility and uncertainty

Existing broad IAM `CAN_ACCESS` edges are retained for compatibility, including
write/list-only S3 privileges. Such an edge has `category="privilege"` and
`metadata["data_read"]=False`. A path through that edge is **not a claim that an
object can be read or exfiltrated**. An action matching `s3:GetObject` or
`s3:GetObjectVersion` sets `data_read=True`, but effective authorization still
requires separate verification. This preserves the existing scoring/demo
contract while making the permission evidence honest.

IAM `Condition`, explicit `Deny`, `NotAction`, `NotResource`, `NotPrincipal`,
permission boundaries, unavailable managed-policy contents, role inline-policy
blocks and other unsupported controls produce coverage diagnostics. Explicit
deny precedence, SCPs, session policies, cross-account evaluation, trust
policies, and resource-policy/identity-policy intersections are not evaluated.
Known `Allow` edges can remain as possible paths even when a deny or condition
could remove them. Such graphs are incomplete; they cannot receive SAFE.

Only AWS-style `*` and `?` wildcards are matched; shell character classes are
not treated as IAM wildcards. Principal `"*"` and `{"AWS":"*"}` (including a
wildcard in the AWS principal list) represent anonymous callers. Service
principals and partial wildcard account ARNs are not anonymous callers.
Malformed/partial wildcard principals are diagnosed.

### S3 public access

`public-read` and `public-read-write` ACLs permit anonymous reads in the model.
`authenticated-read` is not anonymous: it produces a diagnostic for AWS
authenticated-user access rather than an `INTERNET` edge.

For bucket policies, the model requires an `Allow`, anonymous principal, a
matching object-read action, and a `Resource` covering at least one object in
that bucket. List/write/delete/ACL-metadata actions alone do not create public
data-read edges. Bucket-only ARNs do not authorize object reads. Object prefixes
and wildcard bucket patterns mean possible access to some objects, not every
object in a bucket.

| Bucket public-access-block flag | Modeled effect on existing grants |
|---|---|
| `block_public_acls` | Does **not** erase existing ACL grants. AWS rejects new public ACL requests. |
| `ignore_public_acls` | Suppresses existing anonymous ACL-derived edges. |
| `block_public_policy` | Does **not** erase existing policy grants. AWS rejects new public policy requests. |
| `restrict_public_buckets` | Suppresses unconditional anonymous bucket-policy edges. |

Controls apply only to their referenced bucket and only when a flag is the
known boolean `True`. Unknown flags cannot suppress edges. Multiple conflicting
control resources are diagnosed and do not suppress access. An access block
does not suppress identity-policy edges.

Conditional bucket policies stay conservative: S3's complete classification of
a policy as public is not implemented. The engine therefore retains possible
conditional edges even with `restrict_public_buckets`, marks their confidence
conditional, and requires review. Account/organization-level public access
blocks, Object Ownership, access points and ACL grant blocks are not modeled.
A proposed public grant plus a creation-block flag may fail during apply; the
engine models possible existing exposure rather than predicting apply success.

AWS references:

- [S3 public access block settings](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [IAM Principal element](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_principal.html)
- [IAM Action element](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_action.html)
- [IAM policy evaluation logic](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html)

## Incomplete results and gating

`Diagnostic.blocks_analysis=True` means a security-relevant gap. Unsupported
security resources, unresolved links/expressions, unknown plan values, malformed
policies, duplicate addresses, and truncated graphs/paths all prevent SAFE.
An unsupported `aws_cloudwatch_log_group` is currently informational; broader
AWS resources are conservatively blocking diagnostics.

`decide(compare(before, after))` returns BLOCK for configured blocking findings,
then at least REVIEW if either phase is incomplete. A missing old/new path in
an incomplete graph cannot establish remediation. `GraphDiff.verdict` is
`INCOMPLETE ANALYSIS` unless an observed sensitive reachability/path regression
already establishes `SECURITY REGRESSION`.

Legacy process exit behavior is preserved: REVIEW exits 0 by default;
`--fail-on-review` makes it exit 1. **Use `--fail-on-review` in a strict merge
gate.** Invalid/oversized inputs exit 2 and are not presented as SAFE. No policy
toggle can convert incomplete analysis to SAFE.

Both phases' diagnostics appear in CLI summary, Markdown, JSON and SARIF. JSON's
existing `diagnostics` string list is retained for source/transport notes;
`coverage_diagnostics` carries structured engine diagnostics with phase.
SARIF rule `BR004` reports coverage gaps; existing BR001–BR003 remain unchanged.
Markdown displays at most 100 diagnostics per phase and directs readers to
the full JSON/SARIF output. Reports never guess source line numbers.

## Isolation and service integration

Parsing plan values deep-copies caller input before relationship recovery.
Graph nodes copy resource attributes so analyses do not share mutable graph
state. Diagnostics are immutable values on each config/result. `analyze` uses
a local deterministic rule explainer, independent of the legacy module-wide
custom-explainer setter; existing direct explainer APIs remain available.

Parsers and graph analysis are synchronous, bounded offline helpers, not a
service sandbox. A hosted service still needs input size quotas before parsing,
worker time/memory limits, authentication/authorization, safe archive handling,
rate limits and artifact access controls. Terraform values can contain secrets;
do not publish raw graph attributes or plan contents by default.

See [coverage and API contracts](coverage.md) for concrete limits and integration
fields. Engine tests do not certify browser, multi-user service, deployment,
provider behavior, hosted Actions permissions or production readiness.
