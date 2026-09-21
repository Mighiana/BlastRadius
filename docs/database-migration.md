# Moving the service database to another PostgreSQL provider

BlastRadius stores every SaaS record (users, workspaces, projects, analyses,
findings, artifacts, feedback) in one PostgreSQL database referenced by
`BR_DATABASE_URL`. Nothing in the application depends on the provider: the move
is a logical dump, a restore into an empty database, an environment-variable
switch and one migration run. This page is provider-neutral; the Render free
database (deleted after its 30-day window unless upgraded) is only the current
example of a temporary source.

Helper: [`scripts/pg_migrate.sh`](../scripts/pg_migrate.sh). It reads connection
strings **only** from `BR_SOURCE_DATABASE_URL` / `BR_TARGET_DATABASE_URL`, never
from arguments, and never prints them. It needs `pg_dump`, `pg_restore` and `psql`
whose major version is **at least** the source server's (`SELECT version()`), so a
PostgreSQL 18 source needs 18.x client tools.

## 1. Prepare the target

1. Create an empty PostgreSQL database on the new provider (same or newer major
   version; UTF-8; TLS reachable from wherever the app runs). Do not create any
   tables or run migrations in it yet - the restore refuses a non-empty target.
2. Create the application role and, if you separate them, a migrator role
   (see [environment-production.md](environment-production.md)).
3. Record the new connection URL as `postgresql://…?sslmode=require` (or
   `verify-full` with the provider CA). Keep it in the secret store only.

## 2. Freeze writes on the source

Users must not create analyses between dump and switch. Either suspend the web
service (Render: **Suspend**) or announce a short maintenance window and stop the
service; a running worker could otherwise finish an analysis after the dump.

## 3. Dump

```bash
export BR_SOURCE_DATABASE_URL='postgresql://…?sslmode=require'   # from the secret store
scripts/pg_migrate.sh dump ./db-move/$(date -u +%Y%m%dT%H%M%SZ)
```

Produces, mode 0600, in the output directory: `blastradius.dump` (custom format,
`--no-owner --no-privileges`), `source-counts.txt` (row count per table),
`source-alembic-head.txt`, `dumped-at.txt`. The dump contains real tenant data
and user e-mails: keep it on an encrypted disk, do not attach it to tickets, and
delete it after the move is validated.

## 4. Restore into the empty target

```bash
export BR_TARGET_DATABASE_URL='postgresql://…?sslmode=require'
scripts/pg_migrate.sh restore ./db-move/<dir>
```

`pg_restore --no-owner --no-privileges --exit-on-error --single-transaction`:
any error rolls the whole restore back, leaving the target empty. If the target
already has public tables the script exits 3 and does nothing - drop and recreate
the empty database rather than restoring over data.

## 5. Run migrations against the target

The dump carries `alembic_version`, so this is normally a no-op that proves the
application can open the copy. Use the production environment (same image/tag as
the running service):

```bash
BR_DATABASE_URL="$BR_TARGET_DATABASE_URL" BR_ENV=production BR_AUTO_MIGRATE=false … \
  python -I -m alembic -c "$BLASTRADIUS_ALEMBIC_CONFIG" upgrade head
```

In the container this is `sh /app/scripts/container-entrypoint.sh migrate`.
If you are also upgrading the application, run the new image's migrations here,
before any user reaches the new database.

## 6. Validate

```bash
scripts/pg_migrate.sh verify ./db-move/<dir>
```

Exit 0 means every table's row count equals the source dump and the Alembic
head matches. Then:

```text
[ ] verify exit 0 (counts.diff empty, same migration head)
[ ] target `SELECT version()` >= source major version
[ ] app readiness against the target: /health/ready returns 200 with
    BR_DATABASE_URL pointing at the new database (staging instance or a local
    container of the production image)
[ ] one existing tester signs in, sees their workspace, projects and history
[ ] one new analysis runs to a terminal state and its exports download
[ ] retention cleanup (`blastradius-admin cleanup`) runs and removes zero or the
    expected expired rows
```

## 7. Switch the environment variable

Set `BR_DATABASE_URL` on the web service to the target URL (Render: Environment
→ edit `BR_DATABASE_URL`, remove the `fromDatabase` link if the blueprint created
it), keep `BR_AUTO_MIGRATE=false`, redeploy/resume the service, and re-run the
readiness and sign-in checks above on the live URL. Rotate the old database
credentials once traffic has moved; keep the old database read-only (or the
final dump) for the rollback window.

## 8. Rollback

Within the rollback window, rollback is the reverse switch: set
`BR_DATABASE_URL` back to the source URL and redeploy. Analyses created on the
target after the switch will not exist on the source; export them (JSON report
per analysis) before rolling back, or dump the target with the same script and
restore that dump into a fresh database instead. Never point both an old and a
new service instance at different databases at the same time, and never use
`alembic downgrade` or `pg_restore --clean` on a database that has served users.

## 9. Rehearsal record

Performed 2026-09-21 without touching the hosted beta database's content:

| Step | Result |
|---|---|
| Source | Render managed PostgreSQL 18.6 (beta), read-only `pg_dump` via TLS |
| Dump | 23 tables, migration head `0004`, 11 analyses / 32 findings / 24 artifacts / 46 product events |
| Target | Disposable local PostgreSQL 18.6 cluster, empty database |
| Restore | `--single-transaction --exit-on-error` succeeded; second restore into the now non-empty target refused (exit 3) |
| Migrations | `alembic upgrade head` against the copy: no pending revisions |
| Verify | 23/23 tables identical row counts, head `0004` |
| App | `Database.ready()` true on the copy; organizations 3, analyses 11 |

The disposable cluster and the dump were deleted afterwards. This proves the
procedure and tooling, not the new provider's durability, backup encryption or
point-in-time recovery - those remain owner decisions listed in
[readiness.md](readiness.md).
