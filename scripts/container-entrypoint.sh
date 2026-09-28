#!/bin/sh
set -eu

materialize_github_key() {
  # Secret mounts can expose the App key as a symlink or with group/other
  # permissions; the verifier requires a regular file mode 0600 or stricter.
  # Copy the mounted contents (dereferencing links) into a private tmpfs file.
  src=${BR_GITHUB_PRIVATE_KEY_FILE:-}
  if [ -z "$src" ]; then
    return 0
  fi
  dst=${TMPDIR:-/tmp}/br-secrets
  mkdir -p "$dst"
  chmod 0700 "$dst"
  cp -L "$src" "$dst/github-app.pem"
  chmod 0600 "$dst/github-app.pem"
  BR_GITHUB_PRIVATE_KEY_FILE="$dst/github-app.pem"
  export BR_GITHUB_PRIVATE_KEY_FILE
}

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

materialize_github_key

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
