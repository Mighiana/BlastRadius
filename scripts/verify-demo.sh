#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

run_expected() {
  local expected="$1"
  shift
  local code=0
  "$PYTHON" -m blastradius.cli "$@" || code=$?
  if [[ "$code" != "$expected" ]]; then
    printf 'Expected exit %s, received %s\n' "$expected" "$code" >&2
    return 1
  fi
}

for scenario in public_ssh broad_iam public_bucket; do
  case "$scenario" in
    public_ssh) before=examples/safe; after=examples/vulnerable ;;
    *) before="examples/scenarios/$scenario/before"; after="examples/scenarios/$scenario/after" ;;
  esac
  printf '\nScenario: %s (baseline, risky, restored)\n' "$scenario"
  run_expected 0 --before "$before" --after "$before"
  run_expected 1 --before "$before" --after "$after"
  run_expected 0 --before "$after" --after "$before"
done
