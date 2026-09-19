# GitHub Actions onboarding

## First successful check

1. Copy [github-action.yml](github-action.yml) into the Terraform repository as
   `.github/workflows/blastradius.yml` on a reviewed base branch.
2. Keep default analyzer SHA `a72c04890640102b315506ab85e5f1ccbe91bb9f`.
   A `BLASTRADIUS_REVISION` repository-variable override must be a reviewed full
   40-character SHA with working packaging. Do not use `main`, `latest` or `v1`.
3. For multiple Terraform roots, set `BLASTRADIUS_TERRAFORM_DIR=infra` as a
   repository variable, or commit `terraform_dir: infra` to the trusted policy.
4. Open a controlled Terraform PR. Review the Actions summary, artifact, check
   conclusion and, when allowed, the updated bot comment.
5. Select the resulting `blast-radius` check from the **BlastRadius** workflow
   in branch protection after its first run.

No AWS credentials, PAT or paid account is required. The Actions token needs
`contents: read`; `pull-requests: write` belongs to the trusted report job.
Fork/Dependabot PRs may receive read-only tokens or require approval.
Keep those restrictions; analysis and gate remain useful without comments.

The original compatibility example remains at
[`examples/github-action/blastradius-pr-check.yml`](../examples/github-action/blastradius-pr-check.yml).
The onboarding copy adds explicit action SHA pins and seven-day artifact
retention without changing the historical analyzer revision.

## Trust boundary

The reporting workflow checks out the target's **base SHA**, installs the
reviewed analyzer in a venv, and fetches candidate objects without checking out
candidate files. It runs isolated Python (`-I`) from the runner temporary directory.

Candidate HCL is data. Candidate Python, shell, workflows, Terraform providers,
module downloads and build hooks are not executed in that job.
Fetch/comment tokens are step-scoped; analysis does not export a write token.
PR numbers and SHAs arrive through environment variables, not branch-name shell
interpolation. Do not switch to `pull_request_target` to get write access.

This repository's backend/frontend test jobs **do** execute candidate code,
on ephemeral hosted runners with read-only permissions, no persisted checkout
credentials and no production secrets. Never run these on privileged persistent
self-hosted runners.

Policy comes from the trusted base. Protect workflow/policy changes with review.
SHA pinning does not make compromised dependencies or unreviewed edits safe.

## Reporting

The publisher updates only a comment marked `<!-- blastradius-report -->` and
authored by the GitHub Actions bot. Human look-alike comments are not modified.
It checks the current PR head SHA; per-PR concurrency cancels superseded runs.
GitHub comments do not provide an atomic compare-and-write operation, so the
check reduces stale results but cannot eliminate every last-moment race.

Outputs are `decision`, `security_score_before`, `security_score_after`,
`critical_paths_added`, `sensitive_resources_added`, and `exit_code`.
Unknown counts are blank on errors. Publication is best effort; the final
always-running gate preserves exit 0/1/2. SARIF is an artifact.

Reports can expose topology, ARNs and source evidence. Seven-day retention
applies to onboarding artifacts; logs, summaries and PR comments have separate
GitHub access/retention rules. Do not use real secrets in demo PRs.

## Acceptance and troubleshooting

Historical same-repository acceptance is linked in the
[README](../README.md#github-actions). Fork/private repositories still require
hosted acceptance. Live publisher tests need separate approval.

| Symptom | Check |
|---|---|
| Exit 2 | Root selection, missing inputs, policy validity, full Git history |
| No comment | Fork restrictions, permissions, current head SHA; read artifact |
| Pending check | Required-check name and triggers; avoid Terraform-only path filters |
| Install failure | Reviewed full SHA and network; never fall back to candidate code |
| Unexpected pass | Coverage diagnostics, policy, exact base/head SHAs |

## Action pins

Upstream tags and `action.yml` were inspected for these pins:

| Action | Reviewed tag | Commit |
|---|---|---|
| `actions/checkout` | v4.2.2 | `11bd71901bbe5b1630ceea73d27597364c9af683` |
| `actions/setup-python` | v5.6.0 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/setup-node` | v4.4.0 | `49933ea5288caeca8642d1e84afbd3f7d6820020` |
| `actions/upload-artifact` | v4.6.2 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |

Review upstream changes before updates. These pins still need future security maintenance.
