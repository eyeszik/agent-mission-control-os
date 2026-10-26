# ACE × AVIC — governed visual compilation to native SVG

`services/langgraph/agency/avic/` turns an authorized brief into a verified, approval-gated **native SVG** and a separate PNG preview. It is built from existing owners and adds no table, migration, approval store, scheduler or route.

```
INGEST -> HASH_INTENT -> FILTER -> REFERENCE_ANALYSIS -> BRAND_VALIDATION -> IMAGE_INTENT -> SCENE_COMPILATION
-> GENERATE (emit SVG) -> RENDER (local Chromium) -> EVALUATE (independent) -> CAUSAL_REPAIR (H3, bounded)
-> FEASIBLE_PARETO_SELECTION -> APPROVAL (/approvals/{id}/decide) -> RELEASE (local record, no external effect)
```

## What owns what

| Concern | Owner (reused) | AVIC adds |
|---|---|---|
| Brief, exact text, references | PromptIR `AssetRequirement` (`agency/prompt_compiler.py`) | `IntentIR` (ACE classification), reference-role projection onto PromptIR roles |
| Brand palette | `foundry.psem.PALETTE` (PSEM) or another approved palette source | `BrandIR`: a read-only projection, never an authority |
| Artifacts, versions, lineage, invalidation | Project OS through `foundry.studio.store` / `observe` | stage keys `foundry-avic-<asset>-<stage>` |
| Output authorization | N3 `assert_role_may_produce` | stage→role map (`service.STAGES`) |
| Rendering | `visual.browser.rasterize_svg` (local Chromium, network namespace, non-`data:` requests aborted) | — |
| SVG safety | `execution_fabric.verifiers.svg_safety` | an **allowlist** validator on top (`svg.validate`) |
| Contrast, colour distance | `ui_ux.tokens.wcag_contrast_ratio`, `verifiers.delta_e76` / `palette_conformance` | — |
| Approval and release | `intake.release.open_artifact_approval`, `artifact_release_verdict`, `/approvals/{id}/decide` | `APPROVAL_POLICY = amc-avic-approval/v1` |
| Hashing | `execution.canonical` (AMC-CANON-1) | — |

Stage → N3 role → N1 type: `intent` creative_director/asset_prompt_set · `references`, `scene` creative_director/creative_concept · `svg`, `preview` creative_director/media_asset · `brand` design_lead/design_system_spec (projection) · `evaluation`, `provenance` brand_safety_reviewer/qa_report · `release` release_manager/release_record.

## Capability matrix (measured in this repository, see `docs/engineering/avic-m0-report.md`)

| Capability | State | Evidence / limit |
|---|---|---|
| ACE intent: classification, injection containment, effects never inferred | IMPLEMENTED_VERIFIED | `test_avic.py` intent tests |
| Output profiles: native editable / fidelity / illustrative | IMPLEMENTED_VERIFIED | allowlist `profile_integrity`; raster refused in native profiles |
| HYBRID_SVG, RASTER_FINAL | BLOCKED | no raster generation provider; refused, never substituted |
| SceneIR + deterministic SVG emitter | IMPLEMENTED_VERIFIED | same inputs → same bytes (test) |
| Allowlist SVG validator (elements, attributes, local refs, ids, finite coords, ceilings) | IMPLEMENTED_VERIFIED | 15 malicious/invalid cases rejected |
| Editorial vertical slice (background, headline, motif, gradient material object, lighting, annotation) | IMPLEMENTED_VERIFIED | `runtime/avic/demo/` |
| Edits: inspect, recolor, change_text, set_geometry, validate | IMPLEMENTED_VERIFIED | exact text / protected geometry / off-palette edits refused |
| Independent evaluation (exact text, palette, accent budget, WCAG contrast, text fit estimate, nonblank, headline ink) | IMPLEMENTED_VERIFIED | reads SVG/PNG bytes, not the compiler objects |
| Project OS persistence, lineage, approval, local release, approval non-inheritance, tamper detection, cache divergence | IMPLEMENTED_VERIFIED | service tests drive the real `/approvals/{id}/decide` route |
| H3 causal repair (contrast, palette, accent budget, text overflow, exact text) | IMPLEMENTED_VERIFIED | isolated re-render + independent re-evaluation, rollback, ≤3 attempts |
| H3 automatic repair of blank renders | PROPOSED | reported as a defect with hypotheses; human review |
| H1 coarse-to-fine region reconstruction + linear-gradient fitting + Pareto | PARTIAL | measured fidelity vs Chromium render; stdlib CPU baseline |
| H1 DiffVG / LIVE / Bézier contour fitting / Jacobian constraint projection | PROPOSED | optional research dependencies not installed or licence-reviewed |
| H2 governed brand mutation (approval required, protected invariants, rollback ref) | IMPLEMENTED_VERIFIED | `mutate_brand` tests |
| H4 reproducible variant branches, Pareto selection, no approval inheritance | IMPLEMENTED_VERIFIED | Chromium test + demo `variants.json` |
| Style profiles: Post-Surrealist Editorial, Swiss Editorial Modernism, Technical Minimalism, Geometric Infographics | IMPLEMENTED_VERIFIED | other 12 listed profiles are PROPOSED and refused |
| H5 material parameters with provenance; vector shading for 10 families; bounded vector texture | IMPLEMENTED_VERIFIED | palette-only shading; `physical_claim = NONE` |
| Physically based material rendering / inverse rendering | BLOCKED | no physics backend |
| Semantic reference analysis (subjects, styles) | PROPOSED | references contribute measured palettes only |
| Video / motion | PROVIDER_GAP (not AVIC) | belongs to cinematic/motion capabilities |
| API route / web UI | not added | Python and CLI only in this slice |

