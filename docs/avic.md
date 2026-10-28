# ACE × AVIC — governed visual compilation to native SVG

`services/langgraph/agency/avic/` turns an authorized brief into a verified, approval-gated **native SVG** and a separate PNG preview. It is built from existing owners and adds no table, migration, approval store or scheduler; its one route is `/avic`, used by the Visual Compiler section of `/agency`. The capability matrix below is generated from `avic/capabilities.py` and checked against the test suite.

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

<!-- avic-capabilities:begin -->
| Capability | State | Evidence / limit |
|---|---|---|
| ACE intent: classification, injection containment, effects never inferred | IMPLEMENTED_VERIFIED | Unicode-normalised scan copy (NFKC, invisible characters, lookalike letters); stored text untouched (tests: `test_intent_reuses_promptir_and_classifies_every_item`, `test_prompt_injection_and_effects_are_data_not_policy`, `test_intent_filter_survives_unicode_evasions`, `test_intent_normalization_does_not_mangle_or_over_block_benign_text`) |
| Output profiles: native editable / fidelity / illustrative | IMPLEMENTED_VERIFIED | raster refused in native profiles (tests: `test_scene_ir_rejects_raster_in_native_profile_and_dangling_references`) |
| HYBRID_SVG, RASTER_FINAL | BLOCKED | no raster generation provider; refused, never substituted (tests: `test_raster_and_hybrid_profiles_are_never_silently_substituted`) |
| SceneIR + deterministic SVG emitter | IMPLEMENTED_VERIFIED | same inputs give the same bytes (tests: `test_scene_is_deterministic_and_covers_every_requirement`) |
| Allowlist SVG validator (elements, attributes, local refs, ids, finite coords, ceilings) | IMPLEMENTED_VERIFIED | malicious and invalid documents rejected (tests: `test_malicious_or_invalid_svg_is_rejected`, `test_resource_ceilings_reject_oversized_and_deep_documents`) |
| Editorial vertical slice (background, headline, motif, material object, lighting, annotation) | IMPLEMENTED_VERIFIED | `runtime/avic/demo/` (tests: `test_slice_renders_and_passes_independent_evaluation`) |
| Edits: inspect, recolor, change_text, set_geometry, validate | IMPLEMENTED_VERIFIED | exact text, protected geometry and off-palette edits refused (tests: `test_edits_are_bounded_by_brief_brand_and_protection`) |
| Edit concurrency: stale base and racing writers conflict instead of overwriting | IMPLEMENTED_VERIFIED | compare-and-set on the head hash read; the scene is the commit record (tests: `test_store_checks_the_head_it_was_computed_from`, `test_an_edit_against_a_stale_base_conflicts_and_stores_nothing`, `test_a_writer_that_slips_in_between_read_and_write_is_detected`) |
| Crash recovery: stale derived stages detected, blocked from release, re-derived from the scene | IMPLEMENTED_VERIFIED | no transaction across stages; `consistency` + `recompile_asset` (tests: `test_a_crash_between_stage_writes_fails_closed_and_recompile_recovers`) |
| Independent evaluation (exact text, palette, accent budget, WCAG contrast, text fit estimate, nonblank, headline ink) | IMPLEMENTED_VERIFIED | reads SVG/PNG bytes, not the compiler objects (tests: `test_evaluator_reads_the_bytes_not_the_scene`) |
| Margin bands: content in the outer half-margin measured on rendered pixels | IMPLEMENTED_VERIFIED | reported as a defect with no automatic repair (tests: `test_margin_bands_see_ink_where_nothing_may_be`, `test_pixels_catch_an_overflow_that_the_glyph_estimate_misses`, `test_a_normal_slice_has_clean_margins`) |
| Project OS persistence, lineage, approval, local release, approval non-inheritance, tamper detection, cache divergence | IMPLEMENTED_VERIFIED | service tests drive the real `/approvals/{id}/decide` route (tests: `test_project_os_lineage_approval_release_and_no_approval_inheritance`, `test_tampered_stored_bytes_block_approval_and_release`, `test_cache_divergence_is_rejected`, `test_cross_tenant_and_out_of_scope_principals_are_denied`) |
| H3 causal repair (contrast, palette, accent budget, text overflow, exact text) | IMPLEMENTED_VERIFIED | isolated re-render + independent re-evaluation, rollback, at most 3 attempts (tests: `test_h3_repairs_a_contrast_defect_with_an_isolated_render_and_independent_evaluation`, `test_failed_repair_rolls_back_and_keeps_the_parent`) |
| H3 automatic repair of blank renders and margin overflow | PROPOSED | reported as a defect with hypotheses; human review (tests: `test_detect_only_turns_failures_into_defects_and_reports_missing_evidence`) |
| H1 coarse-to-fine region reconstruction + linear-gradient fitting + Pareto | PARTIAL | measured fidelity vs Chromium render; stdlib CPU baseline (tests: `test_reconstruction_is_deterministic_native_and_improves_with_budget`, `test_h1_measured_fidelity_with_real_render`) |
| H1 DiffVG / LIVE / Bezier contour fitting / Jacobian constraint projection | PROPOSED | optional research dependencies not installed or licence-reviewed |
| H2 governed brand mutation (approval required, protected invariants, rollback ref) | IMPLEMENTED_VERIFIED | `mutate_brand` (tests: `test_brand_mutations_need_approval_and_never_touch_protected_invariants`) |
| H4 reproducible variant branches, Pareto selection, no approval inheritance | IMPLEMENTED_VERIFIED | Chromium test + demo `variants.json` (tests: `test_h4_branches_keep_immutable_constraints_and_never_carry_approval`) |
| Style profiles: Post-Surrealist Editorial, Swiss Editorial Modernism, Technical Minimalism, Geometric Infographics | IMPLEMENTED_VERIFIED | the other 12 listed profiles are PROPOSED and refused (tests: `test_proposed_style_profiles_are_refused_not_approximated`, `test_psem_profile_uses_the_one_psem_palette`) |
| H5 material parameters with provenance; vector shading for 10 families; bounded vector texture | IMPLEMENTED_VERIFIED | palette-only shading; `physical_claim = NONE` (tests: `test_material_parameters_carry_provenance_and_make_no_physical_claim`) |
| Physically based material rendering / inverse rendering | BLOCKED | no physics backend |
| Semantic reference analysis (subjects, styles) | PROPOSED | references contribute measured palettes only (tests: `test_references_are_hashed_measured_and_rights_gated`) |
| Video / motion | PROVIDER_GAP | belongs to cinematic/motion capabilities, not AVIC |
| `/avic` API: tenant-scoped, operator-gated writes, idempotent, stale edits are 409, inert SVG serving | IMPLEMENTED_VERIFIED | brand is the server projection; client authority fields are rejected; route sweep covers every path (tests: `test_another_tenant_learns_nothing`, `test_read_only_role_reads_but_cannot_write`, `test_every_route_requires_authentication`, `test_client_supplied_authority_is_rejected`, `test_stored_svg_is_served_inert`, `test_operator_path_edit_conflict_recovery_approval_release`, `test_recorded_fixture_matches_live_responses`) |
| Visual Compiler section in `/agency` (compile, inspect, edit, recover, request approval, release) | IMPLEMENTED_VERIFIED | browser test `apps/web/e2e/visuals.spec.ts` (axe WCAG 2.2 AA, stale-edit conflict, phone width); approval is decided in the queue (tests: `test_operator_path_edit_conflict_recovery_approval_release`) |
| Bounded render concurrency | IMPLEMENTED_VERIFIED | `AMC_AVIC_RENDER_CONCURRENCY` (default 2); no slot in time is BLOCKED (tests: `test_render_capacity_is_bounded_and_reported`) |
<!-- avic-capabilities:end -->

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
- **Concurrent edits conflict, they do not overwrite.** `edit_asset(base_svg_sha256=...)` returns `CONFLICT` (`STALE_BASE`) when the SVG the operator opened is no longer the head, and every stage write carries the head hash it was computed from (`foundry.studio.store(expect_head_hash=...)`), so a writer that slips in between read and write is detected. Nothing is stored on conflict.
- **No transaction spans the stages, so the scene is the commit record.** Stages are written scene, svg, preview, evaluation, provenance. A crash part-way leaves stale derived stages: `service.consistency` names them, `request_approval` and `release_local` block (`EVALUATION_STALE`, `EVALUATION_SCENE_MISMATCH`), and `service.recompile_asset` re-derives them from the stored scene (idempotent when nothing is stale).
- **Overflow is measured on pixels.** `margin_bands` flags content in the outer half-margin of the rendered PNG; the glyph-advance text-fit stays an estimate. A failure is a defect (`out_of_canvas`) with no automatic repair.
- **The intent filter scans a normalised copy** (NFKC, invisible and format characters removed, spaces collapsed, lookalike Cyrillic/Greek letters folded, with an alternate reading for glyphs that resemble two Latin letters). It is defence in depth: the stored text is untouched and the real controls are the allowlist, the evaluator and the approval gate.
- **Telemetry** (compile/render/verify latency, repair attempts and success rate, SVG bytes and elements) is measured and returned to the caller; it is kept out of content-addressed records so identical inputs stay idempotent. No Datadog dependency.

