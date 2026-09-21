# Operations and metrics

This is an operator runbook for the target service. Items requiring infrastructure
or code integration are requirements, not claims of installed monitoring.

## Startup and readiness

Use the [deployment procedure](deployment.md): migrate once, then start traffic.
Separate liveness (process can respond) from readiness (required DB/schema and
configuration are usable). Never mark failed analysis as a healthy zero-finding
result. The supplied image uses `/health/ready` for schema/demo readiness.

Readiness requires the schema expected by the installed release. Record the
actual Alembic head with the release; do not hard-code `0001` in new operational
checks.

## Capacity and restart behavior

Compose reference limits, not a measured production capacity claim:

| Service | CPU | Memory | PIDs | Writable temporary mounts |
|---|---:|---:|---:|---|
| App | 2 | 2 GiB | 128 | `/tmp` 64 MiB; separate persistent `app-data` |
| Migration job | 1 | 512 MiB | 64 | `/tmp` 64 MiB; same `app-data` |
| PostgreSQL | 1 | 1 GiB | 128 | `/tmp` 64 MiB, sockets 16 MiB, shared memory 128 MiB; database volume |

Budget at least 4 GiB RAM plus OS/build headroom for this reference stack.
Persistent volumes have no quota in plain Compose: provision and monitor disk
capacity separately, including WAL, backups and scratch. Docker JSON logs rotate
at 10 MiB × 3 files per container; that is a size bound, not time-based retention.
Observe actual input mix and memory/CPU saturation before increasing limits.

Default `BR_WORKERS=2` is the analysis subprocess pool, not the ASGI process count.
`BR_MAX_JOBS=8` bounds admitted/running jobs; `BR_JOB_TIMEOUT=30` bounds each worker.
`BR_LOG_LEVEL` controls structured application log verbosity and accepts `DEBUG`,
`INFO`, `WARNING` or `ERROR` (default `INFO`).
The queue is in memory. The configured shutdown grace is 150 seconds; this is not
a verified worst-case drain bound. GitHub jobs use a separate single-thread
pipeline plus provider requests, so eight GitHub jobs can exceed that grace even
with the default worker timeout. Measure the intended backlog/input mix and
increase the grace before relying on graceful draining. A forced stop or host
loss still loses queued work. Restart marks queued/running records failed
with `server_restarted` and cleans `BR_DATA_DIR/jobs/job-*`; it does not requeue.

Terminal writes retry three times. If all attempts fail, readiness and new analysis
admission return 503. Reads of unfinished analyses, including history pages that
contain them, return `analysis_persistence_failed` rather than claim the stale
database status is current. The UI clears previous progress and displays
**Analysis incomplete**. Completed reports remain readable. Restore database
access, then restart the single application process; startup recovery finalizes
unfinished rows as failed. Docker's healthcheck alone does not restart an
unhealthy container: configure an alert/operator response or a supervisor that
restarts unhealthy instances. The queue does not retry or resume lost input.

The entrypoint always starts **one ASGI process**. The database service lease
rejects a second process, so do not scale replicas or run overlapping rolling
deployments. Stop admission at the ingress, drain/stop the old service, migrate
once and then start the new service:

```bash
docker compose stop app
docker compose run --rm migrate
docker compose up -d --wait app
docker compose exec -T app id
docker compose exec -T db id
```

Migration failure must stop the rollout. Keep the last reviewed image and a
restorable backup; application rollback requires compatible schema, and
destructive automatic Alembic downgrades are not supported.

### Release drain and rollback

There is no application maintenance/drain endpoint. The release owner must:

1. Record current image digest, migration head, backup/restore evidence and known
   unfinished jobs. Close new analysis admission at the ingress, including GitHub
   webhooks and browser mutations, while existing workers finish. Coordinate a
   webhook delivery pause/redelivery window; GitHub does not automatically replay
   missed work. Do not acknowledge blocked deliveries as accepted.
2. Inspect aggregate DB counts through a separately approved read-only operator
   profile. `queued` deliveries cover the GitHub pipeline, including publication;
   do not judge draining by analysis rows alone:

   ```sh
   : "${inspection_service:?approved read-only libpq service profile required}"
   psql --dbname="service=$inspection_service" --no-psqlrc --set=ON_ERROR_STOP=1 \
     --command="SELECT status,count(*) FROM analyses WHERE status IN ('queued','running') GROUP BY status; SELECT status,count(*) FROM github_deliveries WHERE status='queued' GROUP BY status;"
   ```

