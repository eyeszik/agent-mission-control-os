# Step-by-Step GitHub + Codex Guide

## Goal

Put this artifact bundle into a GitHub repository, connect that repo to Codex, and have Codex build the actual system in controlled phases.

## Recommended Path

Use a GitHub repo as the source of truth. Do not rely on pasting all files into Codex chat. Codex works best when it can inspect the repository, understand file paths, make diffs, run setup/test commands, and produce PRs.

## Step 1 — Unzip the Bundle

1. Download `agent_spec_bundle.zip`.
2. Unzip it locally.
3. Open the extracted folder.
4. Confirm you see:
   - `README.md`
   - `execution_blueprint.json`
   - `task_dag.json`
   - `contract_architecture.json`
   - `runtime_topology.yaml`
   - `codex/codex_implementation_prompt.md`
   - `codex/codex_phase_plan.md`
   - `github/github_setup_guide.md`

## Step 2 — Create a GitHub Repository

Preferred command-line path:

```bash
cd agent_spec_bundle
git init
git add .
git commit -m "Add deterministic agent spec bundle"
```

Then create a repo with GitHub CLI:

```bash
gh repo create agent-mission-control-os --private --source=. --remote=origin --push
```

If you do not use GitHub CLI:

1. Create a new empty repo on GitHub.
2. Copy the repo HTTPS URL.
3. Run:

```bash
git remote add origin <YOUR_REPO_URL>
git branch -M main
git push -u origin main
```

## Step 3 — Connect GitHub Repo to Codex

1. Open Codex.
2. Connect GitHub if not already connected.
3. Create/select a Codex environment for this repository.
4. Let Codex use the repo branch you pushed.
5. Do not start with a build request. Start with an audit request.

## Step 4 — Codex Task 1: Audit Only

Paste this into Codex:

```text
Read these files first:
- README.md
- execution_blueprint.json
- approval_decision.json
- validation_report.json
- task_dag.json
- codex/codex_implementation_prompt.md

Task: Perform Phase 0 repo audit only. Inspect the repository structure, package manager, scripts, framework versions, backend/frontend layout, test setup, env patterns, Cloudflare config, and conflicts with the spec. Do not write implementation code yet. Return an audit, implementation plan, risks, and the first safe patch proposal.
```

## Step 5 — Review Codex Audit

Check whether Codex correctly identifies:

- no existing app vs existing app
- package manager
- frontend framework
- backend structure
- scripts
- missing dependencies
- Cloudflare config status
- exact paths it plans to change

Do not approve implementation if Codex skipped the audit or guessed versions.

## Step 6 — Codex Task 2: Contracts First

Paste:

```text
Use these files:
- contract_architecture.json
- execution_trace.schema.json
- streaming_resilience_spec.json
- fsm_spec.json
- constraint_ledger.yaml

Task: Implement the contract/schema layer first. Create or patch OpenAPI/equivalent contracts, shared TypeScript/Zod schemas, backend schema models where applicable, and typed client boundaries. Do not build UI components yet. Add tests for schema validation and drift detection where feasible.
```

## Step 7 — Codex Task 3: Backend Skeleton

Paste:

```text
Use these files:
- runtime_topology.yaml
- fsm_spec.json
- streaming_resilience_spec.json
- risk_register.json
- governance_decisions.json

Task: Implement backend skeleton for runs, events, approvals, artifacts, exports, checkpointing, idempotency ledger, and safe errors. If LangGraph is available, scaffold StateGraph with checkpointer. If unavailable, create typed stubs and [VOID_DETECTED] notes. Do not implement unverified provider adapters.
```

## Step 8 — Codex Task 4: Frontend Skeleton

Paste:

```text
Use these files:
- system_layers.json
- contract_architecture.json
- streaming_resilience_spec.json
- governance_decisions.json
- codex/codex_file_handoff_matrix.md

Task: Build the Next.js Mission Control frontend shell. Add typed API clients, domain-sharded stores, SSE/reconnect logic, and panels listed in the spec. Build static shell, skeletons, data-bound surfaces, interactions, then motion last. No bare fetch in components.
```

## Step 9 — Codex Task 5: Cloudflare Optional

Only do this if your repo actually targets Cloudflare.

Paste:

```text
Use these files:
- runtime_topology.yaml
- approval_decision.json
- risk_register.json

Task: Inspect Cloudflare config/bindings. If verified, scaffold Workers/Durable Objects/Workflows according to the runtime topology. Shard Durable Objects by tenant/project/run hash. Do not use a global singleton. If bindings are missing, create typed stubs and [VOID_DETECTED] notes only.
```

## Step 10 — Codex Task 6: Tests + Preflight

Paste:

```text
Use these files:
- validation_report.json
- observability_hooks.yaml
- execution_flow.json
- risk_matrix.csv
- role_orchestration.json

Task: Add unit, integration, E2E, accessibility, and security/governance tests where feasible. Run lint/typecheck/tests. Return final preflight, commands run, failures, [VOID_DETECTED] items, and safe next steps.
```

## Step 11 — Use Pull Requests

Best practice:

1. Ask Codex to work on a branch.
2. Review diffs.
3. Ask Codex to open a PR if available in your Codex workflow.
4. Use Codex code review or manual review before merge.
5. Merge only after tests pass.

## What Files Should You Upload or Paste?

Best option: do not paste large files. Commit the ZIP contents to GitHub and tell Codex which files to read.

If you must upload/paste manually, use the matrix:

- Audit: README, execution_blueprint, approval_decision, validation_report, task_dag, codex prompt.
- Contracts: contract_architecture, execution_trace schema, streaming_resilience, fsm_spec, constraint_ledger.
- Backend: runtime_topology, fsm_spec, streaming_resilience, risk_register, governance_decisions.
- Frontend: system_layers, contract_architecture, streaming_resilience, governance_decisions.
- Cloudflare: runtime_topology, approval_decision, risk_register.
- Tests: validation_report, observability_hooks, execution_flow, risk_matrix, role_orchestration.

## Red Flags

Stop Codex if it:

- writes UI before auditing repo/contracts
- invents provider endpoints
- claims Cloudflare bindings exist without config
- asks for secrets in chat
- hardcodes package versions without checking repo
- uses a global Zustand god-store
- creates one global Durable Object for every run
- calls raw fetch inside React components
- ignores PII redaction or approval gates
- claims production readiness without tests and deployment verification
