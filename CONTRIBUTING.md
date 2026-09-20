# Contributing

Read [AGENTS.md](AGENTS.md) first. Use a feature branch and preserve the existing
CLI, demo and trust-boundary tests. Do not run the live GitHub publisher, deploy
publicly or activate billing without explicit approval.

## Environment

Python 3.12 is the test baseline. Node 24.19.0 and npm are needed for `web/`; Make
commands assume a POSIX shell. No pre-commit configuration exists at this
baseline, so the commands below are explicit developer/CI gates.
If `python3.12` is not on PATH, pass `PYTHON` to Make with the installed
interpreter's absolute path, or activate it through your version manager.

```bash
make install-core
make check
```

For the integrated app, copy `.env.example` to `.env`, configure the documented
server settings, then `make dev`. Missing frontend/server contracts fail early.
See [deployment](docs/deployment.md) and [integration notes](docs/release-integration.md).

## Checks before every commit

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest -o addopts='' -q scripts/test_release_tooling.py
make lint typecheck docs
```

For frontend changes, run `make frontend` (npm ci/lint/typecheck/build).
For dependency changes, run `make audit` after installing the full environment.
Audit findings are not silently suppressed. Fix or document/escalate real
findings; do not weaken dependency policy or security tests to make CI pass.

Ruff checks fatal/static issues across historical Python and the standard
E4/E7/E9/F set on release scripts and the new server. Strict mypy checks the
scripts and server once integrated. Historical engine code is not claimed to be
fully typed. Follow the [integration notes](docs/release-integration.md#tooling-scope)
for existing lint debt rather than blanket ignores.

Optional local workflow validation:

```bash
actionlint .github/workflows/*.yml docs/github-action.yml
sh -n scripts/container-entrypoint.sh
bash -n scripts/verify-demo.sh
docker compose config --quiet
```

Use a reviewed actionlint release; this unit verified 1.7.7. ShellCheck strengthens
actionlint shell analysis when installed. YAML parsing alone does not validate
GitHub expression contexts.

## Regression expectations

Tests should prove behavior, not mirror implementation. New graph relationships
need positive and negative cases, evidence checks and unsupported-value handling.
Auth and storage need cross-tenant read/write/delete/export tests. Quotas need
concurrency cases. Providers use mocks unless live sandbox testing is approved.

Do not edit existing tests merely to accommodate a regression. In particular,
preserve the one-line SSH demo, intentional public 443 listener, CLI exit codes,
working-tree preservation, trusted base policy, publisher bot identity and
stale-head checks.

## Packaging and documentation

Build with `python -m pip wheel . --no-deps --wheel-dir dist`. Install the wheel
in a fresh venv and use `python -I -m blastradius.cli` outside the source tree.
Test real static assets and migrations in the final container after integration.

Run `make docs` for local links/anchors. It deliberately does not send private
documents to an external link checker. Preserve old README anchors.
Use real screenshots from the tested revision, no fabricated evidence.

Keep credentials, `.env`, state, reports, database files and generated scratch out
of commits. Pin new dependencies to reviewed versions, ordinarily at least seven
days old; a direct pin alone does not lock transitive dependencies.

## Contributions and legal terms

The baseline repository has no standalone license file. Do not infer a grant
from public source availability. The owner must choose licensing and any
contributor terms before a wider distribution/commercial launch.
Report security issues through [SECURITY.md](SECURITY.md), not public exploit details.
