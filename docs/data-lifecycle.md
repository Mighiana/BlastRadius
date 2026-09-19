# Data retention and deletion

## Enforced retention

Analysis metadata, JSON results, findings, paths/hops and report artifacts share
the current workspace retention window: Free 7 days, Pro 90 days, Team 365 days;
Enterprise is configurable. Age is measured from analysis creation in UTC,
including queued or failed jobs. At the exact cutoff the analysis is expired.

Every history, detail, findings, paths, artifact and report read checks current
retention. Expired objects return `404 not_found` to all users. This applies before
physical cleanup, including direct artifact IDs and SARIF exports. Upgrading can
restore visibility only if cleanup has not already deleted the data. Downgrading
hides older data immediately and makes it eligible for the next cleanup.
Completed policy snapshots are immutable; legacy rows have a null snapshot and
normalization version rather than invented historical evidence.

## Physical cleanup

In a trusted operator environment with the same database configuration:

```bash
BR_ADMIN_ENABLED=true python -m blastradius.server.admin cleanup --limit 100
```

The command removes at most the requested number of expired analysis records
(1–10000, default 100) per invocation, with cascading children, in one transaction.
It selects a bounded candidate batch using workspace retention settings, then
locks only those workspaces and rechecks the current window before deletion.
It is idempotent; repeating after exhaustion reports `{"removed":0}`. Schedule
this command hourly with an operator-controlled timer, repeating bounded batches
as needed. There is no in-process scheduler, external email or queue service.
Audit events record counts and workspace identity without retaining evidence.
Monitor command exit codes and backlog on the chosen deployment.

Deleting an analysis or project also cascades its evidence and artifacts.
Deleting a workspace cascades projects, analyses, members, invitations and usage;
audit tombstones survive with a null workspace reference. Jobs finishing after
deletion do not recreate records. Ordinary analysis/project cleanup does not
decrement or delete historical usage. Deletions of already absent objects return
404 and do not reveal another tenant's data.

## Temporary inputs and stored evidence

HCL/plan requests are processed in unique worker directories beneath
`BR_DATA_DIR/jobs`. They are removed after success, failure or timeout. Startup
recovery removes abandoned directories and marks interrupted jobs failed.
Deletion does not forcibly interrupt an already running subprocess; resource and
time limits still apply and its directory is removed at completion.

Reports intentionally contain resource names, policy evidence, diffs and suggested
HCL patches. Deleting the original scratch files does **not** mean all source
fragments disappear from persisted results. Terraform plans and HCL can contain
secrets; avoid uploading unnecessary secrets, restrict database access, encrypt
backups and use an approved deployment boundary. The parser never executes
Terraform, providers, repository workflows or candidate code. Worker logs include
IDs/outcome/duration, never the request body, invitation tokens or source text.

Sessions expire and are purged on creation of a new session; users can revoke one
or all sessions. Pending invitations expire after seven days and remain listed
as historical records after revocation/acceptance; there is no invitation/audit
age purge yet. Audit, identity and accounting retention, log rotation, encrypted
backups, restore/deletion replay, geography and legal processing terms remain
operator responsibilities before accepting private customer data.

GitHub comments/Actions artifacts, local CLI exports and downloaded reports are
outside database deletion. No external repository content is silently deleted.
