# Customer sample: one SSH change, one new modeled path

**Your Terraform diff shows what changed. BlastRadius shows what became reachable.**

This is synthetic evidence for a private-beta conversation, not a customer result.
No AWS credentials, live infrastructure, Terraform execution or GitHub publication
are involved. Do not apply these fixtures: the AMI is deliberately fictitious.
This bundle uses the actual installed CLI and preserves its output formats.

## Open the evidence

| Item | File |
|---|---|
| BEFORE Terraform | [before/main.tf](../examples/customer/before/main.tf) |
| AFTER Terraform | [after/main.tf](../examples/customer/after/main.tf) |
| Attack-path report | [console.txt](../examples/customer/output/risky/console.txt) |
| Markdown | [report.md](../examples/customer/output/risky/report.md) |
| JSON | [result.json](../examples/customer/output/risky/result.json) |
| SARIF | [results.sarif](../examples/customer/output/risky/results.sarif) |
| Trusted demonstration policy | [policy.yml](../examples/customer/policy.yml) |
| Engine-generated patch | [remediation.patch](../examples/customer/remediation.patch) |
| Repaired candidate | [remediated/main.tf](../examples/customer/remediated/main.tf) |
| Remediation rerun | [report.md](../examples/customer/output/remediated/report.md) |
| Incomplete input / strict result | [review/main.tf](../examples/customer/review/main.tf) / [result.json](../examples/customer/output/review-strict/result.json) |
| Actual invocation arguments and exits | [manifest.json](../examples/customer/manifest.json) |

Each case under `examples/customer/output/` contains `report.md`, `summary.md`,
`result.json`, `results.sarif` and captured CLI `console.txt`. The short Markdown
report summarizes the path; the SARIF `BR001` result contains all five hop
evidence records. Top-level JSON `edge_evidence` describes newly added edges;
it is not the full list of unchanged relationships traversed by the new path.

## The one-line change

The BEFORE and AFTER files differ only in the TCP/22 ingress CIDR:

```diff
-    cidr_blocks = ["10.0.0.0/24"]
+    cidr_blocks = ["0.0.0.0/0"]
```

HTTPS remains restricted to the sample's internal load-balancer subnet.
Public egress is unchanged. The separate canonical `examples/safe` and
`examples/vulnerable` fixtures are not modified by the generator.
The explicit policy blocks new critical paths, sensitive exposure and public
administrative ingress. Its public-HTTPS allowance does not exempt critical paths.

## Read each hop

```text
INTERNET
  → aws_security_group.web
  → aws_instance.web_server
  → aws_iam_role.app
  → aws_s3_bucket.customer_data
  → sensitive_data.customer_data
```

| Hop | Evidence in the sample | Meaning and boundary |
|---|---|---|
| Internet → security group | TCP/22 from `0.0.0.0/0`; `INGRESS_ALLOWS`, confidence `modeled` | Public administrative ingress in the model. Does not establish a public IP, a route, a listening service or a successful SSH login. |
| Security group → EC2 | `vpc_security_group_ids = [aws_security_group.web.id]`; `PROTECTS`, `modeled` | Terraform explicitly attaches the group. Routing, NACLs and other network controls are not resolved. |
| EC2 → IAM role | `iam_instance_profile = aws_iam_instance_profile.app.name`, profile → role reference; `ASSUMES_ROLE`, `conditional` | A compromised instance may obtain role credentials. The analyzer does not compromise compute or prove metadata access. |
| IAM role → S3 | Inline policy allows `s3:GetObject` and `s3:ListBucket` on the bucket and object ARNs; `CAN_ACCESS`, `conservative` | Modeled data-read authorization. This is not an effective-IAM evaluation including all denies, conditions, organization controls or KMS permissions. |
| S3 → sensitive data | `Sensitive = "true"`; `CONTAINS`, `modeled` | Classification supplied by the fixture, not a scan of bucket contents. The last node represents impact, not another AWS resource. |

Each hop is modeled evidence, not proof of successful exploitation. All physical
SARIF locations are `main.tf`, relative to the candidate root. The engine provides
resource addresses and evidence; it does not invent source line numbers.
`analysis_complete: true` means complete within the documented model and selected
input. Read [coverage](coverage.md) and [limitations](limitations.md).

## Regenerate with the installed package

From the repository root, using the project Python 3.12 environment:

```bash
make install-core
.venv/bin/python -I scripts/generate_customer_samples.py
.venv/bin/python -m pytest tests/test_customer_samples.py
```

The [generator](../scripts/generate_customer_samples.py) derives the candidate with
the existing ingress editor, calls the existing remediation helper, then invokes
`python -I -m blastradius.cli` in six subprocesses. `-I` prevents accidental imports
from the working directory. `--report-dir` produces all formats from each analysis.
The interpreter is the same interpreter used to run the generator.

