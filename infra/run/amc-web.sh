#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${PORT:=3200}"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://127.0.0.1:8000}"
export NEXT_PUBLIC_AUTH_MODE="${NEXT_PUBLIC_AUTH_MODE:-local}"
cd "$project_root/apps/web"
if [[ ! -x node_modules/.bin/next ]]; then echo "Install locked web dependencies first" >&2; exit 1; fi
exec node scripts/start.mjs -p "$PORT" -H 127.0.0.1
