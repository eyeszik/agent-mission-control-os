#!/bin/sh
# Preview/dev entrypoint: starts the FastAPI backend, then the Next.js dev server.
# Freebuff injects PORT for the exposed (frontend) port; the backend keeps 8000
# internally. Never chain this behind other commands — run via `freebuff-preview`.
set -e
cd "$(dirname "$0")/.." || exit 1

export AMC_DB_PATH="${AMC_DB_PATH:-/tmp/amc_preview.db}"
export AMC_ENV="${AMC_ENV:-development}"
# Local auth defaults mirroring CI's browser-e2e backend env so the preview
# exercises the real signed-in request path; override any of these via env.
export AMC_AUTH_MODE="${AMC_AUTH_MODE:-local}"
export AMC_LOCAL_USER_ID="${AMC_LOCAL_USER_ID:-local-e2e}"
export AMC_LOCAL_TENANT_ID="${AMC_LOCAL_TENANT_ID:-tenant_1}"
export AMC_LOCAL_PROJECT_IDS="${AMC_LOCAL_PROJECT_IDS:-proj_1}"
export AMC_LOCAL_ROLE="${AMC_LOCAL_ROLE:-operator}"
export AMC_CORS_ALLOWED_ORIGINS="${AMC_CORS_ALLOWED_ORIGINS:-http://127.0.0.1:3000,http://localhost:3000}"
# Frontend env: point the browser at the in-sandbox API in local auth mode
# (same contract the CI browser-e2e job builds Next with).
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://127.0.0.1:8000}"
export NEXT_PUBLIC_AUTH_MODE="${NEXT_PUBLIC_AUTH_MODE:-local}"
PORT="${PORT:-3000}"

# Backend API (background within the preview process tree)
python3 -m uvicorn services.langgraph.app.main:app \
  --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

# Frontend dev server on the managed preview port, binding 0.0.0.0
cd apps/web
exec node_modules/.bin/next dev -p "$PORT" -H 0.0.0.0
