#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="${1:-agent-mission-control-os}"

git init
git add .
git commit -m "Add deterministic agent spec bundle"

if command -v gh >/dev/null 2>&1; then
  gh repo create "$REPO_NAME" --private --source=. --remote=origin --push
else
  echo "GitHub CLI not found. Create an empty GitHub repo, then run:"
  echo "git branch -M main"
  echo "git remote add origin <YOUR_REPO_URL>"
  echo "git push -u origin main"
fi
