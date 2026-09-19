# CLI and repository policy

Run these from the checkout after `make install-core`; activate `.venv` first.

| Input | Example |
|---|---|
| Safe comparison | `blastradius --before examples/safe --after examples/safe` |
| Blocking comparison | `blastradius --before examples/safe --after examples/vulnerable` |
| Git snapshots | `blastradius --repo /path/to/repo --base main --head feature/change --terraform-dir infra` |
| Existing plan JSON | `blastradius --plan examples/plans/ssh_open_plan.json` |

Git mode resolves refs to SHAs, reads snapshots without switching the working
tree, and ignores uncommitted changes. Choose one Terraform root. Multiple roots
without a selector, missing inputs and malformed policy are errors, not passes.
The baseline does not recursively execute module/provider code.

For a plan already generated in a trusted environment,
`terraform show -json plan.out` produces JSON. This can expose secret values.
Do not generate plans from untrusted PRs inside privileged workflows.

## Reports and exit codes

```bash
blastradius --before examples/safe --after examples/vulnerable --format json
blastradius --before examples/safe --after examples/vulnerable --format sarif
blastradius --before examples/safe --after examples/vulnerable --report-dir reports
```

These intentionally exit **1** for the risky change. Exit **0** passes the
configured gate, including REVIEW unless `--fail-on-review` is set.
Exit **2** means invalid/incomplete analysis. Preserve nonzero exits in CI.
A failed report must never be represented as zero findings.

`--report-dir` emits `report.md`, `summary.md`, `result.json` and `results.sarif`
from one analysis. `--comment-file` only writes a file. The
`blastradius-comment` publisher performs real GitHub writes and needs separate
approval for live acceptance testing.

SARIF rules are `BR001` (critical path), `BR002` (noncritical exposure) and
`BR003` (blocking gate). Known files/addresses are emitted without invented lines.
JSON/SARIF stdout is one parseable document. Inspect coverage warnings.

## Repository policy

```yaml
version: 1
terraform_dir: infra
gate:
  block_new_critical_paths: true
  block_new_sensitive_exposure: true
  block_public_admin_ports: true
allowed:
  public_https: true
thresholds:
  minimum_security_score: 70
```

Confirm schema changes against `blastradius/policy.py` and its tests.
Policy does not remove edges, hide findings or change scores. Public HTTPS is
not an exemption for a critical path through that listener.

No policy retains the legacy context-aware decision: new critical paths and
sensitive exposure block; other new exposure requires review. An explicit policy
enables standalone public-admin-port blocking by default. A minimum score checks
the absolute candidate score.

Git input trusts only the base commit's repository-root `blastradius.yml`, unless
an operator explicitly supplies `--policy` as a trusted override. Directory mode
checks BEFORE then the working directory; plan mode checks the plan's parent
then the working directory. Protect policy edits with review and branch protection.

## Private inputs

Run private inputs locally or in controlled CI. Terraform plans, source evidence
and graph reports can contain secrets or reveal internal topology.
Set report retention appropriate to repository access.
See [coverage priorities](roadmap.md) and [data lifecycle](data-lifecycle.md).
