# agency/creative

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Creative search runtime — bounded search, human-gated

`services/langgraph/agency/creative/` runs a brief through `MissionIR → ExecutionPlan → context portfolio → candidates → hard gate → blind critics → Pareto front → HUMAN → ≤1 correction + TriDiff → approval → delivery gate`. It is deterministic: there are no model calls, and model-backed types (image, video, social, brand identity) plan `BLOCKED` as `provider_gap`.

- **Capability registry.** `knowledge/creative-capabilities/registry.json` (hash-pinned guides, dispositions) is loaded by `capabilities.py`.
- **Topology.** `organization.py` picks the smallest topology (T0–T4). T4 search runs only when the brief asks for exploration and `max_candidates > 1`. The caps are schema-enforced: population ≤ 4, generations ≤ 2, corrections ≤ 1.
- **Context.** `context.py` reads the design corpus only through `load_validated_corpus`. References contribute abstract principles only; unknown rights are excluded. `derive_requirements` maps the owned accessibility contract into renderer requirements.
- **Critics.** They see a lineage-free `BlindView`. `ConstraintValidator` is non-compensable.
- **HITL.** It reuses `create_approval_request(subject_hash=<ArtifactIR hash>)`: no graph change, no migration. `delivery_gate` fails closed on pending, rejected, stale or hash-mismatched approvals and never performs delivery.
- **Recorder.** `recorder.py` refuses free text and secrets.

CLI: `creative-run`. Details: `docs/creative-runtime.md`.
