# agency/frre

_Guidance for the Framework Reliability & Remediation Engine. Cross-cutting rules stay in the root file._

## What exists (W1 only): contracts, FSM, guards. Inert.

- **`fsm.py`.** Pure 25-state incident FSM (`amc-frre-fsm/v1`, 96 edges).
  - It is byte-for-byte the edge set model-checked in `docs/frre/FRRE-v15-spec.md`. `test_frre_w1.py` proves it against the preserved checker `tests/fixtures/frre/fsm_check_v15.py`.
  - Every cycle-closing edge is in `BUDGETED_EDGES`, and removing them leaves a DAG, so runs terminate.
  - Keep the recovery budget on `RECOVERY_REQUIRED -> ROLLED_BACK`. `ROLLED_BACK` has a single exit, so a budget there would strand an incident.
- **`contracts.py`.** Strict, frozen, `extra="forbid"` models for Incident, Diagnosis, RepairPlan, Permit, Candidate, Validation, Witness, Capability, Transition, Budget and Outcome. Validators refuse success that wasn't earned:
  - a `Validation` PASS with skips or unknowns, or without a baseline FAIL;
  - an `Outcome` RESOLVED without a PASS verdict;
  - a `Capability` enabled without promotion;
  - a `Diagnosis` that selects an unreproduced cause;
  - plans or candidates that touch the protected floor.
- **`guards.py`.** `decide(transition, facts)` is the single decision point a future tick must call.
  - Facts are fail closed by absence: unknown halt, unchecked permit, missing verdict or unobserved recovery all mean REFUSE.
  - `permit_refusals` checks stage, tenant, project, replay, revocation, expiry, baseline, policy, plan and candidate drift.
- **`policy.py`.** Literal constants: no auto merge, promotion or self-approval; delivery disabled; nothing enabled; the protected floor.

## Rules

- **Nothing may call into this package** from routes, workers, schedulers or integrations until W2 is authorized. `test_frre_w1.py::test_w1_is_inert` fails if one does.
- **`policy.py` and `guards.py` are on the protected floor.** No repair plan may list them. Changing them is a protected-control change that needs independent review.
- **Zod twins** arrive in W2, with the first API-visible model or persisted row.
- **Waves W2–W9 are specification only:** `docs/frre/FRRE-v15-spec.md` section 9 and `docs/frre/PROVENANCE.md`.
- **Reuse, don't duplicate.** Approvals go only through `open_artifact_approval` and `/approvals/{id}/decide`. Capsules live in `foundry.studio.store`. Isolation comes from `execution_fabric/adapters/code_sandbox.py`, which needs independent review before it may run tests (SEC-P1). The kill switch is `security/distributed.check_any_halt`, which is dormant until SEC-P3.
