# agency/cinematic

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Cinematic capability — routed, not global

`services/langgraph/agency/cinematic/` is a lazily-loaded domain capability that compiles ideas/scripts/storyboards/images into T2I/T2V/I2V/storyboard/brand-motion prompts, with canonical `ProjectIR`/`ShotIR`, source-authority resolution, continuity handshakes, camera/lighting/physics reasoning, an evaluator, and a bounded repair loop. It routes via its own deterministic trigger metadata (`cinematic.route_request`) and honours the same firewall — it terminates at prompts and never invokes a media provider. It is a native module (real schemas/compilers/evaluator, not advisory prose) and its full specification is deliberately kept out of this file; see `docs/cinematic-capability.md` and invoke via `orchestrate_brand_pipeline.py cinematic`.
