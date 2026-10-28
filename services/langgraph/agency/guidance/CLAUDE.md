# agency/guidance

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Guidance registry + prompt compiler — stops deliberately short of generation

`agency/guidance/` (models/registry/router) and `agency/prompt_compiler.py` are a second, newer subsystem alongside the kernel, reachable via `orchestrate_brand_pipeline.py compile-prompts`. Two parts:

- **Guidance registry** (`agency/guidance/packs/*.yaml`, e.g. `pg.branding.core`, `pg.studio_identity.v4`): hash-verified (`content_hash` per pack, `registry_hash` over all packs), YAML-as-JSON-1.2 (rejects duplicate keys, no custom tags/aliases — deterministic stdlib parsing). Every pack is `authority_class: ADVISORY` or `EVIDENCE_BOUND_ADVISORY` — guidance can shape how a prompt is compiled, it can never redefine runtime policy, permissions, or canonical `BrandCore` state (`guidance/models.py`'s module docstring is explicit about this). `router.py`'s `route_guidance()` selects packs/sections by a deterministic weighted-overlap score against the request (asset family/type, channel, brand domains, capabilities, task tags) — **no LLM call in routing**, so identical inputs always select identically.
- **Prompt compiler** (`prompt_compiler.py`, ~1300 lines): five explicit audit passes — `intake_claims → hunt_gaps → build_research_backfill → validate_claims → synthesize_report` — before it will compile a prompt package, so retrieval can't silently rewrite source material and every unresolved premise stays visible. Its own module docstring states the boundary plainly: *"intentionally stops at validated prompt packages. It never invokes a media provider, writes a generated asset, publishes content, or performs any other external creative side effect."* `CompilerState`'s terminal success value is `PROMPT_PACKAGE_READY` (`GENERATION_FIREWALL` in the module) — there is deliberately no `ASSETS_GENERATED` state in this enum.

Read together: this is the validated, evidence-grounded input a real image/video generation skill would consume — it is not that skill. Wiring an actual provider behind `PROMPT_PACKAGE_READY` output is still open work, same as the rest of the kernel-to-Layer-1 integration gap above.
