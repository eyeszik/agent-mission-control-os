# GitHub Setup Guide

## Option A — GitHub CLI

```bash
cd agent_spec_bundle
git init
git add .
git commit -m "Add deterministic agent spec bundle"
gh repo create agent-mission-control-os --private --source=. --remote=origin --push
```

## Option B — GitHub Web UI

1. Create a new empty repository on GitHub.
2. Copy the repository URL.
3. Run:

```bash
cd agent_spec_bundle
git init
git add .
git commit -m "Add deterministic agent spec bundle"
git branch -M main
git remote add origin <YOUR_REPO_URL>
git push -u origin main
```

## After Push

1. Open Codex.
2. Connect/select this GitHub repository.
3. Create a Codex environment for the repo.
4. Start with Phase 0 audit only.
