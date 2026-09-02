#!/usr/bin/env bash
set -euo pipefail
project_root=/home/workspace/Projects/agent-mission-control-os
: "${PORT:=8000}"
export AMC_ENV="${AMC_ENV:-local}"
export AMC_AUTH_MODE="${AMC_AUTH_MODE:-local}"
export AMC_DATABASE_BACKEND="${AMC_DATABASE_BACKEND:-sqlite}"
export AMC_LOCAL_USER_ID="${AMC_LOCAL_USER_ID:-local-operator}"
export AMC_LOCAL_TENANT_ID="${AMC_LOCAL_TENANT_ID:-tenant_1}"
export AMC_LOCAL_PROJECT_IDS="${AMC_LOCAL_PROJECT_IDS:-proj_1}"
export AMC_LOCAL_ROLE="${AMC_LOCAL_ROLE:-operator}"
export AMC_DB_PATH="${AMC_DB_PATH:-/home/workspace/Projects/agent-mission-control-os/amc_local.db}"
export AMC_EXPORT_ROOT="${AMC_EXPORT_ROOT:-/home/workspace/Documents/agent-mission-control-ideas}"
export AMC_CORS_ALLOWED_ORIGINS="${AMC_CORS_ALLOWED_ORIGINS:-http://127.0.0.1:3200,http://localhost:3200}"
export AMC_PUBLICATION_MODE="${AMC_PUBLICATION_MODE:-disabled}"
export AMC_PAID_MEDIA_MODE="${AMC_PAID_MEDIA_MODE:-disabled}"
cd "$project_root"
exec "$project_root/.venv/bin/python" -m uvicorn services.langgraph.app.main:app --host 127.0.0.1 --port "$PORT"
