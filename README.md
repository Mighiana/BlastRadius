# BlastRadius

**Your Terraform diff shows what changed. BlastRadius shows what became reachable.**

Attack-path diff for Terraform pull requests. Compare a baseline and proposed
change, see new modeled paths to sensitive resources, inspect Terraform evidence,
and export a review report.

[Try the legacy demo](https://blastradius.streamlit.app/) ·
[Install](#installation) · [GitHub check](#github-actions) ·
[Demo script](docs/demo.md) · [Documentation](docs/index.md)

```bash
python -m blastradius.cli --before examples/safe --after examples/vulnerable
# BLOCK CHANGE · one new modeled critical path · exit 1 (expected)
```

The network demo changes one SSH CIDR:
`10.0.0.0/24 → 0.0.0.0/0 → Internet → EC2 → IAM role → sensitive S3 data`.
Restore the restricted CIDR and re-analyze: **BLOCK CHANGE → SAFE TO MERGE**.
“SAFE TO MERGE” means **No new modeled critical attack paths detected** under
the selected policy. It does not prove AWS infrastructure is safe.

The public URL is the **legacy Streamlit demonstration**, not the new application.
No new public deployment is claimed. Current screenshots will be added after
integrated browser verification; none are fabricated.

## The problem

A small network or IAM diff can connect resources that were previously
unreachable. BlastRadius compares the resulting graphs so a reviewer can see the
connection and its evidence.

## Installation

Use **Python 3.12** for the verified development baseline (the CLI supports 3.11+).
Git is needed for repository comparisons; AWS credentials and Terraform are not.

```bash
git clone https://github.com/Mighiana/BlastRadius.git
cd BlastRadius
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install .
blastradius --before examples/safe --after examples/safe
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell.
For the legacy demo, tests and quality tools, use `make install-core` on Linux/macOS.

### Application workspace

The delivery architecture is React/TypeScript + Vite in `web/`, FastAPI at
`blastradius.server.app:app`, PostgreSQL for deployment, and SQLite for local use.
The Python analysis engine remains reusable independently.

```bash
cp .env.example .env
make dev
```

This installs `.[server,ui,dev]`, checks and builds the frontend, migrates SQLite,
and serves the application at `http://localhost:8000`. It requires Python 3.12,
Node 22.12+ or 24, npm and Make. The example enables disposable local demo
accounts; OIDC and billing are disabled until explicitly configured.
Run `make compose-up` instead for the local PostgreSQL container setup.
See [deployment](docs/deployment.md) and the [integration contract](docs/release-integration.md).

For the previously published CLI consumer revision:

```bash
python -m pip install "git+https://github.com/Mighiana/BlastRadius.git@a72c04890640102b315506ab85e5f1ccbe91bb9f"
```

No PyPI package or `v1` tag is published. This immutable historical source pin is
retained until a new release is reviewed and approved.

## Running

### Dashboard

`make legacy` installs and starts the legacy Streamlit demo on loopback.
Use the three bundled scenarios and the guided SAFE → BLOCK → SAFE flow.
Do not upload confidential infrastructure to the public demonstration.

### Streamlit Community Cloud

The [existing demo](https://blastradius.streamlit.app/) uses `app.py` and the root
`requirements.txt`. Its deployment is separate from this delivery.
Dependency pins describe the checkout, not proof of what a hosted instance runs.
New deployment and live publisher tests require owner approval.

### CI mode

CLI exits: **0** passes the configured gate; **1** blocks; **2** means invalid or
incomplete analysis. REVIEW passes by default; `--fail-on-review` makes it fail.
JSON, SARIF, Markdown and summary reports are supported.
See the [CLI guide](docs/cli.md).

### Analyze local Git changes

```bash
blastradius --repo /path/to/repo --base main --head feature/change --terraform-dir infra
```

Committed snapshots are read without switching the working tree.
Git mode trusts policy from the base revision.

### Analyze Terraform plan JSON

```bash
blastradius --plan examples/plans/ssh_open_plan.json --format json
```

The bundled plan returns exit 1. Supply already-produced plan JSON; BlastRadius
does not run Terraform providers, download modules or contact AWS.

### Repository policy

Use a reviewed base-branch `blastradius.yml` to configure the Terraform root and
gate. Invalid policy fails with exit 2. See [policy examples](docs/cli.md#repository-policy).

### GitHub Actions

Copy [the onboarding workflow](docs/github-action.yml) into your Terraform
repository's `.github/workflows/blastradius.yml`, then follow
[GitHub onboarding](docs/github-actions.md). It analyzes one root, preserves the
reviewed analyzer pin, uploads reports, and updates one bot comment when permitted.
Make the check required in branch protection yourself.

The analyzer runs from a trusted revision; the privileged reporting flow does
not execute candidate code or providers.

Hosted PR analysis and comment updates are verified **for the historical
same-repository acceptance only**:
[BLOCK run 35441550348](https://github.com/Mighiana/BlastRadius/actions/runs/35441550348),
[SAFE run 35441968970](https://github.com/Mighiana/BlastRadius/actions/runs/35441968970),
and [the same updated comment 5741664556](https://github.com/Mighiana/BlastRadius/pull/1#issuecomment-5741664556).
Fork/read-only-token behavior remains locally tested, not hosted-verified.
No fresh GitHub API write was used to prepare this handoff.

### SARIF findings

`--format sarif` emits SARIF 2.1.0 with resource evidence and known filenames,
without guessed line numbers. A blocking result still emits a valid document
and exits 1. Code-scanning uploads are not automatic.

### Tests

```bash
make install
make check
```

See [Contributing](CONTRIBUTING.md) for lint/types, frontend checks and audits.
The original baseline has 239 tests; the integrated report must record the final count.

## Architecture

The [architecture guide](docs/architecture.md) separates the Python engine from
API, identity, storage and browser concerns.

### Pipeline

HCL / plan / Git snapshots → normalized resources → evidence-bearing graph →
before/after diff → policy decision → reports and remediation suggestions.

## Supported Terraform resources

The baseline models security groups, EC2, instance profiles, IAM roles and
selected S3 permissions/exposure. See [coverage priorities](docs/roadmap.md).

## Attack-path logic

A path records a modeled connection from the internet to a resource tagged
sensitive. A detected path is not evidence that exploitation occurred.

### Merge decision

BLOCK identifies new modeled critical paths or configured policy violations.
REVIEW identifies changes needing inspection. Inspect diagnostics with every report.

### Security score

The 0–100 score is a deterministic heuristic, not a probability of compromise.
Higher is better within the same model version.

## Demo workflow

Follow the [three-scenario script](docs/demo.md) for network, IAM and storage
examples, expected exits and remediation boundaries.

### Demo scenarios

All three use committed synthetic Terraform. Network and public bucket examples
support local patch suggestions; IAM remediation needs a reviewer.

### Screenshots

Verified screenshots and recordings belong to the integrated release evidence.
The parent release process owns that evidence.

## Limitations

The AWS model is intentionally incomplete. Unsupported inputs, IAM semantics and
network topology require manual review. Sensitivity tags are declarations, not
data discovery. No score or passing result guarantees safety.
See [threat model](docs/threat-model.md), [roadmap](docs/roadmap.md), and
[integration limits](docs/release-integration.md).

## Implemented versus simulated

The CLI, graph diff, reports and three synthetic scenarios perform real local
analysis. The historical hosted Actions acceptance is linked above. React/API,
authentication, persistence and sandbox billing need integrated verification.
The release scaffolding does not establish that they work.
The GitHub App is a [future design](docs/github-app-design.md).

## Future roadmap

Finish integrated acceptance and deployment validation; validate tenant isolation
and retention; expand supported AWS relationships with evidence and tests; then
review commercial launch and a versioned release. See [roadmap](docs/roadmap.md).

[Security disclosure](SECURITY.md) · [Support](docs/support.md) ·
[Privacy template](docs/privacy.md) · [Terms template](docs/terms.md)
