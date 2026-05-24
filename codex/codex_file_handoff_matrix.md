# Codex File Handoff Matrix

| Codex Phase | Goal | Files to Reference | Instruction |
|---|---|---|---|
| Phase 0 | Audit repo only | README.md, execution_blueprint.json, approval_decision.json, validation_report.json, task_dag.json, codex/codex_implementation_prompt.md | Inspect repo. Report plan. Do not code. |
| Phase 1 | Contracts | contract_architecture.json, execution_trace.schema.json, streaming_resilience_spec.json, fsm_spec.json, constraint_ledger.yaml | Create schemas, types, OpenAPI/equivalent. |
| Phase 2 | Backend | runtime_topology.yaml, fsm_spec.json, streaming_resilience_spec.json, risk_register.json | Scaffold routes, graph state, checkpoints, idempotency, SSE. |
| Phase 3 | Frontend | system_layers.json, contract_architecture.json, streaming_resilience_spec.json, governance_decisions.json | Build typed clients, stores, Mission Control UI. |
| Phase 4 | Cloudflare | runtime_topology.yaml, approval_decision.json, risk_register.json | Implement only if bindings/config verified; otherwise scaffold VOID stubs. |
| Phase 5 | Tests | validation_report.json, observability_hooks.yaml, execution_flow.json, risk_matrix.csv, role_orchestration.json | Add tests and final preflight. |

## Best Practice

Do not paste all files into every Codex task. Put the files in the repository and tell Codex which files to read for the current phase. This reduces context overload and prevents Codex from treating planning artifacts as implementation code.
