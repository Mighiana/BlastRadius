# Data retention and deletion

**Status: policy and implementation checklist, not a service promise.**
Before accepting private customer data, the owner must choose retention periods
and verify the integrated service enforces them. No automatic purge or deletion
endpoint is asserted by this document.

| Data | Location/boundary | Required handling |
|---|---|---|
| Raw HCL/plan input | Request and per-job scratch | Minimize storage; clean success/failure/cancel paths; crash janitor |
| Findings/reports/history | Tenant-scoped database or object storage | Document retention and project/organization deletion cascade |
| Session/identity state | Auth provider and app as implemented | Revoke sessions/membership on deletion; provider-specific cleanup |
| Usage/billing references | App and approved provider | Separate necessary accounting records from analysis payloads |
| Logs/errors | Operator-controlled logging | Redact payloads; approve finite retention and access |
| Backups | Restricted backup storage | Encrypt, expire, and reapply deletions after restore |
| Actions artifacts | GitHub repository | Onboarding copy defaults to seven days |
| PR comments/summaries | GitHub repository | Separate retention; deleting app history does not delete these |
| Local CLI exports | User's disk | User-controlled; no remote deletion by the service |

Terraform plans can contain secret values; “sensitive” flags do not guarantee
redaction in JSON. Resource names, ARNs and graph topology may also be confidential.
Do not accept private files in the public synthetic demo.

## Proposed deletion behavior to verify

An authenticated authorized owner requests deletion of a project/organization.
The service marks it unavailable, prevents new jobs, cancels or fences in-flight
work, removes live inputs/reports/derived indexes and updates permitted usage
records. Concurrent workers must not recreate deleted data. Repeated deletion
must be idempotent and must not reveal another tenant's object existence.

Record a minimal deletion tombstone if needed for backup recovery, without
retaining the deleted payload. On restore, replay deletions before allowing
access. External GitHub comments/artifacts and provider records require explicit
separate handling; do not silently delete customer repository content.

## Owner decisions before launch

Choose exact input, history, logs, backup and billing-record retention; identify
data geography/subprocessors; document deletion request authentication, timing,
exceptions and export behavior. Validate with integration tests and an operational
drill. Until then, the [privacy template](privacy.md) must remain marked for review.
