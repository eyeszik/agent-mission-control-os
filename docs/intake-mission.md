# Governed intake mission

`services/langgraph/agency/intake/` connects a user's request to a release decision through existing primitives:

```
request -> CompiledIntent -> ProjectResolutionReceipt -> ContextCapsule + MemoryUseReceipt
        -> MissionContract -> execution fabric (LOCAL) -> ArtifactVerification
        -> approval (approvals table, /approvals/{id}/decide) -> ReleaseVerdict
```

The slice adds typed receipts, an independent verifier and a fail-closed release gate. It adds no new orchestrator, registry, approval engine, event type, table or migration.

## What each step reuses

| Step | Module | Reuses |
|---|---|---|
| Intent | `intent.compile_intent` | Nothing. Deterministic regex extraction with source spans; no model call. |
| Project | `resolver.resolve_project` | `security.auth.Principal`, `persistence.projects.list_project_workspaces` |
| Memory and context | `context.compile_context` | `project_os.memory.resolve` (unchanged), `persistence.project_knowledge.list_memory` |
| Planning | `runner._plan` | Compiled agency planner, with real project artifact heads and optional scoped `PlanningInputs` supplied by trusted server code |
| Execution | `runner.run_mission` | `execution_fabric.execute_mission` (LOCAL mode): permits, idempotency, Project OS persistence, storage read-back |
| Verification | `runner.verify_artifact` | `execution_fabric.verifiers.svg_safety`, `palette_conformance`, `StorageAdapter.get_bytes` |
| Approval | `runner.request_release_approval` | `persistence.approvals`, `persistence.runs`; decided through the existing `/approvals/{id}/decide` route |
| Events | `runner._event` | `persistence.projects.append_project_event` with existing `ActivityType` values |

## Rules the slice enforces

- **Authority is server-side.** The principal comes from `security.auth`. "Approve" in a message is recorded as an `APPROVAL_CANDIDATE` and `FORBIDDEN_TO_INFER`; it never approves anything.
- **Projects are resolved in a fixed order.** Hard filters (tenant, access, archived) run before matching. A filtered-out project is counted, never named. An unknown id and an inaccessible id give the same `EXPLICIT_PROJECT_NOT_AVAILABLE` reason, so a receipt can't confirm that another project exists. The order is explicit id, then name/slug/brand match, then the active project. A tie, or a named project that differs from the active one, returns `AMBIGUOUS`, and the mission stops before writing anything.
- **Memory keeps its existing authority order.** `resolve()` is called unchanged. On top of it the capsule:
  - drops conversation memory (M3) from other threads;
  - drops quarantined learning (M6);
  - applies an authority floor; brand facts need `APPROVED_PROJECT_DECISION` or higher;
  - withholds a subject when two records have the same authority but different content;
  - reports `UNRESOLVED_STALE` when every record is stale;
  - enforces a byte budget.

  Excluded records are listed with a reason.
- **The capsule hash is deterministic.** It covers the selected memory and a project fingerprint of the artifact heads the mission consumes. The mission's own output type is excluded, so a replay keeps the same identity.
- **Real execution is the default.** `SIMULATION` is a server-side argument, never inferred from wording. A simulated mission:
  - dispatches nothing;
  - is recorded with `simulation: true` on its `WORK_STARTED` event;
  - cannot request an approval;
  - cannot pass the release gate, even with a real verification and approval grafted onto it.
- **Missing providers stay blocked.** An image or video request runs the fabric's real `t2i_image_generate` / `ai_video_generate` binding. That binding reports `PROVIDER_GAP`, and no placeholder artifact is written. Missing upstream inputs (no `brand_core`, `brand_platform` or `positioning_statement` in the project) plan as blocked work; the fabric's own state precedence applies, so a cell held behind a human-only upstream is `NEEDS_HUMAN`.
- **Verification is independent.** The verifier re-reads the persisted bytes from storage, not the skill's output. It checks:
  - the stored bytes' SHA-256 against the recorded `content_hash`;
  - the head version against the produced version;
  - that the root is `<svg>` with a `viewBox`;
  - `svg_safety`;
  - palette conformance against the brand capsule.

  For a `design_token_set`, it also recompiles the persisted DTCG document,
  checks the resulting CSS and source hash, and compares the document's palette,
  fonts and semantic aliases to the approved brand capsule. Without that capsule
  it returns `INCONCLUSIVE`. These checks do not constitute a complete WCAG audit.

  A media type with no verifier yet returns `INCONCLUSIVE`, never `PASSED`.
