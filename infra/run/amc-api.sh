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
# Optional mutual TLS (ASI07). Set all three AMC_MTLS_* variables, or none. Partial configuration fails closed.
tls_args=()
if [[ -n "${AMC_MTLS_CERT_FILE:-}${AMC_MTLS_KEY_FILE:-}${AMC_MTLS_CLIENT_CA_FILE:-}" ]]; then
  "$project_root/.venv/bin/python" -m services.langgraph.security.mtls >/dev/null || { echo "mTLS configuration refused" >&2; exit 1; }
  tls_args=(--ssl-certfile "$AMC_MTLS_CERT_FILE" --ssl-keyfile "$AMC_MTLS_KEY_FILE"
            --ssl-ca-certs "$AMC_MTLS_CLIENT_CA_FILE" --ssl-cert-reqs 2)
fi
exec "$project_root/.venv/bin/python" -m uvicorn services.langgraph.app.main:app --host 127.0.0.1 --port "$PORT" "${tls_args[@]}"
