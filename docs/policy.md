# Trusted workspace policies

Policies change the gate decision, never the attack graph, path search or score.
Only owner/admin can edit; Pro+ supports project policy, Team+ supports an
organization default. The API rejects unknown fields and unsupported rules:

```json
{
  "version": 1,
  "gate": {
    "block_new_critical_paths": true,
    "block_new_sensitive_exposure": true,
    "block_public_admin_ports": true
  },
  "allowed": {"public_https": true},
  "thresholds": {"minimum_security_score": null}
}
```

Booleans must be actual booleans; minimum score is null or integer 0–100.
These are the actual engine's `load_policy_data` fields. Resource exclusions,
custom severities and arbitrary organization rules are not implemented.
Terraform root is validated project metadata rather than policy input.

Each edit increments the target's stored policy version. At enqueue, the server
chooses an entitled project override, otherwise an entitled organization default,
otherwise the engine's legacy default. It persists an immutable snapshot:
`{source:"project|organization|default",version:integer,rules:object|null}`.
No configured policy means `rules:null` and legacy behavior (critical regressions
block, noncritical exposure requires review). Explicit `{}` uses supported policy
defaults, including standalone public administrative-port blocking.

The worker receives this server-created snapshot separately from analysis input.
Editing policy while a job is queued does not change that job. HCL filenames,
candidate repository policy or Terraform plan data cannot supply a snapshot.
Completed analyses retain theirs across edits and plan changes. After downgrade,
unentitled policies remain stored but do not affect new jobs. No historical
snapshot is invented for pre-migration analyses.
