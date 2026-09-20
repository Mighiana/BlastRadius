# Public Streamlit demo

The Streamlit app is the public interactive demo of the Python analyzer. It
uses bundled scenarios to show how a Terraform change can alter modeled
attack paths. The multi-user workspace platform, including accounts and
history, is currently in private beta.

## Streamlit Community Cloud deployment

The Community Cloud app should use `app.py` as its main file and
`requirements.txt` for dependencies. Select Python 3.12 in the app settings.
The public demo has no PostgreSQL, FastAPI, or localhost dependency. Optional
deployment secrets or environment variables are:

- `BLASTRADIUS_BETA_FORM_URL`
- `BLASTRADIUS_BETA_CONTACT`
- `BLASTRADIUS_DOCS_REF`

Leave `BLASTRADIUS_TRUSTED_LOCAL` unset. The app must be configured for public
viewer access and deployed from the intended branch.

## Default hosted behavior

```bash
python -m pip install ".[ui,dev]"
python -m streamlit run app.py
```

Leave `BLASTRADIUS_TRUSTED_LOCAL` unset on a public instance. Both normal and
Demo Mode offer the bundled scenarios, restore, simulation, and remediation
controls. Local directory and Git inputs are hidden, and the server rejects
unapproved paths even if session state contains one. Accepted inputs are exact
bundled scenario directories and jobs belonging to that Streamlit session.
Another session's files are rejected even when their path is known.

Simulation, remediation, and Git extraction each get a new directory. Before
and after snapshots remain separate; generating a fix never overwrites the
configuration it fixes. The current pair is protected from job pruning.
Scenario changes still go through the staged Streamlit state transition.
Analysis results are memoized per Streamlit session by directory content.

Policy discovery for directory comparisons is limited to the selected before
directory. It does not fall back to policy in the application checkout.
Git comparisons retain the analyzer's base-commit policy behavior.

## Trusted local compatibility

On a machine used only by trusted users, explicitly opt in:

```bash
BLASTRADIUS_TRUSTED_LOCAL=1 python -m streamlit run app.py --server.address=127.0.0.1
```

For PowerShell:

```powershell
$env:BLASTRADIUS_TRUSTED_LOCAL = "1"
python -m streamlit run app.py --server.address=127.0.0.1
```

Only the exact value `1` enables this mode. Turn Demo Mode off to reveal the
advanced controls. You can then choose local Terraform directories and compare
Git refs from a local repository. Git uses snapshots, not working-tree checkout,
and stores both refs under the current session's job. Invalid Git requests
discard their partial job.

This is a process-wide operator setting, not a per-user permission. Never enable
it on a public or shared untrusted instance: it deliberately permits local
filesystem and repository reads. Symlink, traversal, file-size, and cross-session
checks still apply. Paths containing `..`, backslashes, or symlink ancestors are
rejected; on Windows use forward-slash paths. The Terraform subdirectory for
Git must remain relative to the repository.

The CLI is unchanged by these settings. Larger or non-demo workloads should use
the CLI/CI integration or the new product service.

## Storage contract

The default root is `~/.cache/blastradius/legacy-sessions`. Operators can set
`BLASTRADIUS_DEMO_STORAGE_ROOT` to a dedicated writable directory outside the
checkout. The root must not be a symlink or have symlink ancestors. On POSIX,
existing roots must not grant group or other permissions; the app creates root,
session, and job directories with mode `0700`. Windows deployments must enforce
equivalent access restrictions using their filesystem ACLs.

```text
legacy-sessions/
  session-<random>/
    simulation-<random>/
    remediation-<random>/
    git-<random>/
      before/
      after/
```

The names are internal implementation details, not stable public identifiers.
Session ownership comes from server-side session state, not a user-submitted
session ID. No generated files are served as static files by this code.

| Limit | Behavior |
| --- | --- |
| Idle retention | A session is eligible for deletion after 24 hours without an app rerun. |
| Sessions | At most 128 recognized session directories per storage root, enforced within one process. Capacity fails closed without evicting active sessions. |
| Jobs | At most 8 recognized operation directories per session, including the current before/after pair. Older unreferenced jobs are pruned first. |
| Terraform files | At most 32 top-level `.tf` files per selected directory. |
| Individual input | At most 512 KiB per Terraform or adjacent policy file. |
| Combined input | At most 2 MiB per selected directory, including adjacent `blastradius.yml` and `blastradius.yaml`. |

