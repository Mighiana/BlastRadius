#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3.12}"
command -v "$PYTHON" >/dev/null || { printf 'Install Python 3.12 or set PYTHON to its executable.\n' >&2; exit 1; }
command -v node >/dev/null || { printf 'Install Node 24.19.0 (see web/.nvmrc).\n' >&2; exit 1; }
"$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install "$ROOT[server,ui,dev]"
npm --prefix "$ROOT/web" ci
printf '\nSetup complete. Start the API and Vite with the commands in docs/frontend.md.\n'
