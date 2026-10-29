# agency/intake

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Governed intake mission — words to a release decision

`services/langgraph/agency/intake/` connects a raw request to a release verdict through existing primitives only:

- **Intent.** A deterministic `compile_intent`, with no model call. Facts keep source spans. Publish, spend and send are `FORBIDDEN_TO_INFER`. Approval wording is only an `APPROVAL_CANDIDATE`. `SIMULATION` is a server argument, never inferred from text.
- **Project.** `resolve_project` filters on tenant, then `Principal` access, then archived state, before matching. Filtered projects are counted, never named. The order is explicit id, then name/slug/brand, then the active project. Ties, or a named project that differs from the active one, are `AMBIGUOUS`.
- **Context.** `compile_context` wraps the unchanged `project_os.memory.resolve`. On top of it, it:
  - takes conversation memory (M3) only from this thread;
  - drops learning memory (M6);
  - applies an authority floor;
  - withholds same-authority conflicts;
  - reports all-stale subjects as `UNRESOLVED_STALE`;
  - enforces a byte budget.

  The capsule hash covers the selected memory and the mission's input artifact heads. The mission's own output type is excluded, so replays keep their identity.
- **Execution.** It runs through the existing compiled planner and `execute_mission` in LOCAL mode.
- **Verification.** `verify_artifact` re-reads the stored bytes and checks the SHA-256 against the recorded hash, the version binding, SVG structure, `svg_safety` and palette conformance. A type with no verifier is `INCONCLUSIVE`, never `PASSED`.
- **Approval.** It uses the existing `approvals` table and a run with `needs_approval` and `initiated_by`, so `/approvals/{id}/decide` enforces the approver role and separation of duties. The subject hash is the verified content hash.
- **Release.** `release_gate` fails closed on simulation, a stale verification, or an approval that is missing, pending, rejected, stale, mismatched or self-approved. It never performs an effect.
- **External effects.** Publish, spend and send are never dispatched. Each gets a `NonActionReceipt` that states its own limits.

The slice adds no route, UI, table, event type or migration. It is Python-only; the tests drive the real approval route. Details: `docs/intake-mission.md`.
