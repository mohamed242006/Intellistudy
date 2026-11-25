#!/usr/bin/env bash
# Start a throwaway FastAPI backend for the Playwright suite (gate GF0A-14..22).
# - Fresh SQLite database and storage in a temporary directory; nothing touches data/backend/.
# - Started from that directory, so the repository's .env (secrets, provider keys) is never read; every setting is
#   given here. Throwaway JWT secret, no LLM provider, background workers off.
# - Rate limits are the real ones (no test switch exists); the suite stays within them.
# Usage: scripts/e2e-backend.sh  (E2E_PYTHON=/path/to/python to choose the interpreter)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${E2E_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$REPO/.venv/bin/python" ]]; then PY="$REPO/.venv/bin/python"; else PY="python3"; fi
fi
PORT="${E2E_BACKEND_PORT:-8100}"
WORK="$(mktemp -d -t intellistudy-e2e-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

export PYTHONPATH="$REPO"
export INTELLISTUDY_PROFILE=demo
export INTELLISTUDY_JWT_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export INTELLISTUDY_LLM_PROVIDER=none
export INTELLISTUDY_DATABASE_URL="sqlite:///$WORK/e2e.sqlite3"
export INTELLISTUDY_DATA_DIR="$WORK"
export INTELLISTUDY_STORAGE_ROOT="$WORK/storage"
export INTELLISTUDY_WORKER_ENABLED=false
export INTELLISTUDY_CORS_ORIGINS="${E2E_FRONTEND_ORIGIN:-http://localhost:3100}"

cd "$WORK"
"$PY" -m backend.app.db.migrate >/dev/null
"$PY" -m uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port "$PORT" --log-level warning
