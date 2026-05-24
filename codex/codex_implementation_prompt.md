# Codex Implementation Prompt

You are Codex acting as a principal full-stack AI systems architect, LangGraph engineer, Cloudflare Workers/Agents/Durable Objects developer, Next.js product engineer, security reviewer, accessibility auditor, and production implementation agent.

## Mission

Inspect this repository and convert the attached architecture/specification bundle into a production-ready implementation plan, then implement only after completing the repo audit and receiving explicit implementation approval in the task.

## Critical Rule

Do not start by writing components. Start by reading the repository and the files in this bundle.

## Required Read Order

1. `README.md`
2. `execution_blueprint.json`
3. `approval_decision.json`
4. `validation_report.json`
5. `task_dag.json`
6. `contract_architecture.json`
7. `fsm_spec.json`
8. `runtime_topology.yaml`
9. `governance_decisions.json`
10. `risk_register.json`
11. `codex/codex_phase_plan.md`
12. `codex/codex_file_handoff_matrix.md`

## Phase 0 — Repo Audit

Inspect the repo and report:

- package manager
- lockfiles
- framework versions
- existing app structure
- existing backend structure
- test scripts
- lint/typecheck scripts
- deployment config
- env patterns
- existing Cloudflare config
- existing Next.js config
- existing Python/FastAPI/LangGraph config
- implementation conflicts with the spec

Do not implement until this audit is complete.

## Phase 1 — Contracts First

Implement or generate:

- OpenAPI or equivalent contract source of truth
- shared schemas for AgentRunState, RunEvent, ToolDescriptor, ArtifactBundle, GovernanceDecision
- Pydantic/backend schemas if backend exists or is scaffolded
- Zod/TypeScript schemas if frontend exists or is scaffolded
- typed API client boundaries
- no bare fetch in React components

## Phase 2 — Backend / Orchestration

If backend implementation is approved and compatible:

- scaffold or patch Python/FastAPI service
- implement LangGraph StateGraph only after checking installed version/docs
- add checkpoint persistence
- add idempotency ledger
- add run/event/approval/artifact/export routes
- add safe error handling
- add PII redaction boundary
- add local quality evaluator
- keep provider adapters as [VOID_DETECTED] until verified

## Phase 3 — Frontend / Mission Control

If frontend implementation is approved and compatible:

- implement Next.js Mission Control route
- implement typed clients
- implement domain-sharded Zustand stores
- implement SSE/reconnect/resume logic
- implement panels: CommandInputPanel, WorkflowMapPanel, LiveStepProgressPanel, IntelligentResultsList, ApprovalInbox, QualityScorePanel, FileOrganizationPanel, ArtifactPreviewPanel, ExportDrawer, AuditLogPanel, RefinerQueuePanel, CapsuleLibraryPanel
- implement loading/empty/error/success states for every data surface
- apply WCAG AA and reduced-motion support
- add Motion layout/layoutId reordering only after data layer is stable

## Phase 4 — Cloudflare Edge Layer

If Cloudflare config exists or user explicitly requests it:

- inspect wrangler config and bindings
- scaffold or implement Worker routes
- shard Durable Objects by tenant/project/run hash
- avoid a global singleton DO
- keep canonical state in durable DB/checkpointer
- store artifacts outside DO memory
- use Workflows/Queues only when bindings are verified

If bindings are missing, mark [VOID_DETECTED: Cloudflare bindings not verified] and keep local backend runnable.

## Phase 5 — Tests and Validation

Add or scaffold:

- unit tests for idempotency, reducers, schemas, PII redaction, approval gates, status mapping, list sorting, quality thresholds
- integration tests for create run, stream events, checkpoint resume, approvals, artifacts, exports, parallel runs
- E2E tests for submit, progress, approval, resume, final artifact, export
- axe accessibility tests
- security/governance tests

## Output Format

Return:

1. Repo audit
2. Implementation plan
3. Files changed
4. Commands run
5. Tests run
6. [VOID_DETECTED] items
7. Remaining risks
8. Safe next steps

## Stop Conditions

Stop and ask for review if:

- repo structure conflicts with the spec
- package versions are incompatible
- secrets are needed
- external writes are required
- production deployment is requested
- Cloudflare bindings are missing
- provider API docs are missing
- SEC/governance risk cannot be reduced
