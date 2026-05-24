# Codex Phase Plan

## Best Operating Model

Use Codex through a GitHub repository, not pasted loose files. The repo gives Codex persistent project context, file paths, diffs, test scripts, and PR workflow.

## Phase 0 — Repository Audit Only

Give Codex:

- `README.md`
- `execution_blueprint.json`
- `approval_decision.json`
- `validation_report.json`
- `task_dag.json`
- `codex/codex_implementation_prompt.md`

Ask Codex to inspect the repo and produce an audit. Do not ask it to build yet.

## Phase 1 — Contract Skeleton

Give Codex:

- `contract_architecture.json`
- `execution_trace.schema.json`
- `streaming_resilience_spec.json`
- `fsm_spec.json`
- `constraint_ledger.yaml`

Ask Codex to create schemas/types/contracts first.

## Phase 2 — Backend Skeleton

Give Codex:

- `runtime_topology.yaml`
- `fsm_spec.json`
- `streaming_resilience_spec.json`
- `risk_register.json`

Ask Codex to scaffold backend routes, state, checkpointing, idempotency ledger, SSE, and mocks. It must not implement provider adapters without verified docs.

## Phase 3 — Frontend Skeleton

Give Codex:

- `system_layers.json`
- `contract_architecture.json`
- `streaming_resilience_spec.json`
- `governance_decisions.json`

Ask Codex to build typed clients, domain stores, Mission Control shell, and panels. Motion comes last.

## Phase 4 — Cloudflare Optional

Give Codex:

- `runtime_topology.yaml`
- `approval_decision.json`
- `risk_register.json`

Ask Codex to inspect existing Cloudflare config. If no config exists, it should create conditional scaffolds only and mark `[VOID_DETECTED]` bindings.

## Phase 5 — Test and Governance Hardening

Give Codex:

- `validation_report.json`
- `observability_hooks.yaml`
- `execution_flow.json`
- `risk_matrix.csv`
- `role_orchestration.json`

Ask Codex to add tests and a final preflight report.