- **Approval binds the exact bytes.** The approval's `subject_hash` is the verified content hash. Requesting approval for changed content marks older pending approvals for that artifact stale. The approval sits on a run record with `status=needs_approval` and `initiated_by=<requester>`, so the existing decide route enforces the approver role and separation of duties.
- **The release gate fails closed.** It allows release only if all of these hold:
  - the mission is real, not simulated;
  - verification `PASSED`;
  - the artifact head still matches the verified version and hash;
  - the approval is resolved as `approve`, in scope, and not stale;
  - the subject hash matches;
  - the reviewer is not the initiator (unless the local self-approval switch is on).

  The gate never performs a release or any external effect.
- **External effects are never dispatched.** Publish, spend and send each produce a `NonActionReceipt` and a `NEEDS_HUMAN` predicate. The receipt records the project's publication-attempt and scheduled-job counts before and after, and states that it does not prove no other system acted. Safe local work in the same request still proceeds.

## Supplying approved foundations before a design-token mission

The runner previously supplied only artifact hashes to the planner, leaving its
evidence, decision and volatile-constraint inputs empty. Supplying the following
facts now lets a ready project proceed without removing the gates:

1. **Persist the real upstream artifacts.** Use the existing Project OS artifact
   API for the approved `brand_core`, `brand_platform`, `positioning_statement`,
   identity guidelines and selected creative concept. The planner reads their
   current hashes from that project; `PlanningInputs` cannot invent them. If an
   upstream must still be authored, it remains planned work and may need a skill
   or provider the fabric does not have installed.
2. **Store the approved rendering values in memory.** The existing
   `brand.identity` subject must meet the `APPROVED_PROJECT_DECISION` authority
   floor. Its body supplies `brand_name`, the `primary`/`secondary`/`surface`/`text`
   palette roles and optional `heading_font`, `body_font`, `voice` and `locale`.
   Fonts are preserved rather than silently replaced with defaults. Literal
   rendering values do not belong in the qualitative `brand_core` contract.
3. **Pass the server-verified planning snapshot.** It contains source references,
   verified `EvidenceItem`s (two supporting `identity_guidelines` when those
   guidelines need to be produced), an accepted `creative_direction` decision
   when that decision is in the backchain, and the fresh
   `accessibility.standard` `VolatileConstraint`. The latter needs its actual
   source, retrieval time, value, verification status and recheck/expiry time.
   An accepted decision needs its actual selected alternative and independent
   human approver. These are input records, not permissions inferred from prose.

```python
from services.langgraph.agency.intake import PlanningInputs, run_mission

# trusted_snapshot is loaded and verified by server code from the project's
# approved sources; it is not an arbitrary request body or a generated default.
inputs = PlanningInputs.model_validate(trusted_snapshot)
outcome = run_mission(
    principal, request_text, export_root=export_root,
    planning_inputs=inputs,
)
```

`PlanningInputs` uses the existing compiled-planner `EvidenceItem`,
`DecisionNode` and `VolatileConstraint` schemas. Its `tenant_id` and `project_id`
must match the server principal and the resolved project. Cross-scope inputs
stop before any mission writes. Duplicate evidence references cannot inflate
the evidence floor, and structurally invalid accepted decisions are rejected.
Missing, unverified or expired inputs retain the planner's existing blockers.

The snapshot hash and source references are recorded in the mission contract;
the hash participates in mission identity and the `WORK_STARTED` event. No
planning facts are extracted as verified facts from “approved”, “ratified” or
“WCAG” wording in the request. Callers are responsible for resolving and checking
the cited evidence and decision records before constructing this trusted input.

With existing upstreams, approved brand memory and current planning inputs, a
local token mission compiles and independently verifies real persisted tokens,
then returns `AWAITING_APPROVAL`. It does not approve or release them. There is
no built-in copy of any external brief's “Sections 1–3” or ratified token values;
those sources must be supplied for the actual project.

## Planner fix included

`media_asset` was added to the N1 ontology for rendered media, but the compiled planner's `ARTIFACT_STAGE` map was not updated. Planning a `media_asset` deliverable raised `KeyError`. The map now places `media_asset` in `S14` (PRODUCE). The backchain also returns an `ARTIFACT_STAGE_UNMODELED` blocker instead of crashing if another N1 type is ever added without a stage. A test asserts every N1 type has a stage.

## Not covered by this slice

- No HTTP route or UI yet. The slice is called from Python, and its tests drive the existing approval route over HTTP.
- No `InteractionDecisionReceipt`, `ProjectAffinityGraph`, `ProofDAG`, metric dictionary or OpenTelemetry spans.
- SVG media and DTCG design-token sets have independent read-back checks; other
  persisted types verify as `INCONCLUSIVE`, never `PASSED`.
- A design-token request without the documented upstream and planning inputs
  still blocks. This slice does not fetch or ratify sources, create human
  decisions, or provide a general-purpose missing-upstream producer.
- Temporal memory beyond `fresh_until` (valid time versus observed time) is not modelled.

Tests: `services/langgraph/tests/test_intake_mission.py`.
