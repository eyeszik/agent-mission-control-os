# agency/foundry

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Generative Creative Foundry — brief to verified brand family, locally

`services/langgraph/agency/foundry/` + `api/routes/foundry.py` + `CreativeFoundryPanel.tsx` (Mission Control mode):

- **Genome.** `compile_genome(UserBrief)` is deterministic, records assumptions and enforces palette contrast floors.
  The brief never carries authority.
- **Grammars.** Thirteen `VisualGrammar`s, blended by weight (the thirteenth, `psem_editorial`, is PSEM; `psem.py` holds its locked palette and computed pairing rules).
- **Composition.** `compose.py` emits CompositionIR (palette roles) and then SVG.
- **Variants.** `variants.py` mutates, crossbreeds and forks within `creative.ir.ResourceBudget` caps.
- **Experience twin.** `experience.py` builds working HTML evaluated by real Chromium scenarios and counterfactual
  skins.
- **Scene and motion.** `scene.py` renders a Blender package scene; `motion.py` turns keyframes into SVG frames,
  then Chromium, then FFmpeg.
- **Proofs.** `proof.py` computes the proof state machine from evidence.
- **Routing.** Local-first; a hosted model is a forbidden route.
- **Capabilities and discovery.** Capabilities are discovered, never installed. The discovery adapters are declared
  and DISABLED.

`studio.Mission` persists every deliverable as a Project OS artifact with `depends_on=genome`, reads it back and
verifies it. A genome revision invalidates dependents through the existing invalidation. Approval goes through
`open_artifact_approval` with the mission id scoped to the project. Don't add a second store or token compiler here.

The demo is `scripts/render_foundry_demo.py`, which writes `runtime/foundry/demo/` for a FICTIONAL brand.
Details: `docs/creative-foundry.md`.
