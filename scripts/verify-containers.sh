#!/usr/bin/env bash
set -euo pipefail

app_image=${1:-blastradius:local}
db_image=${2:-blastradius-postgres:local}
prefix="br-container-check-${RANDOM}-$$"
db="$prefix-db"
app="$prefix-app"
network="$prefix-net"
cleanup() {
  docker rm -f -v "$app" "$db" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker network create --internal "$network" >/dev/null

hardening=(--read-only --cap-drop ALL --security-opt no-new-privileges:true
  --pids-limit 128 --cpus 2 --memory 2g --tmpfs /tmp:size=64m,mode=1777)
app_options=(--network "$network" "${hardening[@]}"
  --tmpfs /app/.local:size=128m,uid=10001,gid=10001,mode=700
  -e BR_ENV=development -e BR_AUTH_MODE=demo -e BR_AUTO_MIGRATE=false
  -e BR_PUBLIC_URL=http://localhost:8000
  -e "BR_DATABASE_URL=postgresql+psycopg://container_test:local-container-test-only@$db:5432/container_test")

docker run -d --name "$db" --network "$network" "${hardening[@]}" \
  --tmpfs /var/lib/postgresql/data:size=256m,uid=999,gid=999,mode=700 \
  --tmpfs /var/run/postgresql:size=16m,uid=999,gid=999,mode=3775 \
  -e POSTGRES_USER=container_test -e POSTGRES_DB=container_test \
  -e POSTGRES_PASSWORD=local-container-test-only \
  --health-cmd='pg_isready -U container_test -d container_test' \
  --health-interval=2s --health-timeout=5s --health-retries=30 "$db_image" >/dev/null

wait_healthy() {
  for ((attempt=0; attempt<90; attempt++)); do
    if [ "$(docker inspect --format '{{.State.Health.Status}}' "$1")" = healthy ]; then
      return
    fi
    if [ "$(docker inspect --format '{{.State.Running}}' "$1")" != true ]; then
      break
    fi
    sleep 2
  done
  docker logs "$1"
  echo "Container did not become healthy: $1" >&2
  return 1
}
wait_healthy "$db"
docker exec "$db" sh -ec '
  test "$(id -u)" = 999
  test ! -w /etc/passwd
  test ! -e /usr/local/bin/gosu
  test -s /var/lib/dpkg/status
  for tool in gcc cc make gpg gpgconf dirmngr; do
    ! command -v "$tool"
  done
'

docker run --rm "${app_options[@]}" --entrypoint python "$app_image" \
  -I -m alembic -c /app/alembic.ini upgrade 0001
docker exec "$db" psql -U container_test -d container_test -v ON_ERROR_STOP=1 \
  -c "CREATE TABLE container_restore_probe (value text NOT NULL); INSERT INTO container_restore_probe VALUES ('preserved');"
docker run --rm "${app_options[@]}" "$app_image" migrate
docker run --rm "${app_options[@]}" "$app_image" migrate
docker exec "$db" sh -ec '
  pg_dump -U container_test -d container_test -Fc -f /tmp/restore.dump
  createdb -U container_test restored
  pg_restore -U container_test --exit-on-error -d restored /tmp/restore.dump
  test "$(psql -U container_test -d restored -Atc "SELECT value FROM container_restore_probe")" = preserved
  test "$(psql -U container_test -d container_test -Atc "SELECT version_num FROM alembic_version")" = \
       "$(psql -U container_test -d restored -Atc "SELECT version_num FROM alembic_version")"
  rm /tmp/restore.dump
'
docker run --rm "${app_options[@]}" \
  -e "BR_DATABASE_URL=postgresql+psycopg://container_test:local-container-test-only@$db:5432/restored" \
  "$app_image" migrate

docker run -d --name "$app" "${app_options[@]}" \
  --health-interval=2s --health-start-period=5s "$app_image" >/dev/null
wait_healthy "$app"
docker exec "$app" sh -ec '
  test "$(id -u)" = 10001
  test ! -w /app/alembic.ini
  test ! -d /app/blastradius
  test ! -d /usr/local/include/python3.12
  test -s /lib/apk/db/installed
  for tool in gcc cc make git node npm pip; do
    ! command -v "$tool"
  done
'
docker exec -i "$app" python -I - <<'PY'
import importlib.util
import json
import os
from pathlib import Path
import sys
import urllib.request

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from blastradius.security.decision import Decision
from blastradius.server.config import Settings
from blastradius.server.demos import build_demos

assert sys.version_info[:2] == (3, 12)
assert importlib.util.find_spec("pip") is None
assert psycopg.pq.__impl__ == "binary"
url = os.environ["BR_DATABASE_URL"].replace("postgresql+psycopg:", "postgresql:")
with psycopg.connect(url) as connection:
    head = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert head == ScriptDirectory.from_config(Config("/app/alembic.ini")).get_current_head()
    assert connection.execute("SELECT value FROM container_restore_probe").fetchone()[0] == "preserved"
with urllib.request.urlopen("http://localhost:8000/health/ready") as response:
    assert response.status == 200
with urllib.request.urlopen("http://localhost:8000/") as response:
    assert b'<div id="root">' in response.read()
demos = build_demos(Settings(data_dir=Path(os.environ["BR_DATA_DIR"])))
assert len(demos) == 9
for (scenario, stage), result in demos.items():
    expected = Decision.BLOCK if stage == "risky" else Decision.SAFE
    assert result["decision"] == expected.value, (scenario, stage, result["decision"])
assert not list(Path("/app/.local/jobs").glob("job-*"))
print(json.dumps({"psycopg": psycopg.__version__, "python": sys.version,
                  "migration_head": head, "installed_worker_cases": len(demos)}))
PY

expect_usage_error() {
  local status=0
  docker run --rm "${app_options[@]}" "$@" || status=$?
  test "$status" = 2
}
expect_usage_error "$app_image" invalid-command
expect_usage_error -e BLASTRADIUS_ALEMBIC_CONFIG=/missing "$app_image" migrate
echo "Container checks passed: migrations, restore, psycopg, installed workers, health, non-root/read-only."