3. Wait for both counts to reach zero and investigate retryable/uncertain GitHub
   publication. If they cannot drain within the approved window, retain ingress
   closure and choose an explicit interrupted-work recovery plan. Do not pretend
   `BR_JOB_TIMEOUT` or 150 seconds covers the whole GitHub queue.
4. Stop the old singleton with the platform's reviewed grace period. Verify it
   exited before migration/new startup. Take/verify the pre-migration recovery
   point while admission is closed, then execute the reviewed image's `migrate`
   command under the migration role.
5. If migration succeeds, reapply/check runtime grants, start `serve` under the
   runtime role, and verify readiness/liveness, expected schema and authorized
   tenant reads through the real ingress. Reopen admission only after acceptance.
6. On failure keep admission closed. Prefer a reviewed forward fix. Reuse the
   previous image only after proving it accepts the current schema; readiness
   requires exact packaged heads, so even an additive migration can prevent that
   old image starting. Otherwise restore the pre-change backup to **a new isolated
   database**, replay deletions, validate and explicitly approve the connection
   cutover/data-loss window. Preserve the failed database for investigation.

Never use `alembic downgrade`, `pg_restore --clean` against an active database,
delete volumes, or start two ASGI replicas as an improvised rollback. Recover
interrupted work as failed; tell users to resubmit authorized inputs as needed.
For GitHub, review current heads/authorization and use the documented signed
redelivery procedure; redelivery does not automatically rerun an already failed
analysis. Record lost-work and publication reconciliation decisions.

## Logging contract

Use structured logs with timestamp, level, event name, request/job ID, route
template, status, duration and model version. Include opaque tenant/project IDs
only when necessary and access-controlled; avoid raw names.

Never log tokens, authorization/cookie headers, keys, webhook raw bodies,
full Terraform plans or complete source by default. Redact error details before
returning them to users. Do not log database URLs containing passwords.
Keep privileged audit events separate from verbose debugging.

Optional error monitoring must remain off without credentials. Review payload
scrubbing before enabling it; stack frames can include customer data.
Do not add a Sentry DSN or pretend an error-monitoring hook exists without code.

## Metrics to implement and observe

| Signal | Why | Suggested dimensions |
|---|---|---|
| Request latency/error rate | API availability | route template, status class |
| Analysis duration and timeout count | Parser/graph saturation | input mode, model version |
| Queue wait/depth, active workers | Capacity and backpressure | worker pool |
| Input bytes/resources/path cap hits | Abuse/coverage pressure | input mode, limit type |
| Decision and incomplete counts | Result quality | decision, diagnostic category |
| Auth failures and denied tenant access | Access-control incidents | reason category |
| Database pool saturation/migration version | Storage readiness | instance |
| Scratch bytes and cleanup failures | Disk exhaustion and retention | worker |
| Usage quota rejections | Limit enforcement | plan identifier |
| Publisher/webhook retries and stale skips | Integration reliability | event category |

These are proposed metrics, not current exported metric names.
Do not use tenant IDs, resource addresses or filenames as high-cardinality metric
labels. Choose alert thresholds after load tests; no SLA/SLO is asserted here.

### Initial alert routing

Install these in the chosen platform and test notification delivery. Thresholds
below are proposed starting points, not measured service objectives:

| Check | Initial trigger | Owner response |
|---|---|---|
| HTTPS readiness | Two consecutive failed one-minute probes outside an approved maintenance window | Service owner: check DB/schema/lease/persistence; keep admission closed if degraded |
| Liveness/restarts | Process unavailable or repeated restarts | Service owner: inspect redacted logs/resource limits; do not add replicas |
| Analysis failures/backlog | Oldest queued work exceeds measured drain budget, or sustained timeout/error increase | Service owner: pause admission, inspect capacity and safe error categories |
| Database/WAL/scratch | Free space below 20%, fast growth, or provider capacity alarm | Database owner: investigate growth and retention; never delete live WAL/scratch blindly |
| Backup | Any failed/empty job or latest verified off-host copy older than scheduled interval plus approved grace | Database owner: restore coverage immediately and record exposed recovery window |
| PITR archive | Provider/WAL archive failure or archive age exceeds approved recovery point | Database owner: repair archiving and verify complete base-backup/WAL chain |
| Cleanup | Nonzero command exit, missing scheduled run or repeated full batches | Data owner: investigate backlog/DB access, then run more bounded batches |
| Certificate/secrets | Certificate within 14 days of expiry or provider-defined rotation warning | Domain/identity/GitHub owner: renew and test without exposing keys |
| GitHub delivery | Failed deliveries, retry budget exhaustion or reconciliation-required code | GitHub owner: inspect safe IDs/current head, reconcile or redeliver with approval |

