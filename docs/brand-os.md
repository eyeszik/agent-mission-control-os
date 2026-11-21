# Brand OS 4.0 SOPs in Agent Mission Control

| Source | File |
|---|---|
| Index of F01-F60 | `services/langgraph/agency/sop/data/brand_os_index.v1.json` |
| F01-F08 drafts and README | `services/langgraph/agency/sop/data/brand_os/` |
| Step companion (advisory) | `services/langgraph/agency/sop/data/brand_os_companion.v1.json` |
| AGM mapping | `services/langgraph/agency/sop/data/brand_os_agm_mapping.v1.json` |
| Validation | `agency/sop/brand_os_source.py` |
| Approval | `agency/sop/source_approval.py` |
| API | `agency/sop/brand_os_service.py`, `api/routes/brand_os.py` (`/brand-os`) |
| Contracts | `agency/sop/brand_os_contracts.py`, Zod twin `packages/shared/src/schemas/brandOs.ts` |

## What exists

| Ids | Status | Meaning |
|---|---|---|
| F01-F08 | `NEWLY_AUTHORED_DRAFT` | Newly written v0.1 drafts, which the owner adopted on 2026-11-21 as the starting Brand OS 4.0 procedures. They are **not** recovered Brand OS 3.0 originals, and every file says so. |
| F09-F60 | `SOURCE_UNAVAILABLE` | Identity only (id, name, department). No procedure exists. F09-F12 are in Batch 1 but have no procedure body. |

The Brand OS 3.0 original procedures were never recovered. The searches covered the repository, its history, Google Drive and the documents supplied.

**Source integrity.** Each draft, and the pack README, is pinned by the SHA-256 of its bytes, and the ZIP archive digest is recorded. All nine files are byte-identical to the members of `F01-F08_reconstructed_drafts.zip`.

**Steps.** Steps are extracted only from each draft's `## Procedure` section, with their exact text and source line. Each step has a stable reference, `F0n.Sk`, always read together with the source digest. F04 has 7 steps and every other draft has 8, for **63 steps**. The drafts contain no numbered list outside a Procedure section.

## Step companion (advisory)

For every step, `brand_os_companion.v1.json` records:

- a suggested performer;
- inputs, observable output and evidence to retain;
- acceptance, review responsibility and what to do on failure;
- for each SOP, handoffs: the receiving SOP, the artifact it receives and the prerequisite.

**Native role binding.**

- **54 steps:** a native role, taken from the `bindings.py` role of the mapped AGM module. This is a module-level binding, not a per-step role contract.
- **9 steps:** an explicit `MISSING` binding, because no AGM task was mapped.
- The suggested performer is advice only; it binds no role.

**Who may approve.** Eligible approvers are the native approver roles (`reviewer`, `approver`, `admin`, `owner`). They decide only on `/approvals/{id}/decide`, and the decider can never be the requester.

**Cross-SOP dependencies.**

- **F03 and F06.** F06 opens an initial ledger from F01/F02 claims. F03 rates its themes provisionally against a named ledger version and appends new claims as UNVERIFIED rows, and F06 updates the ledger as evidence arrives. F03 acceptance re-checks the ratings against the ledger version current at decision time, so neither SOP waits for the other.
- **F07** receives F06's unresolved critical evidence and open risks alongside its F01-F05 inputs.
- **F08** receives the selected F07 territory, its proof plan, open risks and the F06 claim limitations.

**Scope.** The companion is advisory. It does not change the drafts' bytes or their mandatory behaviour, and an adoption approval does not cover it. Making any of it mandatory takes a new draft revision (a new file and a new digest) and its own independent adoption decision.

## AGM mapping

The mapping was made against catalog `9a2c30e9e65c2a3a6de70245cc47bbeeea2c695b965c09a143935d8ce3df501a` (`catalog.seed-v1.json`).

