#!/usr/bin/env bash
# Build and start the production frontend for the Playwright suite against an EXPLICIT throwaway backend.
# Next.js fixes the /api/v1 rewrite target at build time, so the origin must be set before `next build`; this script
# refuses to run without it, refuses the development backend's port 8000, and checks the built rewrite before start.
# Usage: INTELLISTUDY_API_ORIGIN=http://127.0.0.1:8100 E2E_FRONTEND_PORT=3100 scripts/e2e-frontend.sh
set -euo pipefail

ORIGIN="${INTELLISTUDY_API_ORIGIN:?INTELLISTUDY_API_ORIGIN must be set explicitly for E2E}"
PORT="${E2E_FRONTEND_PORT:?E2E_FRONTEND_PORT must be set explicitly}"
if [[ ! "$ORIGIN" =~ ^http://127\.0\.0\.1:[0-9]{4,5}$ || "$ORIGIN" == *":8000" ]]; then
  echo "e2e-frontend: refusing backend origin '$ORIGIN' (must be http://127.0.0.1:<port>, never :8000)" >&2
  exit 2
fi
export INTELLISTUDY_E2E=1 NEXT_TELEMETRY_DISABLED=1
cd "$(dirname "$0")/.."
npx next build
if ! node -e '
  const m = require("./.next/routes-manifest.json");
  const all = [...(m.rewrites?.beforeFiles ?? []), ...(m.rewrites?.afterFiles ?? []), ...(m.rewrites?.fallback ?? [])];
  const api = all.filter((r) => r.source === "/api/v1/:path*");
  process.exit(api.length === 1 && api[0].destination === process.argv[1] + "/api/v1/:path*" ? 0 : 1);
' "$ORIGIN"; then
  echo "e2e-frontend: the build does not rewrite /api/v1 to $ORIGIN; refusing to start" >&2
  exit 3
fi
exec npx next start --port "$PORT"