Use opaque IDs and counts in alert payloads. The health endpoints and completion
logs exist; a metrics exporter, dashboard, remote scheduler and paging service
are not installed. Record the alarm destination, backup contact and rehearsal
time in the owner checklist.

## Backup and recovery

Use [the backup and restore runbook](backup-restore.md) for encrypted PostgreSQL
backups with restricted operator access and independently tested restore. Record
snapshot time, migration head, model/service version and retention. Keep backup
credentials separate from application credentials.

After restore: verify schema compatibility, confirm tenant-scoped reads/deletes,
reapply recorded deletion requests, and ensure interrupted jobs are not replayed
as new work. A durable deletion ledger is an operator requirement, not a feature
asserted by this runbook. Recovery time and recovery point objectives
remain owner decisions, not guarantees.

### Local PostgreSQL restore drill

Use [the dedicated drill](../scripts/ops_restore_drill.py) from a checkout with
Python 3.12, the `server,dev` extras, and a local Unix Docker daemon. It accepts
only a new output directory, **no database URL, container or restore target**.
It ignores application database settings and never attaches existing volumes.
Pull the reviewed digest explicitly; the drill itself uses `--pull=never`:

```bash
docker pull postgres:16.15-alpine3.23@sha256:621a761097839bdb50207afd6b87a72f38e2d718dd46c3d744828d8917c4f1e0
.venv/bin/python scripts/ops_restore_drill.py \
  --output-dir ".local/ops-drill/$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python -m pytest -o addopts='' -q scripts/test_release_ops_drill.py
```

The opt-in integration regression is
`BR_RUN_OPS_DRILL=1 .venv/bin/python -m pytest -o addopts='' -q scripts/test_release_ops_drill.py`.
Without the flag only the Docker integration case is skipped.

The drill creates one randomly named/labeled, nonroot, read-only PostgreSQL
container with tmpfs data and an ephemeral **loopback-only** port. Its random
credentials stay in process/container environment memory, not arguments, output
or artifact files. Docker daemon administrators can inspect container secrets;
use a trusted local machine. No Docker logs are retained. Source and restore DBs
are synthetic and live only in that new container. Cleanup verifies its ownership
label before removal; a forced machine/process kill may leave that disposable
container. Inspect its exact name and label before operator removal; do not bulk
delete containers or volumes.

The implementation performs these PostgreSQL operations only inside that owned
container, without `--clean`, `--create` or restoring over existing tables:

```text
pg_dump --username br_migrator --dbname br_drill_source --no-owner --no-privileges --format=custom
pg_restore --username br_migrator --dbname br_drill_restore --no-owner --no-privileges --exit-on-error --single-transaction
```

It applies the installed migrations twice, seeds a synthetic owner/project and
two explicitly failed sentinel analyses, restores to the empty second DB, and
compares every public table's row counts/data hash plus a schema catalog hash.
At migration `0004`, the seed also includes fresh/expired synthetic beta
requests, feedback and product events, so commercial records participate in
the same restore comparison.
The schema signature covers column order/types/length/precision/null/defaults,
constraint names/types/keys/referenced tables/actions/validation, and indexes.
It excludes CHECK expression text because PostgreSQL can rewrite equivalent
casts during dump/restore; an invalid membership role is separately rejected.
This is not exhaustive proof of every constraint's semantics.

