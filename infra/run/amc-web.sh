#!/usr/bin/env bash
set -euo pipefail
project_root=/home/workspace/Projects/agent-mission-control-os
: "${PORT:=3200}"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://127.0.0.1:8000}"
export NEXT_PUBLIC_AUTH_MODE="${NEXT_PUBLIC_AUTH_MODE:-local}"
cd "$project_root/apps/web"
exec npx next start -p "$PORT" -H 127.0.0.1
