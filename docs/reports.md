# Reports and exports

Reports carry the engine decision, heuristic scores, before/after graph state,
added/removed paths, coverage diagnostics, edge evidence and remediation guidance.
Saved analyses also record input type, refs/SHAs when known, timestamps, status,
trusted policy snapshot and normalized findings/path hops.

SAFE means no new modeled blocking findings under the selected policy.
Incomplete/unknown coverage requires review independently of score or path count.
See [decision semantics](security-model.md) and [coverage](coverage.md).

## Application

- `GET /api/analyses/{id}` returns retained job/report state.
- `/findings`, `/paths` and `/artifacts` expose normalized saved evidence.
- `/report?format=json|markdown|sarif|web` downloads or returns the report.
- `/artifacts/{artifact_id}` reads the selected artifact under the same tenant,
  retention and format entitlement checks.

All persisted evidence requires workspace membership. JSON/Markdown are available
on every plan. Saved SARIF requires Pro/Team/Enterprise and is removed from nested
JSON on Free, so alternate download paths cannot bypass the entitlement.
Public synthetic demo reports remain available in every format.
Plan retention changes take effect immediately on reads and exports.

Downloads increment UTC monthly export counters; ordinary job reads and
`format=web` do not. Deletion does not refund accepted analyses or export usage.
Reports reveal architecture even when source paths and errors are sanitized.
External downloaded copies and GitHub comments have separate retention.

## CLI and Actions

CLI `--format json|sarif|pr|summary` and `--report-dir` use engine output without
SaaS account/plan restrictions. JSON and SARIF stdout are a single parseable
document. SARIF uses logical resource addresses and known relative filenames,
not guessed source lines. See [CLI](cli.md), [sample report](sample-report.md)
and [Actions delivery](github-actions.md).

No PDF export, public sharing link or hosted signed-object-store URL is
implemented. Artifact access is through the authenticated API.
