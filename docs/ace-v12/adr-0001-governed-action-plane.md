# ADR-0001: A governed action plane over the existing owners

Status: accepted for implementation on `claude/ai-agency-pipeline-oae65z` (draft PR, not merged).
Base: `master` 5d2433bd, merged into the branch as 28bab930. PR #135 (`docs/external-action-risk-policy.md`,
open, docs only) is treated as a **proposal**. Its R0–R6 vocabulary is adopted. Its state machine is replaced
by the one below, which the ACE v12 brief specifies.

## Context

The repository already has every authority primitive an external action needs. What it lacks is a single
place that combines them for an action that leaves the process:

| Concern | Existing owner (reused, not duplicated) |
|---|---|
| Identity, tenant, project scope | `security.auth.Principal`, `authorize_resource`, `persistence.tenancy.ensure_tenant_project` |
| Human approval, approver role, separation of duties | `persistence.approvals` + `POST /approvals/{id}/decide` + `security.approval_authority` |
| Approval anchor | a `runs` row with `needs_approval` and `initiated_by` (same pattern as `agency.intake.release.open_artifact_approval`) |
| Policy decisions, recovery cases, audit chain | the trust kernel (`agency.reliability.service`, `persistence.trust_kernel`) |
| Execution and observation receipts | `persistence.proofs` (`ExecutionReceipt`, `ObservationReceipt`) |
| Hashing | AMC-CANON-1 `agency.execution.canonical.canonical_hash` |
| Injection scan, redaction | `agency.compiled.role_sources.scan_for_injection`, `security.pii.redact_value` |
| Local work (R1) | `agency.execution_fabric` (missions) and the VNEXUS media fabric. Both keep their own dispatch. |
| Brief → project → verified artifact → approval → release verdict | `agency.intake` (`run_mission`, `release_gate`) |
| Publication / paid media | `integrations.publication` (dry run only), `integrations.paid_media` (requests only) |

Verified facts this design depends on:

- **LangGraph replays interrupted nodes.** The installed langgraph is 1.2.11. The `langgraph.types.interrupt`
  docstring says: "The graph resumes from the start of the node, **re-executing** all logic." The gateway is
  therefore never called from inside a graph node. A test enforces this.
- **No EXT-/ART- action IDs exist** anywhere in the repository. Inventing their descriptions is not allowed, so
  `EXT-001…090` and `ART-001…012` are registered as reserved namespaces with status `VOID_DETECTED`, and looking
  one up returns `NOT_IMPLEMENTED`.
- **External references could not be fetched.** The OWASP, NIST, OpenTelemetry and LangChain web pages were
  blocked by this environment's network policy (proxy 403). Statements here rely on repository code and
  installed package source only.

## Decision

Add `services/langgraph/agency/actions/` as the **only entry point for actions with an effect outside the
process** (R2–R6), and as the descriptive catalogue for everything else. The responsibilities in the brief map
onto modules, not services.

| Responsibility | Module | Reuses |
|---|---|---|
| ActionRegistry | `catalog.py` | Fabric skill metadata, VNEXUS provider registry, integration modes |
| RiskEngine | `risk.py` (pure) | — |
| AuthorizationBroker | `broker.py` | Principal, tenancy registry, approvals table, approval authority |
| ExecutionGateway | `gateway.py` | Trust-kernel policy decisions, proofs receipts, runs |
| EvidenceLedger | `evidence.py` + `action_transitions` hash chain | Trust-kernel audit chain, proofs |
| RecoveryCoordinator | `recovery.py` | Trust-kernel recovery cases |
| ClientActionConsole | `/agency` UI + `api/routes/actions.py`, `api/routes/agency_os.py` | Existing approval inbox route |

### Persistence: migration 16

These tables are additive; no existing table changes.

| Table | Holds |
|---|---|
| `action_requests` | The ActionRequest, its state, version (CAS), lease and binding |
| `action_transitions` | Append-only, hash-chained per action |
| `action_budget_policies` | Ceilings |
| `action_budget_reservations` | Reservations |
| `action_freezes` | Incident freezes |
| `action_project_settings` | The autonomy dial |
| `action_sandbox_effects` | The **fake** provider's remote state, used for read-back |
| `agency_clients` | Clients |
| `agency_client_projects` | Links between clients and projects |

Rejected alternatives:

- **Reuse `durable_jobs`.** Its FSM schedules recurring ticks; an action is a one-shot governed effect with
  approval and budget states. Mixing them would make one FSM serve two meanings.
- **Reuse `publication_jobs` / `spend_authorizations`.** They are per-integration and carry no binding, budget
  window or reconciliation. They stay as they are and are described in the catalogue.
- **A second approvals store.** Rejected. Approvals are rows in `approvals` with
  `subject_hash = binding_hash` and decisions go through the existing route.

### Exact approval binding

`binding_hash = canonical_hash({payload_hash, target_ref, tenant_id, project_id, environment, policy_version,
dependency_hashes, expires_at, capability_ref, args_hash})`. Approval is satisfied only by a resolved
`approve` whose `subject_hash` equals the **current** binding hash. Any change in payload, target, environment,
policy, dependency or expiry produces a different hash, so the old approval cannot apply (I05/I06). An
approval decided after `expires_at` is rejected (EXPIRED).

### LIVE gate

`Environment.LIVE` is refused by the request model and by the gateway (I20). It stays refused even if an
adapter declares live support and an environment variable is set: `live_enablement()` returns `DISABLED` with
its reasons, and no code path in this change can return `ENABLED`. R3–R6 descriptors are `LIVE_GATED`.
Sandbox fakes exercise the full control path against a table that only they read and write. Their outputs are
labelled `SIMULATED` and are never claimable as delivered.

## Consequences

- Every R2–R6 effect is persisted *before* dispatch (`DISPATCHING` with a lease) and *after* observation.
- A dispatch timeout becomes `UNKNOWN`. It can only leave that state through `RECONCILING`, which uses a
  read-back by idempotency key (I09).
- Delivery is at-least-once. The adapter's idempotency key dedupes at the fake provider; exactly-once is not
  claimed.
- Step-up authentication does not exist in this repository. R5 actions therefore block with
  `STEP_UP_UNAVAILABLE`, even in the sandbox; nothing is simulated.
