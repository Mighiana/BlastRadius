#!/bin/sh
set -eu

serve_app() {
  if [ "${BR_TRUST_PROXY_HEADERS:-false}" = "true" ]; then
    exec python -I -m uvicorn blastradius.server.app:app \
      --host 0.0.0.0 --port 8000 --workers 1 --no-access-log \
      --proxy-headers --forwarded-allow-ips='*'
  fi
  exec python -I -m uvicorn blastradius.server.app:app \
    --host 0.0.0.0 --port 8000 --workers 1 --no-access-log --no-proxy-headers
}

run_migrations() {
  if [ -z "${BLASTRADIUS_ALEMBIC_CONFIG:-}" ] || [ ! -f "$BLASTRADIUS_ALEMBIC_CONFIG" ]; then
    echo "Set BLASTRADIUS_ALEMBIC_CONFIG to the server's existing Alembic config." >&2
    exit 2
  fi
  python -I -m alembic -c "$BLASTRADIUS_ALEMBIC_CONFIG" upgrade head
}

case "${1:-serve}" in
  serve)
    serve_app
    ;;
  sh)
    shift
    [ "${1:-}" = "/app/scripts/container-entrypoint.sh" ] && shift
    exec sh /app/scripts/container-entrypoint.sh "$@"
    ;;
  migrate)
    run_migrations
    ;;
  migrate-serve)
    run_migrations
    serve_app
    ;;
  *)
    echo "Expected serve, migrate or migrate-serve." >&2
    exit 2
    ;;
esac
