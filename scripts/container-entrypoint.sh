#!/bin/sh
set -eu

case "${1:-serve}" in
  serve)
    exec python -I -m uvicorn blastradius.server.app:app \
      --host 0.0.0.0 --port 8000 --workers 1 --no-access-log --no-proxy-headers
    ;;
  migrate)
    if [ -z "${BLASTRADIUS_ALEMBIC_CONFIG:-}" ] || [ ! -f "$BLASTRADIUS_ALEMBIC_CONFIG" ]; then
      echo "Set BLASTRADIUS_ALEMBIC_CONFIG to the server's existing Alembic config." >&2
      exit 2
    fi
    exec python -I -m alembic -c "$BLASTRADIUS_ALEMBIC_CONFIG" upgrade head
    ;;
  *)
    echo "Expected serve or migrate." >&2
    exit 2
    ;;
esac
