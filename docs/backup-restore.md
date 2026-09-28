# PostgreSQL backup and restore

This runbook describes the logical backup and restore procedure for the private
beta. It is an operator procedure, not a claim that the free Render plan
provides managed backup or point-in-time recovery.

## Scope

A PostgreSQL backup includes the application tables and their relationships,
including:

- `users`, `organizations`, `memberships`, and `projects`;
- `analyses`, `findings`, `attack_paths`, `attack_path_hops`, and
  `analysis_artifacts`;
- policy snapshots stored in `analyses.policy_snapshot`;
- plan assignments stored in `organizations.plan` and
  `organizations.plan_limits`; and
- the `github_*` tables, including installations, deliveries, and runs.

The database backup does **not** contain the session secret, OIDC secrets, or
the GitHub private key. Those values live in the environment or secret store
and must be backed up, rotated, and restored separately.

## Backup procedure

Set `BR_SOURCE_DATABASE_URL` in the trusted operator environment, then run:

```bash
scripts/pg_migrate.sh dump /secure/backup/path/blastradius-$(date -u +%Y%m%dT%H%M%SZ)
```

The script invokes `pg_dump --format=custom` and records non-sensitive row
counts and the Alembic head beside the dump. For the private beta, take a
backup daily, before every deployment, and before every migration.

### Encrypted storage expectation

Dump files are sensitive. Store them encrypted at rest with `age`, `gpg`, or a
provider-encrypted bucket; restrict access to approved recovery operators;
delete copies when they are superseded; and never commit a dump to this
repository. Keep backup credentials separate from application credentials.

## Restore procedure

Restore only into a fresh, empty target database:

```bash
export BR_TARGET_DATABASE_URL='postgresql://.../empty-target'
scripts/pg_migrate.sh restore /secure/backup/path/blastradius-YYYYmmddTHHMMSSZ
```

Then apply migrations and verify:

```bash
python -m blastradius.server.migrate
# Or, where Alembic is operated directly:
# alembic upgrade head
scripts/pg_migrate.sh verify /secure/backup/path/blastradius-YYYYmmddTHHMMSSZ
```

Never restore into a non-empty database. The migration step should be a no-op
when the restored rehearsal target is already at migration revision `0004`.

## Integrity validation

Record row counts per table and compare source with target. Confirm the
Alembic head, and confirm that `Database.ready()` returns `True` using the
target settings. Spot-check one organization through its members, projects,
analyses, and findings; use opaque IDs and counts in recovery evidence rather
than names, email addresses, or other personal data.

Keep the old database untouched until all verification passes. If verification
fails, switch `BR_DATABASE_URL` back to the old database, investigate the
target separately, and do not retry by restoring over a non-empty target.

## Beta recovery objectives

The private-beta recommendation is an RPO of 24 hours with daily dumps and an
RTO of one hour on the free tier. Production V1 requires managed PITR and
tested restores. That is a Production V1 target, not an achieved capability
of this beta deployment.

## Hosted-to-local rehearsal evidence

The rehearsal used the hosted Render database as the source and a fresh,
disposable PostgreSQL 18.6 database on local port `55432` as the target. The
source URL was loaded from `/home/ubuntu/beta-prep/.render_db_url` into
`BR_SOURCE_DATABASE_URL` without printing it. A new `br_restore_drill` database
was created, and the sequence was dump, restore, migration, and verify.

The restore reached Alembic `0004`; `python -m blastradius.server.migrate`
completed with no migration output, and `scripts/pg_migrate.sh verify`
reported `23 tables match, head 0004`. The target check returned
`Database.ready()=True`.

The exact requested count queries produced these sanitized result sets:

### Source

```text
users|2
organizations|3
memberships|3
projects|2
analyses|11
findings|32
attack_paths|4
attack_path_hops|20
analysis_artifacts|24
analyses_with_policy_snapshot|11
```

Plan distribution:

```text
free|3
```

Alembic head:

```text
0004
```

### Target

```text
users|2
organizations|3
memberships|3
projects|2
analyses|11
findings|32
attack_paths|4
attack_path_hops|20
analysis_artifacts|24
analyses_with_policy_snapshot|11
```

Plan distribution:

```text
free|3
```

Alembic head:

```text
0004
```

No names, email addresses, credentials, or other personal data were recorded.
The disposable dump directory was deleted after the rehearsal, and no dump or
environment file was added to the repository.
