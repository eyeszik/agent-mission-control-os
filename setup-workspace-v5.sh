#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-.}"
TARGET_DIR="$(cd "${TARGET_DIR}" && pwd)"

if [ -f "${TARGET_DIR}/check_env.py" ]; then
    python3 "${TARGET_DIR}/check_env.py" || true
fi

echo "[INFO] Executing Level 100 Workspace Setup v5 at: ${TARGET_DIR}"

mkdir -p "${TARGET_DIR}/.agents/skills"
mkdir -p "${TARGET_DIR}/.claude/skills"
mkdir -p "${TARGET_DIR}/.cursor"
mkdir -p "${TARGET_DIR}/.windsurf"
mkdir -p "${TARGET_DIR}/.github"
mkdir -p "${TARGET_DIR}/.husky"

HOOK_PATH="${TARGET_DIR}/.husky/pre-commit"
if [ -f "${HOOK_PATH}" ]; then
    if ! grep -q "compile_tokens.py" "${HOOK_PATH}"; then
        echo "" >> "${HOOK_PATH}"
        echo "# Auto-compile design tokens on commit" >> "${HOOK_PATH}"
        echo "if [ -f \"compile_tokens.py\" ]; then" >> "${HOOK_PATH}"
        echo "  npm run tokens:build 2>/dev/null || python3 compile_tokens.py" >> "${HOOK_PATH}"
        echo "  git add _tokens.css 2>/dev/null || true" >> "${HOOK_PATH}"
        echo "fi" >> "${HOOK_PATH}"
    fi
else
    cat << 'EOF' > "${HOOK_PATH}"
#!/usr/bin/env sh
. "$(dirname "$0")/_/husky.sh"

if [ "${CI:-false}" = "true" ]; then exit 0; fi

if [ -f "compile_tokens.py" ]; then
  npm run tokens:build 2>/dev/null || python3 compile_tokens.py
  git add _tokens.css 2>/dev/null || true
fi

npx lint-staged
EOF
fi

chmod +x "${HOOK_PATH}"
echo "[SUCCESS] Configured .husky/pre-commit with token compiler automation."
