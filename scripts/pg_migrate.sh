#!/bin/sh
# Provider-neutral PostgreSQL move for the BlastRadius service database.
#
#   scripts/pg_migrate.sh dump    OUT_DIR          # logical dump + source row counts
#   scripts/pg_migrate.sh restore DUMP_DIR         # restore into the EMPTY target
#   scripts/pg_migrate.sh verify  DUMP_DIR         # compare target counts with the dump
#
# Connection strings are read from the environment only, never from arguments:
#   BR_SOURCE_DATABASE_URL  (dump)            BR_TARGET_DATABASE_URL  (restore, verify)
# Both must be postgresql:// URLs. Use sslmode=require (or verify-full with a CA)
# for any provider-hosted database. Nothing here prints a connection string.
set -eu

usage() {
  echo "usage: $0 dump OUT_DIR | restore DUMP_DIR | verify DUMP_DIR" >&2
  exit 2
}

TABLES="users organizations memberships sessions projects analyses usage invitations \
audit_events findings attack_paths attack_path_hops analysis_artifacts billing_events \
github_installations repository_connections github_deliveries github_runs commercial_lock \
beta_interest analysis_feedback product_events alembic_version"

require_url() {
  name="$1"
  eval "value=\${$name:-}"
  case "$value" in
    postgresql://*|postgres://*) ;;
    *) echo "$name must be set to a postgresql:// URL (never passed as an argument)" >&2; exit 2 ;;
  esac
}

# Row counts per table, one "table count" line each, in a fixed order.
count_rows() {
  url="$1"
  for table in $TABLES; do
    count=$(psql "$url" --no-psqlrc --tuples-only --no-align --quiet \
      --command "SELECT count(*) FROM \"$table\"" 2>/dev/null || echo "missing")
    echo "$table $(echo "$count" | tr -d '[:space:]')"
  done
}

alembic_head() {
  psql "$1" --no-psqlrc --tuples-only --no-align --quiet \
    --command "SELECT version_num FROM alembic_version" | tr -d '[:space:]'
}

[ "$#" -eq 2 ] || usage
mode="$1"; dir="$2"

case "$mode" in
  dump)
    require_url BR_SOURCE_DATABASE_URL
    umask 077
    mkdir -p "$dir"
    pg_dump "$BR_SOURCE_DATABASE_URL" --format=custom --no-owner --no-privileges \
      --file "$dir/blastradius.dump"
    count_rows "$BR_SOURCE_DATABASE_URL" > "$dir/source-counts.txt"
    alembic_head "$BR_SOURCE_DATABASE_URL" > "$dir/source-alembic-head.txt"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$dir/dumped-at.txt"
    echo "dump written to $dir (mode 0600); migration head $(cat "$dir/source-alembic-head.txt")"
    ;;
  restore)
    require_url BR_TARGET_DATABASE_URL
    [ -f "$dir/blastradius.dump" ] || { echo "no blastradius.dump in $dir" >&2; exit 2; }
    existing=$(psql "$BR_TARGET_DATABASE_URL" --no-psqlrc --tuples-only --no-align --quiet \
      --command "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'" | tr -d '[:space:]')
    if [ "$existing" != "0" ]; then
      echo "target already has $existing public tables; restore only into an empty database" >&2
      exit 3
    fi
    pg_restore --dbname "$BR_TARGET_DATABASE_URL" --no-owner --no-privileges \
      --exit-on-error --single-transaction "$dir/blastradius.dump"
    echo "restore complete; target migration head $(alembic_head "$BR_TARGET_DATABASE_URL")"
    ;;
  verify)
    require_url BR_TARGET_DATABASE_URL
    [ -f "$dir/source-counts.txt" ] || { echo "no source-counts.txt in $dir" >&2; exit 2; }
    count_rows "$BR_TARGET_DATABASE_URL" > "$dir/target-counts.txt"
    status=0
    if ! diff "$dir/source-counts.txt" "$dir/target-counts.txt" > "$dir/counts.diff"; then
      echo "ROW COUNT MISMATCH (see $dir/counts.diff)" >&2
      status=4
    fi
    src_head=$(cat "$dir/source-alembic-head.txt")
    dst_head=$(alembic_head "$BR_TARGET_DATABASE_URL")
    if [ "$src_head" != "$dst_head" ]; then
      echo "MIGRATION HEAD MISMATCH: source $src_head target $dst_head" >&2
      status=4
    fi
    [ "$status" -eq 0 ] && echo "verify OK: $(wc -l < "$dir/target-counts.txt" | tr -d ' ') tables match, head $dst_head"
    exit "$status"
    ;;
  *) usage ;;
esac