It verifies foreign-key, unique-identity and role-check enforcement, runtime role
flags, migrator table ownership, and denied runtime DDL/migration-metadata writes.
The actual FastAPI lifespan checks `/health/live` and `/health/ready` via in-process
ASGI transport. The real operator cleanup command deletes one expired analysis
and its artifact, preserves usage/current evidence, audits the deletion and
removes zero on repetition. The source stays unchanged; a second nonempty restore
is refused.
Analysis deletion also proves feedback/event foreign-key cascades. The separate
`cleanup-commercial --limit 1` command runs three times: each of the first two
calls removes one expired row from each commercial table, and the third removes
zero. One fresh row per table survives; audits and usage preservation are checked.

Exit 0 writes `evidence.json` with exact invocation, pinned image, migration head,
counts/hashes, privilege/integrity/readiness/retention outcomes and measured
duration. Errors return nonzero with bounded diagnostics; do not print captured
subprocess output containing connection details. The private output directory
also holds a mode-0600 `synthetic.dump`. Share the **JSON**, not a real DB dump.
The file format is not encryption. Drill time is not a production recovery-time
objective: it excludes provision, download, decryption and real data volume.

For a glibc-based PostgreSQL image → Alpine, dump from the running old image before
changing it, retain that image and volume, then use a separately reviewed operator
procedure to restore into a new Alpine database/volume. This synthetic-only script deliberately
cannot accept that live backup. Validate locale/collation-dependent indexes and
queries before cutover; do not mount the old data directory into the new OS image.
Indexes are rebuilt by logical restore. PostgreSQL major upgrades additionally
require their reviewed upgrade procedure. The local drill is not certification of
arbitrary existing data.

The dump is plaintext on disk despite custom format. Production needs encrypted
backup storage, access controls, an independently stored key and restore tests;
do not upload raw database dumps to CI artifacts. Use the managed provider's
approved backup/PITR mechanism where applicable. A logical database dump excludes
roles, provider configuration and external encryption keys; keep their controlled
recovery inventory separately. Never back up application secrets in this repo.

### Production backup, encryption and PITR

The database owner must configure an approved scheduler and encrypted off-host
storage; none is installed by this repository. Use the provider's documented
backup/restore mechanism, enable its completion/age alarms, and record the actual
retention and recovery targets. Keep backup/key access independent of the runtime
role. Test recovering when the application host and its secret store are unavailable.

For PostgreSQL tooling, use a separately provisioned libpq service profile and
protected credential injection. A profile must not be a password-bearing URI in
shell history. The following is an **operator template, not executed production
backup automation**; `backup_service`, `backup_dir` and `encryption_recipient`
are approved nonsecret configuration. It requires PostgreSQL client tools and an
operator-approved `age` installation:

```bash
set -euo pipefail
set -o noclobber
umask 077
: "${backup_service:?approved libpq service profile required}"
: "${backup_dir:?private backup directory required}"
: "${encryption_recipient:?approved age public recipient required}"
test -d "$backup_dir"
backup="$backup_dir/blastradius-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
test ! -e "$backup"
pg_dump --dbname="service=$backup_service" --format=custom --no-owner --no-privileges \
  | age --encrypt --recipient "$encryption_recipient" > "$backup"
test -s "$backup"
sha256sum "$backup"
```

Pipe failure must fail the scheduler job and alert; a partial file is not a
completed backup. Publish the success inventory/checksum only after the command,
encrypted off-host transfer and storage verification all succeed. Protect any
failure logs from connection details. Assign a backup identity able to read every
required table and verify that row-level restrictions do not silently omit data.
A daily scheduler should run this reviewed wrapper with a nonoverlap lock,
bounded runtime and failure notification; pick the interval from the approved
recovery point target, not from this example. Enforce storage lifecycle expiry
only after reviewing holds and successful restore evidence.

Logical dumps recover the dump's consistent snapshot; they **do not provide
PITR**. PostgreSQL PITR requires a physical base backup plus continuous WAL
archiving (or a provider facility that implements it). The owner must record the
WAL retention window, archive health, key availability and chosen recovery time,
then rehearse an isolated restore to that timestamp. Test logical and PITR
restores separately. Never feed an untrusted dump to an unrestricted production
server: restore can execute SQL supplied by the source.

After provider restore, keep egress/webhooks/admission disabled until schema,
tenant isolation, counts/evidence, role grants, deletion-ledger replay and health
are verified. Restore secrets/roles/provider settings from their controlled
inventory separately. Queued work is not replayable from a logical backup.
Reconcile GitHub publication with current PR heads before authorizing delivery.
No managed-backup, failover or disaster-recovery acceptance is claimed by the
local drill.

