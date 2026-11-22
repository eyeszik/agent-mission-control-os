# Computer-agent execution contracts (outcomes G and H)

The directive asks for controlled computer-task execution on **existing** AMCOS infrastructure, with no parallel platform. AMCOS already has two governed execution planes and a tool-call security layer. This cycle maps Steps A–I onto them and verifies them with their existing tests. **No new executor, gateway, store or approval path was added.**

## Steps A–I on existing code

| Step | Existing owner | Contract (real symbols) |
|---|---|---|
| A. TaskSpec | `agency/actions/gateway.py` `preview`/`propose` (capability id, project, environment, args, idempotency key); `agency/execution_fabric/contracts.py` `ExecutionContext` | `ExecutionContext.from_server` rejects client-injected authority and any mode except LOCAL/SANDBOX |
| B. Capability discovery | `agency/actions/catalog.py` (gateway-owned vs `NOT_GATEWAY_OWNED`); `agency/skills/dispatcher.py`; `agency/council/mcp_client.py` `configured_servers`/`pinned_paths` (pinned MCP servers) | Only catalogue entries are proposable; MCP servers are pinned by path |
| C. Plan DAG | `execution_fabric/schedule.py` `from_compiled_agency_plan`, `from_method_mission` | Waves recomputed at execution to prove freshness; colliding cells are split into sub-waves |
| D. Authorization | `actions/governance.py` (freeze, autonomy, `live_enablement()` always `DISABLED`); `actions/risk.py`; approvals decided only on `/approvals/{id}/decide`; `council/capability.py` scoped Ed25519 capability tokens with a JTI registry | Spend and governance roles are server-written; there is no LIVE switch |
| E. Dispatch | `actions/gateway.py` `dispatch` → sandbox adapters (`actions/adapters.py`); `execution_fabric/consumer.py` `execute_mission` → `dispatch_skill` | Sandbox only; consequential effects are never dispatched (NEEDS_HUMAN / `LIVE_GATED`) |
| F. Observe | gateway `_observation_receipt` (independent read-back); the fabric's storage read-back | Completion needs an independent read-back, never the adapter's own report |
| G. ActionReceipt | `agency/execution/models.py` `ExecutionReceipt`, `ObservationReceipt`, `DispatchPermit`; `actions/adapters.py` `DispatchReceipt`; hash-chained `action_transitions` | `persistence.actions.transition` is the only state writer (CAS on `version`) |
| H. Recover | gateway: a timeout becomes `UNKNOWN` → `RECONCILING` → `VERIFIED` / `FAILED` / `NEEDS_HUMAN`; fabric: a stale reservation is reconciled against the permit pre-image (retry / adopt / halt `RECONCILE_DIVERGENT`) | Outcome-unknown is never treated as success |
| I. Handoff | `open_artifact_approval` plus the existing Approvals view; NEEDS_HUMAN states | Approval never deploys, publishes, sends or spends |

The browser surfaces (Obscura isolated extraction; the `visual/browser.py` sandboxed Chromium) run with a network namespace and offline fixtures. Driving a live desktop or a live external website is **NOT_APPLICABLE** under the fail-closed rule: LIVE enablement is `DISABLED` and there is no adapter for external effects.

## Verification of the native path

Verdicts are taken from the full backend runs recorded in `COMPLETE_TEST_EVIDENCE.md`. A gate is claimed only where its tests ran and passed.

| Gate (directive A7–A9) | Evidence tests | Verdict |
|---|---|---|
| A7 governed dispatch (authorize → dispatch → receipt) | `test_ace12_actions.py`, `test_ace12_agency_os.py`, `test_execution_fabric.py`, `test_council_gateway.py` | see `COMPLETE_TEST_EVIDENCE.md` |
| A8 independent observation and receipts | `test_ace12_actions.py`, `test_execution_fabric.py`, `test_obscura_*.py` | see `COMPLETE_TEST_EVIDENCE.md` |
| A9 recovery and reconciliation | `test_ace12_actions.py` (UNKNOWN/reconcile), `test_execution_fabric.py` (stale reservation) | see `COMPLETE_TEST_EVIDENCE.md` |
| Live computer control (desktop or external web) | none: no adapter exists by design | NOT_APPLICABLE |
