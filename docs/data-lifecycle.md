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

## Commercial beta records

Beta-interest requests, per-user analysis feedback and first-party product events
have a separate **90-day** lifetime measured from creation. Feedback updates do
not extend it. Review/summary routes hide expired records; feedback also requires
an analysis visible under the workspace's current retention window.

Intake stores name/email, optional bounded workflow details and the consent
notice version after explicit agreement. Feedback stores useful/not-useful,
optional review text and server-derived user/workspace/project/analysis IDs.
These texts are private operator-review data and are not automatically scrubbed.
Do not submit Terraform, credentials or private infrastructure in these forms.

Product events contain only fixed milestone names, timestamps and optional UUID
references. There is no source/email/name/IP/token payload or browser ingestion.
Storage is capped at 10,000 beta requests, 50,000 feedback rows and 100,000 events;
events evict oldest rows at capacity. These counts are not a durable accounting
ledger. See [commercial API](beta-api.md) for exact schemas and semantics.

Schedule the separate trusted command, with the same migrated database:

```bash
BR_ADMIN_ENABLED=true python -m blastradius.server.admin cleanup-commercial --limit 100
```

Each call removes up to `limit` expired rows from **each** of the three tables
(1–1000, default 100), auditing counts only. Repeat bounded calls until all three
returned counts are zero; monitor exit status and backlog. There is no automatic
time-based purge. Analysis/user/tenant deletion cascades dependent feedback/event
references; anonymous beta requests have no account relationship. Operators must
include these records in backup expiry, rights requests and deletion replay.

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
as needed. Operators may instead opt in to the bounded in-process sweep with
`BR_RETENTION_SWEEP_SECONDS`; it runs only on the lease-holding instance,
performs its first sweep at startup, and repeats at the configured interval.
Manual cleanup commands remain the authoritative path. Sleeping free instances
only sweep while awake. There is no external email or queue service.
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