Paths passed to analysis are relative to the sample root. The manifest records
actual arguments, version, a content digest of the relevant installed analyzer
modules and observed exits; it contains no timestamp or local checkout path.
Generator output is byte-compared to this bundle by the regression tests.
After an engine change, reinstall, regenerate and review changed evidence rather
than editing generated reports. `--output /your/local/directory` writes a fresh
bundle elsewhere using the committed baseline and policy as inputs.

To rehearse individual comparisons in Bash:

```bash
source .venv/bin/activate
cd examples/customer

run_expected() {
  expected="$1"
  shift
  actual=0
  python -I -m blastradius.cli "$@" || actual=$?
  test "$actual" -eq "$expected"
}

run_expected 0 --before before --after before --policy policy.yml --fail-on-review &&
run_expected 1 --before before --after after --policy policy.yml --fail-on-review &&
run_expected 0 --before after --after remediated --policy policy.yml --fail-on-review &&
run_expected 0 --before before --after review --policy policy.yml &&
run_expected 1 --before before --after review --policy policy.yml --fail-on-review &&
run_expected 2 --before before --policy policy.yml
```

The last command deliberately omits AFTER to exercise usage error exit 2.
Do not copy the `run_expected` wrapper into a merge gate: it is a rehearsal that
accepts intentionally failing scenarios. In CI, preserve the analyzer's real exit.

## Expected decisions and interpretation

| Case | Decision text preserved from CLI | Exit | Interpretation |
|---|---|---:|---|
| Baseline → baseline | `SAFE TO MERGE` | 0 | No new modeled blocking findings detected. Score 100 → 100. |
| Baseline → risky | `BLOCK CHANGE` | 1 | One new critical path; one newly reachable sensitive bucket. Score 100 → 20. |
| Risky → repaired | `SAFE TO MERGE` | 0 | No new modeled blocking findings detected. Critical path removed; score 20 → 100. |
| Baseline → unexpanded module | `REVIEW REQUIRED` | 0 by default | Incomplete analysis, even though score stays 100. Review is advisory without the strict flag. |
| Same incomplete input, `--fail-on-review` | `REVIEW REQUIRED` | 1 | Strict gate fails; diagnose and resolve the missing module coverage. |
| Missing AFTER | `ERROR` | 2 | No completed analysis or merge-safety conclusion; counts are unknown, not zero. |

The legacy JSON `passed` field can be `true` for REVIEW, including strict REVIEW
with `exit_code: 1`. Consumers must inspect `decision`, `analysis_complete` and
`exit_code`, not that boolean or the score alone. Incomplete analyses can also
block when known evidence is already sufficient; do not suppress their findings.
Use `--fail-on-review` when CI must fail on any REVIEW result.

The remediation helper returns TCP/22 to the synthetic private CIDR while leaving
egress and HTTPS unchanged. It writes local files only. A real team must select
its authorized administrative access design; `10.0.0.0/24` is not a universal
recommendation. Re-analysis checks the proposed edit without applying Terraform.

## Reproduce full screenshots

These are instructions for the integrated build's acceptance operator. This
bundle does not contain screenshots and does not assert browser acceptance.
Never substitute a mockup, another revision's graph or edited decision text.

1. Record the checkout SHA, installed engine version, scenario and viewport in
   the capture notes. Regenerate this bundle. Start the local application using
   [getting started](getting-started.md); use synthetic data and local demo auth
   only in the documented development environment.
2. For captures of this exact bundle, create a project and open **HCL files**.
   Select `before/main.tf` for **Baseline** and the same file for **Candidate**.
   Set descriptive labels, select **Analyze change**, wait for completion, and
   capture the decision with its coverage context.
3. Submit `before/main.tf` against `after/main.tf`. Capture **Responsible change**,
   expand `main.tf` under **Source changes**, and select the **After** graph.
   Expand the attack-path evidence. Capture all hops over additional full
   screenshots if they do not fit; retain the model caveat and surrounding UI.
4. Capture **Review the remediation** with **Inspect supported patch** expanded.
   Submit `after/main.tf` as baseline and `remediated/main.tf` as candidate for a
   separate real rerun. Capture the resulting decision and removed path count.
5. Capture **Export this analysis**. JSON and Markdown are available on Free;
   saved SARIF needs the documented operator entitlement. The committed CLI
   SARIF remains available without it. Do not hide an entitlement error.
6. If demonstrating the built-in public SSH scenario instead, label it as that
   separate fixture: **Simulate risky change**, **Remediate & re-analyze**, and
   **Reset baseline** operate the bundled demo, not uploaded files.
7. Use a maximized browser, 100% zoom and full uncropped screenshots. Record
   actual viewport size; repeat responsive captures at widths
   320/375/768/1024/1440 during acceptance. Preserve visible failure states.
   Do not crop out warnings or silently repair overflowing UI in image editing.
   Save captures outside the committed generated bundle and label the tested SHA.

For a terminal-only capture, show the actual `console.txt` or rerun the matching
command with the full terminal visible. Caption it as CLI evidence, not a browser
test. For delivery, use the [demo script](demo-sales.md); start beta evaluation
with the [beta guide](beta-guide.md).
