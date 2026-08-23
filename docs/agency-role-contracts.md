# N3 — Skill Orchestrator Role Contracts

Execution standards for specialized agent roles in the multi-department agency.

The machine-readable source of truth is
[`services/langgraph/agency/kernel/roles.py`](../services/langgraph/agency/kernel/roles.py).
This document explains the standards those contracts encode; it does not
restate the registry, because a hand-maintained copy would drift.

## What a role contract is

A **department** (N1) is accountable for an area. A **role** is the executable
unit the orchestrator dispatches inside that department. The contract binds a
role to four things it cannot exceed at runtime:

| Field | Meaning | Enforced by |
| --- | --- | --- |
| `capabilities` | What the role is permitted to do | `validate_registry()` — a role cannot claim a capability its department does not hold |
| `produces` | Artifact types it may emit | `assert_role_may_produce()` |
| `consumes` | Artifact types it needs as input | `validate_registry()` — every consumed type must be producible by some role |
| `min_evidence` | Evidence items backing its claims | `assert_evidence_sufficient()` |

## Authority is declared, not inferred

Two fields decide whether a role's output can leave the agency:

- **`requires_human_approval`** — the role's output cannot enter a
  client-visible lifecycle state without a resolved `approve` decision. Default
  is `True`. A role opts out only when its output is an *input to* the human
  gate rather than client-facing (currently only `brand_safety_reviewer`).
- **`external_side_effect`** — executing the role can publish or spend. These
  roles additionally require escrowed authorization; the lifecycle guard
  `_guard_spend_authorized` blocks the transition without it.

`validate_registry()` rejects any role that declares an external side effect
while waiving human approval. That combination is the shape of an autonomous
publish, which this system does not permit.

These fields are consumed by the N2 lifecycle guards. A role's prompt has no
authority to widen them — the prompt describes *how* the role works, the
contract decides *what it may do*.

## Execution standards

1. **Dispatch is contract-checked, not trust-based.** Before dispatch, the
   orchestrator verifies the role exists, its `consumes` inputs are present and
   not `invalidated`, and its evidence threshold is met. A role that cannot
   satisfy its inputs is not dispatched with partial context — it blocks.

2. **Every claim carries evidence or is marked unproven.** A role with
   `min_evidence > 0` is evidential: its assertions must reference
   `Evidence` records. Roles with `min_evidence == 0` are generative; their
   output is a proposal, and downstream consumers must not treat it as fact.

3. **Degraded generation never advances.** If the provider fell back
   (`FALLBACK_DEGRADED`), the run may complete, but the lifecycle guard blocks
   every client-visible transition regardless of role or approval. Degraded
   output is visible internally and inert externally.

4. **Ownership is exclusive.** Exactly one department owns each artifact type
   (N1 `ARTIFACT_TYPE_OWNER`). A role may consume another department's
   artifacts freely; it may never produce them. Cross-department revision goes
   through the N4 registry as a branch, not an in-place overwrite.

5. **Failure is explicit.** Roles report `BLOCK` (cannot proceed),
   `ESCALATE` (needs a human decision), or `RETRY` (transient). A role that
   silently returns a lower-confidence result instead of blocking violates its
   contract.

## Adding a role

1. Add the `RoleContract` to `ROLE_REGISTRY`.
2. If it introduces a new artifact type or capability, extend N1 first — the
   registry validator will reject a role referencing an unowned type.
3. Mirror any N1 change into `packages/shared/src/schemas/ontology.ts`;
   `scripts/verify_ontology_parity.py` fails CI on drift.
4. Run `pytest services/langgraph/tests/test_agency_ontology.py`, which calls
   `validate_registry()` and will surface ownership, capability, and
   reachability defects.