References: [pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html),
[pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html),
[logical dumps](https://www.postgresql.org/docs/16/backup-dump.html),
[continuous archiving / PITR](https://www.postgresql.org/docs/16/continuous-archiving.html),
[connection service files](https://www.postgresql.org/docs/16/libpq-pgservice.html),
[age encryption usage](https://github.com/FiloSottile/age#usage).

### SQLite local backup

SQLite is local-only. Stop the local server, then use SQLite's backup API rather
than copying a live database without its WAL:

```bash
umask 077
mkdir -p .local/backups
.venv/bin/python -c 'import sqlite3; from pathlib import Path; source = sqlite3.connect(Path(".local/server.db").resolve().as_uri() + "?mode=ro", uri=True); target = sqlite3.connect(".local/backups/server-restore-check.db"); source.backup(target); assert target.execute("PRAGMA integrity_check").fetchone() == ("ok",); source.close(); target.close()'
```

Use a new backup filename for each run. Test the restored copy in a separate
workspace/configuration; do not overwrite the active SQLite file.

## Retention and operator schedule

The following initial schedule requires an assigned operator and approved policy.
No cron, hosted backup service, scheduled report cleanup or deletion ledger is
installed by these docs. The bounded cleanup command exists, but absence of the
approved schedule and recovery controls remains a promotion blocker.

| Cadence | Owner/action | Evidence |
|---|---|---|
| Every release | Release operator: image/dependency/secret audits, migrate, readiness, restore drill | Source SHA, image IDs, full JSON/SARIF, migration head and restore result |
| Daily | Database operator: encrypted backup; verify completion/size and a 30-day retention policy | Backup inventory and checksum; alert on missed/empty backup |
| Daily | Service operator: inspect disk/WAL/scratch and failed/restarted jobs | Capacity trend, cleanup failures; do not delete active scratch |
| Daily initially | Data owner: `BR_ADMIN_ENABLED=true blastradius-admin cleanup --limit 100` in the restricted operator environment | Exit status and JSON `removed` count; alert on failure or persistent backlog, audit `retention.cleanup` |
| Daily initially | Data owner: `BR_ADMIN_ENABLED=true blastradius-admin cleanup-commercial --limit 100` | Up to 100 expired rows from **each** of beta requests, feedback and product events; counts only, audit `commercial.cleanup` |
| Daily | Data owner: process approved deletion requests through tenant-authorized application paths | Access-controlled deletion log retained independently of backups |
| Weekly and before risky migrations | Database operator: restore into isolation and verify data/deletion replay | Measured restore duration and recorded recovery point |
| Daily | Logging owner: expire centralized logs after approved 14-day window | Retention job status; local size rotation alone is insufficient |
| Every 30 days | Data owner: review reports and expired sessions against tenant policy | Approved deletion/expiry evidence; no blanket SQL deletion of tenant rows |
| After 7 days | CI: expire scan artifacts through workflow retention | GitHub artifact lifecycle; archive release evidence securely if needed longer |

The 30-day backup and 14-day log windows are proposed operating defaults, not
customer promises. Agree legal/contractual retention and incident-hold exceptions
before installing automation. A live-record deletion does not instantly remove
that record from encrypted backups; restore access must reapply the deletion log,
and backups must expire on the approved schedule.

Inspect backup files older than the proposed window without deleting anything:

```bash
find .local/backups -maxdepth 1 -type f -name '*.dump' -mtime +29 -print
docker compose exec -T app sh -c 'du -sh /app/.local; df -h /app/.local'
docker compose exec -T db sh -c 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --command="SELECT pg_size_pretty(pg_database_size(current_database()))"'
```

Install deletion only after reviewing that inventory and confirming a successful
recent restore, incident holds, and the actual backup storage lifecycle policy.
Scratch cleans automatically after each finished worker and at service recovery;
alert on leftovers rather than racing a worker with a blanket `rm -rf`.
Run cleanup with one scheduler instance and a nonoverlap lock. If a batch removes
100, schedule further bounded batches within a fixed operator time budget; stop
at zero rather than an unbounded tight loop. Free/Pro/Team retention defaults are
7/90/365 days and Enterprise is configured through the plan policy. Review holds
and plan changes before enabling the schedule. Keep `BR_ADMIN_ENABLED=true`
confined to that job; never set it globally for the serving app.
Commercial records expire after 90 days independently of plan history.
For commercial cleanup, stop only when all three returned counts are zero;
repeat bounded invocations if any table has a backlog. Review and alert on
capacity (10,000 beta requests, 50,000 feedback records, 100,000 activity events).
Event capacity evicts oldest activity and is not a durable accounting ledger.
The optional `BR_RETENTION_SWEEP_SECONDS` timer runs both bounded cleanup passes
only on the lease-holding instance, immediately at startup and then at the
configured interval. Manual commands remain authoritative; user requests never
trigger cleanup, and the operator may opt in to the timer via
`BR_RETENTION_SWEEP_SECONDS`.

## Incident workflow

1. Restrict the affected surface or pause admission; preserve redacted evidence.
2. Identify affected versions, tenants and timeframe without dumping customer plans.
3. Revoke/rotate compromised credentials through the provider's approved process.
4. Recover using a reviewed image/database procedure; do not run destructive
   rollback commands reflexively.
5. Validate isolation, readiness and delayed jobs before restoring traffic.
6. Follow approved legal/security notification obligations and record follow-up tests.

For an analysis correctness incident, retain model/input hashes when permitted,
mark affected reports for review, and never silently rewrite past decisions.
Contact routing is in [support](support.md) and [security policy](../SECURITY.md).

## Beta administration

The local `blastradius-admin` entrypoint (also
`python -m blastradius.server.admin`) requires `BR_ADMIN_ENABLED=true` and the
configured database URL. It is not an HTTP administrator role. Never expose a
command runner or arbitrary database credentials to workspace users.

```bash
BR_ADMIN_ENABLED=true blastradius-admin inspect organizations --limit 100
BR_ADMIN_ENABLED=true blastradius-admin inspect users --limit 100
BR_ADMIN_ENABLED=true blastradius-admin inspect projects --limit 100
BR_ADMIN_ENABLED=true blastradius-admin inspect failures --limit 100
BR_ADMIN_ENABLED=true blastradius-admin inspect usage --limit 100
BR_ADMIN_ENABLED=true blastradius-admin inspect beta-requests --limit 100
BR_ADMIN_ENABLED=true blastradius-admin inspect feedback --limit 100
BR_ADMIN_ENABLED=true blastradius-admin inspect events
BR_ADMIN_ENABLED=true blastradius-admin assign-plan WORKSPACE_ID team
BR_ADMIN_ENABLED=true blastradius-admin assign-plan WORKSPACE_ID enterprise \
  --limits '{"projects":50,"analyses_per_month":10000,"retention_days":180,"members":50}'
BR_ADMIN_ENABLED=true blastradius-admin cleanup --limit 100
BR_ADMIN_ENABLED=true blastradius-admin cleanup-commercial --limit 100
```

Assign-plan locks the workspace, persists the central plan identifier and
validated Enterprise overrides, and appends an audit event with before/after
state. There is no subscription activation. Non-Enterprise assignments clear
old overrides. Inspect commands are bounded and omit source, cookies and tokens;
user inspection intentionally includes identity email for trusted operators.
Both read inspection and plan assignments are audited as `operator`.

Cleanup removes bounded batches of expired analysis records and child evidence;
see [retention and scheduling](data-lifecycle.md). Usage is not refunded.
User requests never trigger cleanup; the operator may opt in to the timer via
`BR_RETENTION_SWEEP_SECONDS`.

The separate read-only `/operator` UI requires verified OIDC and
`BR_WEB_ADMIN_USER_IDS`; CLI enablement and workspace roles do not grant access.
Follow [web operator setup](owner-setup.md#web-operator-and-commercial-data-setup)
and the [commercial contract](beta-api.md). Beta requests and feedback contain
private review text; do not copy them into monitoring, public issues or URLs.

The worker emits JSON `event:"analysis.completed"` logs with `analysis_id`,
`request_id`, `organization_id`, `project_id`, `outcome` and `duration_ms`.
These describe actual completion rather than timed progress. Existing HTTP error
logs omit request content; proxy access logs must continue omitting callback
queries and invitation fragments.
