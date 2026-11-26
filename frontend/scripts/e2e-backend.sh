#!/usr/bin/env bash
# Start a throwaway FastAPI backend for the Playwright suite (gates GF0A-14..22, GF0B-*).
# - Fresh SQLite database and storage in a temporary directory; nothing touches data/backend/ or data/uploads/.
# - Started from that directory, so the repository's .env (secrets, provider keys) is never read; every setting is
#   given here. Throwaway JWT secret, no LLM provider.
# - The document-processing worker is on (F0-B: uploads must reach real terminal states); E2E_WORKER_ENABLED=false
#   turns it off.
# - LLM: the DETERMINISTIC TEST PROVIDER tests/e2e/fixtures/stub_llm.py on 127.0.0.1:$E2E_LLM_PORT, through the
#   backend's existing `local` provider slot (F1). Never a real model, never a key, no network.
# - Ports are required and explicit (E2E_BACKEND_PORT, E2E_LLM_PORT); the development port 8000 is refused.
# - Rate limits are the real ones (no test switch exists); the suite stays within them.
# Usage: scripts/e2e-backend.sh  (E2E_PYTHON=/path/to/python to choose the interpreter)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${E2E_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$REPO/.venv/bin/python" ]]; then PY="$REPO/.venv/bin/python"; else PY="python3"; fi
fi
PORT="${E2E_BACKEND_PORT:?E2E_BACKEND_PORT must be set explicitly}"
LLM_PORT="${E2E_LLM_PORT:?E2E_LLM_PORT must be set explicitly}"
for p in "$PORT" "$LLM_PORT"; do
  if [[ ! "$p" =~ ^[0-9]{4,5}$ || "$p" == "8000" ]]; then
    echo "e2e-backend: refusing port '$p' (8000 is the development backend)" >&2
    exit 2
  fi
done
WORK="$(mktemp -d -t intellistudy-e2e-XXXXXX)"
STUB_PID=""
API_PID=""
cleanup() {
  # Stop both processes (escalating to SIGKILL after about 3 s, so a stuck shutdown cannot keep the temp dir alive),
  # then delete the temporary database, storage and work files.
  for pid in "$API_PID" "$STUB_PID"; do
    [[ -n "$pid" ]] || continue
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 15); do kill -0 "$pid" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$pid" 2>/dev/null || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT
trap 'exit 143' TERM INT

export PYTHONPATH="$REPO"
# No network during the run: the embedding model is loaded from the local Hugging Face cache (CI fetches it in an
# earlier step). E2E_HF_OFFLINE=0 allows a download for a first local run.
export HF_HUB_OFFLINE="${E2E_HF_OFFLINE:-1}" TRANSFORMERS_OFFLINE="${E2E_HF_OFFLINE:-1}"
export INTELLISTUDY_PROFILE=demo
export INTELLISTUDY_JWT_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export INTELLISTUDY_LLM_PROVIDER=local
export INTELLISTUDY_LLM_BASE_URL="http://127.0.0.1:$LLM_PORT/v1"
export INTELLISTUDY_LLM_MODEL=deterministic-test-stub
export INTELLISTUDY_LLM_MAX_RETRIES=0
export INTELLISTUDY_LLM_TIMEOUT_SECONDS=10
export INTELLISTUDY_DATABASE_URL="sqlite:///$WORK/e2e.sqlite3"
export INTELLISTUDY_DATA_DIR="$WORK"
export INTELLISTUDY_STORAGE_ROOT="$WORK/storage"
export INTELLISTUDY_WORKER_ENABLED="${E2E_WORKER_ENABLED:-true}"
export INTELLISTUDY_CORS_ORIGINS="${E2E_FRONTEND_ORIGIN:-http://localhost:3100}"

cd "$WORK"
# Preflight: retrieval must be the real one (embedder + re-ranker), loaded offline. Without a model the backend would
# fall back to a degraded search and the answer states would differ, so stop here with a clear message instead.
if ! "$PY" -c "
from ai.chunking.config import EMBEDDING_MODEL
from ai.retrieval.rerank import DEFAULT_RERANKER_MODEL
from sentence_transformers import CrossEncoder, SentenceTransformer
SentenceTransformer(EMBEDDING_MODEL); CrossEncoder(DEFAULT_RERANKER_MODEL)
" >/dev/null 2>&1; then
  echo "e2e-backend: the retrieval models are not in the local Hugging Face cache (run once with E2E_HF_OFFLINE=0)" >&2
  exit 4
fi
"$PY" -I "$REPO/frontend/tests/e2e/fixtures/stub_llm.py" "$LLM_PORT" &
STUB_PID=$!
"$PY" -m backend.app.db.migrate >/dev/null
"$PY" -m uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port "$PORT" --log-level warning &
API_PID=$!
wait "$API_PID"
