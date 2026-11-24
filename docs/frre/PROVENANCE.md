# FRRE specification: provenance and revision record

`FRRE-v15-spec.md` is preserved **byte-for-byte** as written in the session that produced it. It is the
original specification and is not edited. Everything that has changed since is recorded below, not patched
into the original.

## Preservation record

| Artifact | Source (session scratchpad, ephemeral) | Destination | sha256 (original = copy) | Status |
|---|---|---|---|---|
| Specification | `scratchpad/frre/FRRE-v15-spec.md` | `docs/frre/FRRE-v15-spec.md` | `11ec3dcf885864e9beaa58431afca8e57d9bceb2bcc20976270dde16b1b105f0` | PRESERVED (byte-identical) |
| FSM model checker | `scratchpad/frre/fsm_check.py` | `services/langgraph/tests/fixtures/frre/fsm_check_v15.py` | `a905b8b950331fc53c4f90e0ef33f45180f87023b03823050c9324b0275756d8` | PRESERVED (byte-identical) |

Further provenance:
- **Redaction:** none needed. A scan for credentials and personal data found only design vocabulary ("fencing token", "design tokens").
- **Authority:** the repository owner granted local W0.5 preservation and W1 implementation; push and PR were not granted.
- **Integrity check:** `test_frre_w1.py::test_preserved_checker_is_byte_identical_to_the_original` fails if the preserved checker's hash ever changes. The checker sits under `tests/fixtures/`, which is in the FRRE protected floor, so a repair actor can never edit it (counterexample escrow).

## What changed after v15 was written (recorded, not edited into v15)

| v15 statement | Current fact | Status |
|---|---|---|
| Baseline `master = c1e4d0a` | `master = 977158d2750b5083bc99c82c8ff24cdf40e38f45` (#304 merged after #303) | Superseded |
| Master CI on `c1e4d0a` "in progress" | Run 45489613981 finished with 5 jobs successful and 4 **cancelled** (superseded by the #304 push): Backend, Backend on PostgreSQL, Browser E2E, and UCPO's AVIC step. Cancelled is neither PASS nor FAIL, so `c1e4d0a` has no complete CI verdict. | Resolved: no verdict |
| Ruleset 20371074 | Unchanged (`updated_at 2026-11-18`): 0 required approvals, `required_status_checks: []`, no bypass actors | Re-verified |
| §4 FSM: 25 states, 96 edges | Implemented as `services/langgraph/agency/frre/fsm.py` with the identical edge set, proven by a differential test against the preserved checker | Implemented (W1) |
| §4 caveat: rollback cycle needs a budget | Implemented. Every cycle-closing edge is budgeted, and removing the budgeted edges leaves a DAG, so every run terminates (see `fsm.py`). | Implemented (W1) |
| §9 W1 "Zod twin" for every contract | Deferred. W1 contracts are not API-visible (no route, no persisted row), and CLAUDE.md requires a Zod twin only for API-visible models. It becomes required in W2, when the first route or row exists. | Revised (justified) |

## Scope boundary

W1 is **inert**. It adds pure contracts, a pure FSM and pure guard functions. It adds no route, worker, table,
migration, scheduled trigger, network call or enabled effect path, and the tests prove this within the
inspected boundaries. W2–W9 remain specification only until separately authorized.
