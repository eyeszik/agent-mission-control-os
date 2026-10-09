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
| Planning | `runner._plan` | Compiled agency planner, with upstream inputs taken from the project's real artifact heads |
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

## Planner fix included

`media_asset` was added to the N1 ontology for rendered media, but the compiled planner's `ARTIFACT_STAGE` map was not updated. Planning a `media_asset` deliverable raised `KeyError`. The map now places `media_asset` in `S14` (PRODUCE). The backchain also returns an `ARTIFACT_STAGE_UNMODELED` blocker instead of crashing if another N1 type is ever added without a stage. A test asserts every N1 type has a stage.

## Not covered by this slice

- No HTTP route or UI yet. The slice is called from Python, and its tests drive the existing approval route over HTTP.
- No `InteractionDecisionReceipt`, `ProjectAffinityGraph`, `ProofDAG`, metric dictionary or OpenTelemetry spans.
- Only SVG media has an independent verifier; any other persisted type verifies as `INCONCLUSIVE`, never `PASSED`.
- A design-token request routes correctly but stays `BLOCKED` at planning in a project like the test fixture: the planner
  requires identity guidelines evidence, a verified WCAG volatile constraint and a human creative-direction decision first.
- Temporal memory beyond `fresh_until` (valid time versus observed time) is not modelled.

Tests: `services/langgraph/tests/test_intake_mission.py`.
