#!/usr/bin/env bash
# This job starts native processes, whose logs are redirected by Start local stack.
set -euo pipefail

redact() {
  sed -E \
    -e '/-----BEGIN .*PRIVATE KEY-----/,/-----END .*PRIVATE KEY-----/c\[REDACTED PRIVATE KEY]' \
    -e 's/("?[[:alnum:]_]*(TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY)"?[[:space:]]*[:=][[:space:]]*)("[^"]*"|[^[:space:],;]+)/\1[REDACTED]/gI' \
    -e 's/((Bearer|Basic)[[:space:]]+)[[:alnum:]_.+\/=-]+/\1[REDACTED]/gI' \
    -e 's/(gh[pousr]_|github_pat_)[[:alnum:]_]+/[REDACTED]/g' \
    -e 's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1[REDACTED]@#g'
}

mkdir -p ci-diagnostics
{
  printf '===== runner: %s/%s =====\n' "${RUNNER_OS:-unknown}" "${RUNNER_ARCH:-unknown}"
  uname -a || true
  df -h . /tmp || true
  if command -v docker >/dev/null 2>&1; then
    # No job.services containers are configured; these processes log to files.
    timeout 10s docker ps -a --format '{{.Names}} {{.Status}}' || true
  fi

  for service in backend frontend; do
    printf '\n===== %s (last 500 redacted lines) =====\n' "$service"
    log="/tmp/amc-${service}.log"
    if [[ -r "$log" ]]; then
      # Redact before tailing so a private key crossing the tail boundary is removed.
      redact < "$log" | tail -n 500 || true
    else
      printf 'Log unavailable: %s\n' "$log"
    fi
  done

  for url in http://127.0.0.1:8000/health http://127.0.0.1:3000/mission-control; do
    printf '\n===== health: %s =====\n' "$url"
    curl --connect-timeout 2 --max-time 5 -sS -o /dev/null -w 'HTTP %{http_code}\n' "$url" || true
  done

  printf '\n===== Playwright artifact sizes =====\n'
  for dir in apps/web/playwright-report apps/web/test-results apps/web/traces apps/web/.playwright/artifacts; do
    [[ ! -d "$dir" ]] || du -sh "$dir" || true
  done
} 2>&1 | redact | tee ci-diagnostics/browser-e2e.log
