# BlastRadius

**Your Terraform diff shows what changed. BlastRadius shows what became reachable.**

Attack-path diff for Terraform pull requests.

BlastRadius compares Terraform snapshots, models supported AWS relationships,
and explains new paths to sensitive resources with evidence. The commercial-beta
application adds private workspaces, projects, persistent analyses, history,
policies and GitHub PR checks around the existing Python engine.

[Get started](docs/getting-started.md) · [Documentation](docs/index.md) ·
[Beta welcome](docs/beta-welcome.md) · [Private-beta guide](docs/beta-guide.md) · [Customer samples](docs/customer-samples.md) ·
[GitHub App](docs/github.md) · [Actions](docs/github-actions.md) ·
[Readiness and launch blockers](docs/readiness.md)

The [public Streamlit demo](https://blastradius.streamlit.app/) is the public
interactive demo of the analyzer. The multi-user platform is currently in
private beta.

## Quickstart

Use Python **3.12**, Node **24.19.0**, npm, Git and Make on Linux/macOS.
Neither AWS credentials nor Terraform execution is required.

```bash
git clone https://github.com/Mighiana/BlastRadius.git
cd BlastRadius
source "$HOME/.nvm/nvm.sh"
nvm install "$(cat web/.nvmrc)"
nvm use "$(cat web/.nvmrc)"
cp .env.example .env
make dev
```

Open `http://localhost:8000`. This installs dependencies, checks/builds the React
app, migrates a local SQLite database and starts one API process. Demo sign-in
creates a disposable local identity and a Free workspace; public scenarios need
no login. Use the exact configured browser origin. See
[getting started](docs/getting-started.md) for uploads, plan assignment and checks.

Production identity requires [OIDC configuration](docs/auth.md).
**Payments are unavailable.** Pro/Team prices are proposals; operators can grant
beta entitlements with an audited local CLI. There is no checkout, payment SDK,
payment webhook, card collection or subscription activation.
See [plans](docs/billing.md) and [future billing](docs/billing-future.md).

## What you can do

- Compare bounded HCL snapshots or saved Terraform plan JSON; inspect graphs,
  path evidence, coverage diagnostics, findings and remediation guidance.
- Organize private projects, archive/restore them, retain history, and export
  JSON/Markdown plus entitled SARIF.
- Manage owner/admin/developer/viewer roles, verified-email invitations,
  sessions, trusted policies and plan usage.
- Connect an operator-verified GitHub App installation for persistent PR
  analysis, stale-commit checks and app-owned checks/comments.
- Keep using the independent CLI, trusted Actions workflow and public demo.

Some capabilities require plan entitlements or operator/provider configuration.
[Readiness](docs/readiness.md) distinguishes implementation from external
acceptance and lists missing enterprise features.

## CLI and GitHub Actions

For the CLI alone:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install .
blastradius --before examples/safe --after examples/vulnerable
blastradius --plan examples/plans/ssh_open_plan.json --format json
```

Both examples intentionally block and return **1**. Exit **0** passes the
selected gate; **2** means invalid input or usage. REVIEW passes by default;
use `--fail-on-review` for strict gating. Git comparisons read committed data
without switching the working tree and trust policy from the base revision.
See the [CLI](docs/cli.md), [policy](docs/policy.md) and [report](docs/reports.md) guides.

### GitHub Actions

Copy the [reviewed consumer workflow](docs/github-action.yml) using
[Actions onboarding](docs/github-actions.md). Its immutable historical analyzer
pin remains `a72c04890640102b315506ab85e5f1ccbe91bb9f` until a new release is
approved; it does not automatically adopt this source branch. The
[GitHub App](docs/github.md) is a separate operator-managed integration.
Neither flow executes candidate code, providers or workflows.

No PyPI package or `v1` tag is published.
Hosted PR analysis and comment updates are verified for the historical
same-repository [BLOCK run 35441550348](https://github.com/Mighiana/BlastRadius/actions/runs/35441550348)
and [SAFE run 35441968970](https://github.com/Mighiana/BlastRadius/actions/runs/35441968970);
[comment 5741664556](https://github.com/Mighiana/BlastRadius/pull/1#issuecomment-5741664556)
was updated rather than duplicated. These are historical acceptance results,
not a new integration run. Fork/read-only-token behavior remains locally tested.

## Architecture

React/TypeScript + Vite → FastAPI → SQLAlchemy/PostgreSQL (SQLite locally).
Authenticated requests authorize workspace membership, reserve quota, and store
an immutable policy snapshot before a bounded background job launches the
installed engine with isolated Python. Results persist with normalized findings,
paths, artifacts and provenance. Every read/export repeats tenant and retention
checks. Node builds static assets; it is absent from the application runtime.

Use **one ASGI process per database**. The queue is in memory; interrupted jobs
fail closed on restart. This is not a distributed/high-availability service.
See [architecture](docs/architecture.md), [deployment](docs/deployment.md) and
[operations](docs/operations.md).

## Security and model limits

“SAFE TO MERGE” means no new modeled blocking findings under the selected policy.
It does **not** prove infrastructure is secure. Incomplete coverage requires
review even when no path is found. Scores are heuristics, not exploit probabilities.

Only the documented [AWS resources and relationships](docs/coverage.md) are
modeled. No live cloud discovery, effective IAM authorization, full routing,
provider execution, multi-cloud coverage or compliance certification is claimed.
Terraform plans and reports can expose private architecture; use authorized
inputs and protected storage. See [security model](docs/security-model.md),
[limitations](docs/limitations.md) and [security reporting](SECURITY.md).

## Development

```bash
make check
make frontend
make docs
make wheel
```

[Contributing](CONTRIBUTING.md) covers environment/tool versions and release
checks. [Integration acceptance](docs/release-integration.md) covers disposable
PostgreSQL, fresh installs, containers and the parent-owned browser checks.
Legal, external-provider and operational acceptance remain launch prerequisites.

## Future roadmap

Complete external/browser acceptance and operational/security promotion gates
before public beta. Durable jobs, deeper AWS coverage and enterprise capabilities
are separate scopes; [the roadmap](docs/roadmap.md) does not promise shipping dates.