## Rules the code enforces

- **Brief text is data.** `intent.compile_intent` classifies every item `VERIFIED | INFERRED | PROPOSED | UNSUPPORTED | PROHIBITED`. Instruction-like text, external effects (publish, send, spend) and reproduction of third-party marks are PROHIBITED; photographic generation, 3D and motion are UNSUPPORTED. A blocked hard requirement stops the compile before anything is stored.
- **Raster is never vectorization.** Native profiles reject any `<image>`; `svg_safety` rejects non-local `href`, so HYBRID is impossible until a reviewed path exists.
- **Exact text** is rendered as escaped SVG text and read back from the bytes by the evaluator. An edit cannot change text that the brief fixed; a repair can only restore it.
- **Brand.** Colours come only from the `BrandIR` palette (checked as ΔE76 ≤ 2.3 on every literal colour). At most `max_signal_accents` accents. Accents sit on a ground they reach 3:1 against, so with PSEM the charcoal becomes the ground (Signal Red on Paper is 2.86:1).
- **Failed candidates are not promoted.** A failing edit or recompile is returned `REJECTED` and the stored head is kept.
- **Approval binds bytes.** Approval is opened on the SVG's content hash; an edit, repair or variant produces new bytes and the old approval cannot release them (`SUBJECT_HASH_MISMATCH` / `VERIFICATION_STALE`). The requester cannot approve their own artifact.
- **Release re-verifies.** `release_local` re-reads the stored SVG, checks its hash against the head and the evaluation, re-runs the allowlist, then asks the shared release verdict. Tampered storage is `STORED_BYTES_MISMATCH`. `external_effects` is always `none`.
- **Cache identity** = canonical hash of the normalized request, brand, profile, seed, references, material, compiler/renderer/schema/policy versions and output profile. The same identity producing different bytes is `CACHE_DIVERGENCE` and is rejected.
- **Renderer variance is measured, not hidden.** Chromium's software rasterizer is not bit-exact: identical SVG rendered 5 times gave 2 distinct PNGs, differing by at most 2/255 per channel on 0.8% of pixels (soft blurs and gradients). The SVG is the source of truth and is byte-deterministic; when an unchanged SVG re-renders within 2/255 of the stored preview, the stored preview is reused (`service.RENDER_TOLERANCE`), so identical inputs stay idempotent. A larger difference is treated as a real change.
- **Telemetry** (compile/render/verify latency, repair attempts and success rate, SVG bytes and elements) is measured and returned to the caller; it is kept out of content-addressed records so identical inputs stay idempotent. No Datadog dependency.

## H3 repair

`repair.detect` turns only **failed** independent checks into `DefectIR`s, with the evaluation hash as evidence and causes as hypotheses; checks that could not run are reported as missing evidence. `propose` changes the defect's target plus its dependency closure (dependents, children, clip users), never moves protected geometry, and is deterministic. The child is re-emitted in full and diffed against the parent: a change outside the declared set is cache divergence and the proposal is rejected. Each proposal is rendered in its own directory and evaluated independently; it is accepted only if the targeted check passes and nothing that passed before regresses, otherwise the parent is kept. At most 3 attempts per defect.

## H1 fidelity reconstruction

`optimize.candidates(png)` splits the working grid where Lab error is largest, fits flat colour and least-squares linear gradients per region, and emits rect + `linearGradient` SVG at several budgets. `optimize.compare` measures the Chromium render against the reference (MSE, PSNR, mean ΔE76). Demo results, synthetic 320×240 reference, measured at full resolution (`runtime/avic/demo/benchmark_results.json`): budget 16 → mean ΔE76 7.20, 64 → 3.86, 256 → 1.61. Region count is not evidence of fidelity; only the measured numbers are.

## Run it

```bash
python3 orchestrate_brand_pipeline.py avic --input sample_avic_request.json --out /tmp/avic-out           # compile, render, verify
python3 orchestrate_brand_pipeline.py avic --input sample_avic_request.json --out /tmp/avic-out \
        --reference path/to/reference.png --variants 3                                                       # + H1 benchmark, H4 variants
python scripts/render_avic_demo.py                                                                          # regenerates runtime/avic/demo/
python -m pytest services/langgraph/tests/test_avic.py -q
```

The CLI exit code is 0 when evaluation passed, 1 when it failed or policy blocked it, 3 when Chromium is unavailable. A local run is never released; `release.json` says why. Project-scoped approval and release go through `services.langgraph.agency.avic.service` (`compile_asset`, `edit_asset`, `request_approval`, `release_local`).

## Not done

Hosted or local image/video generation, HYBRID/RASTER_FINAL output, semantic reference understanding, Bézier/differentiable vectorization, physically based materials, cross-editor (Inkscape/Illustrator) round-trip tests, a `/avic` API route and a web UI, Cloudflare deployment of the archived Realism Engine worker. The archived Realism Engine sources were inspected as data; none of their code is imported (see `docs/engineering/avic-m0-report.md`).
