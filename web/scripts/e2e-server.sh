#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/web/.e2e"
RUN="$(mktemp -d "$ROOT/web/.e2e/run-XXXXXXXX")"
export BR_ENV=test BR_AUTH_MODE=demo BR_PUBLIC_URL=http://127.0.0.1:5173
export BR_DATABASE_URL="sqlite:///$RUN/test.db" BR_DATA_DIR="$RUN/data"
export BR_RATE_LIMIT=10000 BR_DEMO_RATE_LIMIT=10000 BR_AUTH_RATE_LIMIT=1000
export BR_AUTO_MIGRATE=true
export BR_STRIPE_SECRET_KEY='' BR_STRIPE_WEBHOOK_SECRET='' BR_STRIPE_PRICE_PRO='' BR_STRIPE_PRICE_TEAM=''
export PYTHONPATH="$ROOT"
exec "$ROOT/.venv/bin/python" -m uvicorn blastradius.server.app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