Terraform and adjacent policy inputs must be regular files, without symlinks or
hard links. Generated jobs use fresh directories, so old `.tf` files cannot
carry over into the next operation.

Cleanup runs at session creation and on app reruns. It removes only recognized,
expired session directories; it skips symlink entries and unrelated root
entries. Removing a session does not follow symlinks inside that session.
An expired browser session recovers by creating a fresh workspace and restoring
the default bundled comparison.

There is no background janitor. Files can remain past 24 hours while the app is
idle or stopped; a browser disconnect does not immediately delete them.
Operators needing deletion deadlines must add managed storage expiration or a
maintenance job. With the Streamlit process stopped, the same cleanup helper
can be run using the same storage environment:

```bash
python -c "from blastradius.session_storage import cleanup_expired, storage_root; print(cleanup_expired(storage_root()))"
```

The app no longer writes `.blastradius_sim` or `examples/generated_fix`. Existing
files in those historical locations are not migrated or automatically deleted.
Operators should inspect and remove obsolete data under their own retention
policy. Older README/working-note references to shared outputs describe the
pre-hardening implementation.

## Rendering and security boundaries

Untrusted resource labels and evidence are escaped in HTML cards, path traces,
and graph tooltips. Markdown text cannot introduce arbitrary links or images.
Graph rendering uses escaped display copies, preserving analysis graph values,
node identities, deterministic positions, and disabled physics.

Cards wrap on narrow screens. Graph iframes fit their width and re-fit their
network when the container size or fonts change. These are incremental fixes to
the public demo; the private-beta platform owns the commercial workspace
experience.

This app does not execute Terraform, apply remediation to AWS, or inspect a live
cloud account. A zero-path result means **“No new modeled critical attack paths
detected.”** It does not prove infrastructure is safe or provide complete AWS
coverage. Decision labels remain compatible with the analyzer;
they must be interpreted within the analyzer's modeled coverage.

## Residual limitations

- Locking and session-capacity enforcement are process-local. Use one Streamlit
  process per dedicated root. Multiple workers or replicas must use separate
  roots and route an existing browser session to its owning process. A shared
  filesystem across processes needs additional coordination.
- This protects sessions against ordinary web visitors, not a hostile process
  running as the same operating-system user. Path checks and later parser reads
  are separate operations. Run under a dedicated unprivileged account, keep the
  code/examples read-only, and restrict access to the storage root.
- Count and input-size bounds are not filesystem quotas. Trusted-local Git
  snapshots are materialized before the app validates their size. The demo has
  no upload endpoint, CPU deadline, authentication, per-user quota, or rate
  limiter; anonymous sessions can occupy its finite capacity.
- Resetting a scenario does not immediately purge all older jobs. They remain
  subject to the eight-job limit and idle-session expiration.
- AppTest checks state and rendered output, not actual browser geometry or
  JavaScript execution. Final desktop/mobile browser checks belong to the
  integrating delivery session.

## Verification and integration

The implementation changes only `app.py`, adds
`blastradius/session_storage.py`, and adds regression coverage in
`tests/test_session_isolation.py`. Parser, graph, remediation, Git, and CLI
engines are unchanged. The existing `tests/test_app_smoke.py` remains unchanged.

```bash
python -m pytest
python -m pytest tests/test_session_isolation.py tests/test_app_smoke.py -q
ruff check app.py blastradius/session_storage.py tests/test_session_isolation.py
mypy --follow-imports=skip --ignore-missing-imports app.py blastradius/session_storage.py tests/test_session_isolation.py
```

Coverage includes two independent AppTest sessions through simulation and
remediation; before/after state across Demo Mode toggles; forged hosted paths;
trusted-local directory/Git compatibility; content reload with an unchanged
timestamp; symlinks, traversal, hard links, and nonregular inputs; retention and
capacity; expired-session recovery; and malicious graph/Markdown labels.

The integration owner handles final browser testing, screenshots, deployment
configuration, and integration into the product delivery branch.
