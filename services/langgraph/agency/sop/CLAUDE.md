# agency/sop

## Ordered SOP contracts — a guard over the live graph, not an authority

`services/langgraph/agency/sop/` + `graph/agency/build.py` (every node wrapped by `guard_stage`) + `packages/shared/src/schemas/sop.ts` (`docs/acceptance-closure.md`):

- **One registry.** `data/sop_registry.v1.json` is the single source. Pydantic (`contracts.py`) and Zod (`sop.ts`) validate the same bytes; the TS fixture `packages/shared/tests/fixtures/sop-registry.json` is regenerated with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_sop_contracts.py`.
- **Order follows the topology.** Pipeline procedures must equal `agency/delivery/workflow.topology()` for every workflow version; add a stage there and here together. `sequence_index` is contiguous from 1, no step repeats, and a step may only require state an earlier step produced (`verify_repository_invariants.py` checks this statically).
- **References are proof, checked.** `enforced_by` and `tests` are `path::symbol`; `verify_against_code()` resolves every one, plus N3 owner roles, `LIVE_STAGE_ARTIFACTS` production rights and the RoleOS skill from `AGENCY_STAGE_BINDINGS`. Never cite a symbol or test that doesn't exist.
- **Guard semantics.** Missing entry state or a dropped declared output raises `SopContractViolation`; the run fails. The guard is behaviour, not topology, so `graph_fingerprint` is unchanged — never add or reorder nodes through it.
- **Failure disposition** is `FALLBACK_DEGRADED` or `BLOCKED`, never a pass. The registry grants no authority; approval and release stay on `/approvals/{id}/decide` and the N2 release guards.
- **Source approval (Batch 1b).** `source_approval.py` authenticates a Brand OS source only through the native route: the source bytes are a Project OS artifact (content hash = SHA-256 of the bytes), `open_source_approval` opens a `BRAND_OS_SOURCE` / `amc-brand-os-source/v1` approval via `open_artifact_approval`, and `verify_source_approval` reuses `artifact_release_verdict` plus a purpose and principal-scope check. It returns evidence (`grants_runtime_authority` is typed `False`), never a token, and never decides or releases anything.
