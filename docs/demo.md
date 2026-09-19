# Three-scenario demo

**Audience:** infrastructure reviewer, recruiter or security engineer.
**Inputs:** bundled synthetic Terraform. No AWS credentials, plan execution,
provider installation or live GitHub publication is needed.

[Read an actual CLI-generated report](sample-report.md) for the network-exposure
scenario below. It uses only the repository's synthetic fixtures; it is not a
customer result or a screenshot of the new application.

## Two-minute narrative

“This diff changes one SSH CIDR. The interesting result is what the change
connects: internet → instance → IAM role → sensitive bucket. BlastRadius compares
the modeled paths before and after, shows each hop's evidence and gives a merge
decision. It is an incomplete static model, not proof of exploitability or safety.”

In the integrated UI, select a bundled scenario, show the baseline and candidate,
open the new path/evidence, inspect the change, then review remediation and
re-analyze. Use the actual integrated button labels; the release-only unit has
not verified them. Legacy Streamlit's network flow uses **Demo Mode → Restore safe
configuration → Simulate risky change → Generate Safer Configuration & Re-analyze**.

## Reproducible CLI rehearsal

```bash
make install-core
PYTHON=.venv/bin/python bash scripts/verify-demo.sh
```

The script exercises baseline, risky and restored inputs for all three scenarios.
Expected CLI exits are **0 → 1 → 0**. Restoring the committed baseline demonstrates
the original configuration again; it does not pretend every scenario has an
automatic patch.

### 1. Network exposure

```bash
.venv/bin/python -m blastradius.cli --before examples/safe --after examples/vulnerable --format pr
```

Expected BLOCK, one new critical path. The files differ by exactly one SSH CIDR
line, guarded by the original tests. Show the security-group evidence, EC2
instance profile, IAM-to-S3 connection and sensitivity tag.
The baseline legacy score is 100 → 20; verify any changed model's current score
before putting it in a screenshot. The narrow-CIDR patch is a local suggestion,
not an AWS change and not a universally correct corporate CIDR.

### 2. IAM expansion

```bash
.venv/bin/python -m blastradius.cli \
  --before examples/scenarios/broad_iam/before \
  --after examples/scenarios/broad_iam/after --format pr
```

The candidate changes `s3:PutObject` on one bucket to `s3:*` on `"*"`.
The public 443 listener is intentional; the new critical connection is
authorization to sensitive storage. Explain why “close every public port” is
the wrong remediation. Narrow IAM actions/resources through review.
Do not claim the existing patcher repairs arbitrary IAM semantics.
The restored baseline remains MEDIUM and is labeled REVIEW REQUIRED by the
baseline engine, with exit 0 under the default policy; it is not a zero-risk result.

### 3. Sensitive storage

```bash
.venv/bin/python -m blastradius.cli \
  --before examples/scenarios/public_bucket/before \
  --after examples/scenarios/public_bucket/after --format pr
```

Changing bucket ACL `private` to `public-read` creates a direct modeled
internet → bucket → sensitive-data path. No EC2 hop is required.
Demonstrate restoring private access and re-analyzing; explain public-access-block,
policy and other AWS semantics according to current coverage diagnostics.

## Exports and evidence

Add `--report-dir reports/network` to a comparison to produce JSON, SARIF,
summary and marked Markdown from the same analysis. The risky command still exits
1. Do not commit private reports or use live publisher commands in rehearsal.

The historical [acceptance PR](https://github.com/Mighiana/BlastRadius/pull/1)
demonstrates one bot comment changing from BLOCK to SAFE. It is a historical
example, not a new release acceptance. Do not alter or merge it.

Parent release testing owns screenshots at 320/375/768/1024/1440, no horizontal
overflow, bounded graph, keyboard navigation, loading/error states and export
checks. Use only real captures from the tested revision. A CLI rehearsal does not
establish browser responsiveness, tenant isolation or production readiness.