## H3 repair

`repair.detect` turns only **failed** independent checks into `DefectIR`s, with the evaluation hash as evidence and causes as hypotheses; checks that could not run are reported as missing evidence. `propose` changes the defect's target plus its dependency closure (dependents, children, clip users), never moves protected geometry, and is deterministic. The child is re-emitted in full and diffed against the parent: a change outside the declared set is cache divergence and the proposal is rejected. Each proposal is rendered in its own directory and evaluated independently; it is accepted only if the targeted check passes and nothing that passed before regresses, otherwise the parent is kept. At most 3 attempts per defect.

## H1 fidelity reconstruction

`optimize.candidates(png)` splits the working grid where Lab error is largest, fits flat colour and least-squares linear gradients per region, and emits rect + `linearGradient` SVG at several budgets. `optimize.compare` measures the Chromium render against the reference (MSE, PSNR, mean ΔE76). Demo results, synthetic 320×240 reference, measured at full resolution (`runtime/avic/demo/benchmark_results.json`): budget 16 → mean ΔE76 7.20, 64 → 3.86, 256 → 1.61. Region count is not evidence of fidelity; only the measured numbers are.

## API and operator UI

`/avic` (`api/routes/avic.py`), all routes authenticated and resolved against the project's recorded tenant:

| Route | Who | What |
|---|---|---|
| `GET /avic/capabilities` | any principal | registry rows with their tests, style profiles, renderer state and concurrency, the brand projection |
| `GET /avic/projects/{p}/assets`, `GET …/{asset}` | project reader | asset list; view with stage heads, evaluation, consistency, editable objects, approvals, last release |
| `GET …/{asset}/master.svg`, `…/preview.png` | project reader | stored bytes; SVG with `Content-Security-Policy: default-src 'none'; sandbox` and `nosniff` |
| `POST …/assets` | operator + `Idempotency-Key` | compile; the brand is the server's projection, never the request's |
| `POST …/{asset}/edits` | operator + `Idempotency-Key` | one edit; `base_svg_sha256` is required and a stale base is `409 CONFLICT` |
| `POST …/{asset}/recompile` | operator + `Idempotency-Key` | re-derive stale stages from the scene; a no-op when consistent |
| `POST …/{asset}/approval` | operator | open or reuse the approval bound to the current SVG hash |
| `POST …/{asset}/release` | operator | local release record; blocked unless verified, current and approved by someone else |

Requests reject unknown fields, so a client cannot send a brand, tenant, approver or `force`. The UI (`components/avic/VisualCompilerView.tsx`) shows the preview through `<img>` from the PNG (the SVG source is never injected into the page), lists every check, disables each control with its reason, reloads on a 409 and keeps Apply off until the newer version has loaded. `apps/web/e2e/visuals.spec.ts` drives it against the real stack (axe WCAG 2.2 AA, stale-edit conflict, phone width).

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

Hosted or local image/video generation, HYBRID/RASTER_FINAL output, semantic reference understanding, Bézier/differentiable vectorization, physically based materials, cross-editor (Inkscape/Illustrator) round-trip tests, reference uploads through the API, Cloudflare deployment of the archived Realism Engine worker. The archived Realism Engine sources were inspected as data; none of their code is imported (see `docs/engineering/avic-m0-report.md`).
