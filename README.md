# Deterministic Agent Operating Spec Compiler

## Purpose

This repo artifact bundle compiles a high-complexity prompt into an agent-runnable operating specification for deterministic AI orchestration.

It preserves the LangGraph + Cloudflare + Next.js Mission Control OS intent while converting vague, aspirational, duplicated, or unverified claims into explicit requirements, assumptions, constraints, DAGs, contracts, state-machine rules, streaming resilience rules, runtime topology, governance decisions, risks, role handoffs, validation criteria, observability hooks, and approval routing.

## Current Status

- Status: `architecture_bundle_complete_requires_review`
- Routing: `ESCALATE`
- Production release: **not approved**
- Implementation code: **not included**

## Why It Escalates

Human review is required because no repository was provided, package versions and commands are unverified, Cloudflare bindings are unverified, external tool/provider contracts are unverified, SEC dissent blocks production deployment and unverified tool execution, and runtime schema validation was not executed.

## Start Here

1. Read `STEP_BY_STEP_GITHUB_CODEX_GUIDE.md`.
2. Push this bundle to a GitHub repository.
3. Connect the repository to Codex.
4. Run Codex Phase 0 with `codex/codex_phase_plan.md` and `codex/codex_implementation_prompt.md`.
5. Let Codex inspect the repo before asking it to build anything.

## Key Files

- `execution_blueprint.json`: top-level architecture summary.
- `task_dag.json`: deterministic task sequence and dependencies.
- `contract_architecture.json`: contract/source-of-truth plan.
- `fsm_spec.json`: state machine and transition rules.
- `runtime_topology.yaml`: backend/frontend/edge topology.
- `governance_decisions.json`: LEG/ETH/SEC/RG results.
- `approval_decision.json`: final approval routing.
- `codex/codex_implementation_prompt.md`: prompt to give Codex.
- `codex/codex_file_handoff_matrix.md`: which files to give Codex at each phase.
- `github/github_setup_guide.md`: GitHub setup instructions.

## Non-Goals

This bundle does not deploy, mutate infrastructure, request secrets, expose credentials, or perform irreversible actions. It does not claim production readiness.
