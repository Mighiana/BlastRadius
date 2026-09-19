# BlastRadius - working notes

## Commands

```bash
pip install ".[ui,dev]"          # setup (Python 3.11+; verified on 3.14)
streamlit run app.py              # dashboard (http://localhost:8501)
python -m pytest                 # all tests (must be green before any commit)

python -m blastradius.cli --before examples/safe --after examples/vulnerable
# exit 0 = no critical regression, 1 = BLOCK CHANGE, 2 = usage error
```

## Verification expectations

The demo depends on these invariants; `tests/` enforces them:

* `examples/safe/` → 0 critical attack paths, risk `LOW`, score 100
* `examples/vulnerable/` → exactly 1 critical path
  `INTERNET → aws_security_group.web → aws_instance.web_server → aws_iam_role.app →
  aws_s3_bucket.customer_data → sensitive_data.customer_data`, risk `CRITICAL`
* The two files differ by **exactly one line** (the SSH ingress CIDR, line 28) -
  `test_demo_configs_differ_by_exactly_one_line` asserts this literally
* `compare(safe, vulnerable)` → `Verdict.REGRESSION`, `Decision.BLOCK`
* Remediating `examples/vulnerable/` restores score 100 and `Decision.SAFE`
* All three bundled scenarios start from a clean baseline and end in `BLOCK`
* The simulated risky change must produce results identical to the committed
  `examples/vulnerable/` config (`test_simulation_produces_the_same_result...`)

`tests/test_app_smoke.py` runs `app.py` headlessly via `streamlit.testing.v1.AppTest`,
including the full click path (restore → simulate → remediate). Run it after any UI
change.

## Gotchas

* `python-hcl2` v8 keeps surrounding quotes on strings, returns heredocs as
  `<<MARKER\n...\nMARKER`, and wraps references as `${aws_x.y.z}`. All of this is
  normalized in `blastradius/parser/terraform_parser.py`; don't bypass it.
* IAM and bucket policies in example Terraform must be **heredoc JSON** -
  `jsonencode(...)` is not parseable and is deliberately skipped.
* The package is `blastradius/` rather than top-level `parser/` to avoid shadowing
  stdlib module names.
* Streamlit forbids writing to a widget's `session_state` key after that widget is
  created - use `queue_scenario()` in `app.py`, which stages the change and reruns.
* PyVis graphs use pinned coordinates with `physics: false` so the demo layout is
  identical on every run. Keep it that way. Off-path nodes are dimmed by emitting
  `rgba()` backgrounds; note that pyvis's own JS template also contains `rgba(`,
  so tests must assert a specific faded colour, not the substring.
* `.streamlit/config.toml` pins a dark theme. The CSS assumes dark; without the
  pin, light-theme users get unreadable pale text.
* **Terraform edits live in one place**: `blastradius/security/hcl_edit.py`.
  Simulation widens a CIDR, remediation narrows it, and both must only touch
  `ingress` blocks that reach an admin port (22/3389). Rewriting a public 443
  listener would cause an outage - `test_remediation_does_not_touch_a_public_443_listener`
  guards this.
* The CLI reconfigures stdout to UTF-8: the PR report contains emoji and a Windows
  cp1252 console raises `UnicodeEncodeError` otherwise.
* Runtime-generated Terraform goes to `examples/generated_fix/` (remediation) and
  `.blastradius_sim/` (simulator). Both are gitignored.

## Product input / CI verification

```bash
python -m pytest -o addopts='' -q
python -m blastradius.cli --repo /path/to/repo --base main --head feature/network-change --terraform-dir infra --format json
python -m blastradius.cli --plan examples/plans/ssh_open_plan.json --format sarif
```

* Git extraction uses resolved SHAs and temporary snapshots, never checkout of
  the developer's working tree. Tests preserve dirty files and branch state.
* Git policy is read from the base commit, not candidate policy or working tree.
  `--policy` is an explicit trusted override. Invalid policies return exit 2.
* No-file policy preserves legacy behavior. Explicit policy enables standalone
  public SSH/RDP blocking; public HTTPS never exempts a critical path.
* JSON and SARIF stdout must be a single parseable document. Do not prefix it
  with diagnostics. Git SARIF filenames must not leak temporary snapshot paths.
* Candidate plan configuration references must never rewrite prior-state links.
  Real module/indexed addresses are reported outside coverage instead of silently
  colliding with root resource addresses. Plan mode is currently CLI-only.
* SARIF includes logical resource addresses and known files, not guessed lines.
* Tests must set Git author identity per command (`git -c`), not via git config.
* Internal repo CI runs the base-revision analyzer. The external example installs
  a reviewed upstream commit into a venv and uses isolated Python from runner.temp;
  only the target repo's base is checked out, and candidate objects are read as data.
* Demo Mode removes advanced widgets. Preserve before/after session state when
  hiding those widgets; test toggling back after remediation.

## Installation and GitHub PR delivery

* Build a wheel with `python -m pip wheel . --no-deps --wheel-dir dist`.
  Install it in a fresh venv and use `python -I -m blastradius.cli` to avoid falsely
  testing imports from the source tree. CLI core does not require Streamlit.
* `--github-action` reads a validated pull_request event. Never accept
  pull_request_target, event branch names in shell code, or mismatched base repos.
* `terraform_dir` comes from explicit override or trusted base policy; multiple
  roots must fail clearly. Do not read candidate policy to weaken its own gate.
* `--report-dir` emits all formats from one analysis. CLI exit 0/1/2 is independent
  of comment publication. Action outputs use fixed keys and scalar values only.
* Publication updates only the GitHub Actions bot's marked comment and checks the
  head SHA. Never modify a human's look-alike comment. Tests use a fake API client;
  do not run the publisher against a live PR without explicit authorization.
* GitHub permissions failures leave the report in summary/artifacts. No token is
  embedded in command arguments or logs; use the step-scoped GITHUB_TOKEN env var.
* This integration and packaging are locally verified, not a published PyPI
  package, Action release or verified hosted GitHub run. Publication needs approval.
* Tests with very large parametrized strings need short explicit IDs: Windows
  environment variables (including PYTEST_CURRENT_TEST) have a 32767-char limit.
* Invoke tests with `python -m pytest`, not the standalone pytest entry point.
  Without an installed project, standalone pytest fails importing blastradius
  from conftest (exit 4); this was reproduced during hosted CI bring-up.
* Published, install-verified analyzer pin: a72c04890640102b315506ab85e5f1ccbe91bb9f.
  The consumer workflow uses this immutable default; overrides must be full SHAs.
* GitHub rejects `runner.temp` in job-level defaults.run. Specify it in each
  shell step's working-directory instead. Plain YAML parsing misses this contextual
  validation error; the hosted workflow validator exposed it.
* Linux tests and gate verified in Actions run 35441042287. This is not evidence
  that the separate PR-comment acceptance workflow has completed.
