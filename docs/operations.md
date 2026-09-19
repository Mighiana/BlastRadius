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
The queue is in memory. Shutdown has 150 seconds for the default eight jobs/two
workers; increase the grace period if increasing those bounds. A forced stop or
host loss still loses queued work. Restart marks queued/running records failed
with `server_restarted` and cleans `BR_DATA_DIR/jobs/job-*`; it does not requeue.

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

## Backup and recovery

Use encrypted PostgreSQL backups with restricted operator access and independently
tested restore. Record snapshot time, migration head, model/service version and
retention. Keep backup credentials separate from application credentials.

After restore: verify schema compatibility, confirm tenant-scoped reads/deletes,
reapply recorded deletion requests, and ensure interrupted jobs are not replayed
as new work. A durable deletion ledger is an operator requirement, not a feature
asserted by this runbook. Recovery time and recovery point objectives
remain owner decisions, not guarantees.

### Local PostgreSQL restore drill

These commands were exercised against the non-root/read-only Compose database.
They create a logical dump and a separate restore database, never overwrite the
active database. Use a fresh restore name per drill; `createdb` fails if it exists.
Run from the checkout with its trusted local `.env`:

```bash
umask 077
mkdir -p .local/backups
backup=".local/backups/blastradius-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db sh -c 'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges' > "$backup"
test -s "$backup"
sha256sum "$backup"
docker compose exec -T db sh -c 'createdb --username="$POSTGRES_USER" blastradius_restore_check'
docker compose exec -T db sh -c 'exec pg_restore --username="$POSTGRES_USER" --dbname=blastradius_restore_check --no-owner --no-privileges --exit-on-error' < "$backup"
POSTGRES_DB=blastradius_restore_check docker compose run --rm --no-deps migrate
POSTGRES_DB=blastradius_restore_check docker compose run --rm --no-deps --entrypoint python migrate -I -c 'from blastradius.server.config import Settings; from blastradius.server.db import Database; db = Database(Settings.from_env()); assert db.ready(); db.engine.dispose(); print("restored schema ready")'
```

`--no-deps` is essential: the temporary `POSTGRES_DB` override must not recreate
the active database service. This drill checks dump restore and schema readiness.
Before a production cutover also verify real tenant counts, authorization/deletion
checks and application behavior in isolation; never expose a restored database
containing previously deleted customer data.

For Bookworm → Trixie, dump from the running old image before changing it, retain
that image and volume, then restore into a new Trixie database/volume using the
same `pg_restore` procedure. Validate locale/collation-dependent indexes and
queries before cutover; do not mount the old data directory into the new OS
image. PostgreSQL major upgrades additionally require their reviewed upgrade
procedure. The local drill is not certification of arbitrary existing data.

The dump is plaintext on disk despite custom format. Production needs encrypted
backup storage, access controls, an independently stored key and restore tests;
do not upload raw database dumps to CI artifacts. Use the managed provider's
approved backup/PITR mechanism where applicable. A logical database dump excludes
roles, provider configuration and external encryption keys; keep their controlled
recovery inventory separately. Never back up application secrets in this repo.

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
No cron, hosted backup service, automatic report expiry or deletion ledger is
installed by these docs. Absence of those controls remains a promotion blocker.

| Cadence | Owner/action | Evidence |
|---|---|---|
| Every release | Release operator: image/dependency/secret audits, migrate, readiness, restore drill | Source SHA, image IDs, full JSON/SARIF, migration head and restore result |
| Daily | Database operator: encrypted backup; verify completion/size and a 30-day retention policy | Backup inventory and checksum; alert on missed/empty backup |
| Daily | Service operator: inspect disk/WAL/scratch and failed/restarted jobs | Capacity trend, cleanup failures; do not delete active scratch |
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