| SOP | PARTIAL_MATCH | UNRESOLVED |
|---|---|---|
| F01 | 6 | 2 (S5 distinctiveness test, S7 founder member-check) |
| F02 | 7 | 1 (S5 instrument pilot) |
| F03 | 7 | 1 (S5 ledger-based rating) |
| F04 | 7 | 0 |
| F05 | 7 | 1 (S8 validation-experiment design) |
| F06 | 5 | 3 (S1 claim atomization, S5 confidence scale, S7 ledger versioning) |
| F07 | 8 | 0 |
| F08 | 7 | 1 (S6 six-criterion editorial check) |
| **Total** | **54** | **9** (of 63) |

No step is EXACT or COMPOSITE. Catalog tasks carry a title, an output class and a module-level acceptance only. They define no inputs, evidence fields or failure recovery per task, so every material dimension can't be evidenced from the catalog. UNRESOLVED means no verified match was found; it is not a confirmed capability gap. Adding AGM extensions for these steps is a separate scope decision.

## Adopting a draft in a project

There is no SOP screen in the web app, so the request side is an API in the same style as the other project routes. The reviewer side uses the existing Approvals view, which now labels the two Brand OS purposes.

| Method and path | Who | Result |
|---|---|---|
| `GET /brand-os/sops` | any authenticated principal | The 60 ids with status, origin, digest and step count |
| `GET /brand-os/sops/{sop_id}` | any authenticated principal | The ordered steps with their AGM disposition. `original_authenticated` is always `false`. |
| `POST /brand-os/projects/{project_id}/sops/{sop_id}/adoption` | operator role with project access; needs an `Idempotency-Key` header | 202 with the persisted `AdoptionStatus` |
| `GET /brand-os/projects/{project_id}/sops/{sop_id}/adoption` | principal with project access | The persisted `AdoptionStatus` |
| `GET /approvals`, `POST /approvals/{id}/decide` | approver role; never the requester | The existing route; decides the adoption |

### Adoption states

| State | Meaning |
|---|---|
| `NOT_STAGED` | Nothing has been requested in this project. |
| `PENDING` | Waiting for a decision. |
| `ADOPTED` | The exact pinned bytes were approved in this tenant and project by someone other than the requester. |
| `REJECTED` | The adoption was turned down. A new request opens a new decision. |
| `STALE` | An approval exists but no longer verifies; `reasons` says why. |
| `REVISION_CHANGED` | The stored artifact isn't the currently pinned draft. |
| `STAGED_NO_APPROVAL` | The document was stored but the approval wasn't opened. Repeating the request opens it. |

Every status states what the decision covers. `grants_runtime_authority` is typed `false`, and `external_effects` is `none`.

### Retries

- The same `Idempotency-Key` replays the first response.
- A new request while the adoption is `PENDING` or `ADOPTED` opens nothing; it returns the current status.
- After a failure between storing the document and opening the approval, a repeat request reuses the unchanged artifact and opens exactly one approval.

**Residual race.** Two concurrent requests with different keys could both find no pending approval. `open_artifact_approval` doesn't lock, so this window is not closed.

### Reproduce locally (SQLite)

Use the local stack in `CLAUDE.md` with `AMC_AUTH_MODE=local`.

1. As user A with role `operator`, call `POST /brand-os/projects/<project>/sops/F01/adoption` with an `Idempotency-Key`. Expect 202 and `PENDING`.
2. As user B with role `reviewer`, read `GET /approvals` and call `POST /approvals/<approval_id>/decide` with `{"decision":"approve"}`.
3. As user A, call `GET .../adoption`. Expect `ADOPTED`.

`services/langgraph/tests/test_brand_os_api.py` runs this flow and its failure cases.

## Boundaries

None of the following has been done; each remains the owner's decision:

- adopting a real SOP in a real project, which needs an independent approver;
- merging the PR or marking it ready;
- applying the RLS migration in production, binding a production application role, wrapping production routes or switching on enforced mode.

Adoption never authorizes running a procedure, publishing, spending or messaging.
