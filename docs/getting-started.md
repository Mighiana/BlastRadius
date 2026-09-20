# Getting started

## Run the local application

Use Python 3.12, Node 24.19.0, Git and Make. From a reviewed checkout:

```bash
source "$HOME/.nvm/nvm.sh"
nvm install "$(cat web/.nvmrc)"
nvm use "$(cat web/.nvmrc)"
cp .env.example .env
make dev
```

Open `http://localhost:8000`. The example config uses local SQLite and demo
authentication. It is not suitable for public deployment. Subsequent starts can
use `make start`; rebuild frontend changes with `make frontend`.
Keep the browser origin equal to `BR_PUBLIC_URL`, including scheme and port.

## First analysis

1. Try the public SSH, IAM and bucket scenarios without login.
2. Sign in with demo auth to create a local Free workspace. Real accounts use
   [OIDC](auth.md). Demo sign-in creates a new random identity each time.
3. Create a project. Supply two `.tf` snapshots, using
   `examples/safe/main.tf` and `examples/vulnerable/main.tf` to reproduce the
   one-line public-SSH regression.
4. Inspect the persisted job, decision, graph, attack path, evidence and coverage.
   Alternatively upload the already-produced `examples/plans/ssh_open_plan.json`.
5. Open history and download JSON or Markdown. Free saved SARIF is restricted;
   public demo SARIF is available. Paid-plan entitlements require an
   [operator grant](operations.md#beta-administration).

Uploads are bounded UTF-8 file maps or plan JSON, not archives, host paths or
arbitrary URLs. Do not send secret-bearing plans to an untrusted instance.
BlastRadius never runs Terraform, providers, module downloads or candidate code.

## CLI and legacy demo

For CLI-only use, install `.` in a Python virtualenv and follow [CLI](cli.md).
`make legacy` runs the separate Streamlit demo. The historical public demo and
Actions consumer do not change when a local SaaS checkout is built.

## Configuration and troubleshooting

- `authentication_disabled`: configure local demo mode or production OIDC.
- `invalid_origin`: fix `BR_PUBLIC_URL`; do not weaken CSRF or proxy trust.
- Readiness failure: run migrations against the same DB; check Alembic head 0003.
- Service lease error: stop the other process using this DB; do not add workers.
- Quota/entitlement 402: inspect [usage and plans](billing.md); there is no checkout.
- Worker failure/incompleteness: inspect diagnostics and [coverage](coverage.md).

See [frontend](frontend.md) for Vite development, [deployment](deployment.md)
for containers, and [integration acceptance](release-integration.md) for verified
operator commands and downstream browser testing.
