# AVIC contract map

`requirement -> owner -> source -> schema -> storage -> consumer -> test -> evidence -> status`

| Requirement | Owner | Source | Schema | Storage | Consumer | Test (`test_avic.py`) | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| Brief intake, exact text | PromptIR | `prompt_compiler.AssetRequirement` | `IntentIR`, `IntentItem` | `foundry-avic-<a>-intent` (asset_prompt_set) | scene, evaluator | `test_intent_reuses_promptir_and_classifies_every_item` | requirements.json | IMPLEMENTED_VERIFIED |
| ACE FILTER classes | AVIC | `avic/intent.py` | `Classification` | inside IntentIR | compile gate | `test_prompt_injection_and_effects_are_data_not_policy` | blocked reasons | IMPLEMENTED_VERIFIED |
| Output profile integrity | AVIC | `avic/intent.py`, `svg.validate` | `OutputProfile` | scene.json, evaluation.json | evaluator, release | `test_raster_and_hybrid_profiles_are_never_silently_substituted`, malicious-SVG cases | `profile_integrity` | IMPLEMENTED_VERIFIED |
| References: hash, palette, rights | AVIC (projection) | `avic/references.py` | `ReferenceManifest`, `ReferenceAsset` | `-references` (creative_concept) | scene colour choice | `test_references_are_hashed_measured_and_rights_gated` | reference.json | IMPLEMENTED_VERIFIED |
| Brand palette | Foundry PSEM / approved source | `foundry.psem.PALETTE` | `BrandIR` (projection) | `-brand` (design_system_spec) | scene, evaluator, edits | `test_psem_profile_uses_the_one_psem_palette` | brand.json | IMPLEMENTED_VERIFIED |
| Scene compilation | AVIC | `avic/scene.py` | `SceneIR` | `-scene` (creative_concept) | emitter, repair | `test_scene_is_deterministic_and_covers_every_requirement` | scene.json | IMPLEMENTED_VERIFIED |
| Requirement coverage | AVIC | `scene.requirement_coverage` | `RequirementMapping` rows | requirements.json, evaluation.json | release gate | `test_unmapped_requirements_are_reported_not_dropped` | coverage | IMPLEMENTED_VERIFIED |
| SVG generation | AVIC | `avic/svg.emit` | SVG bytes | `-svg` (media_asset) | renderer, approval | `test_emitted_svg_passes_the_allowlist_and_is_native` | master.svg | IMPLEMENTED_VERIFIED |
| SVG security | Execution fabric + AVIC | `verifiers.svg_safety` + `svg.validate` | `Check` | evaluation.json | every store, release | `test_malicious_or_invalid_svg_is_rejected` (15), `test_resource_ceilings_reject_oversized_and_deep_documents` | checks | IMPLEMENTED_VERIFIED |
| Rendering | Visual engine | `visual.browser.rasterize_svg` | PNG bytes | `-preview` (media_asset) | evaluator | `test_slice_renders_and_passes_independent_evaluation` | preview.png | IMPLEMENTED_VERIFIED |
| Independent verification | AVIC (PVSE role) | `avic/evaluate.py` | `EvaluationReport` | `-evaluation` (qa_report) | repair, release | `test_evaluator_reads_the_bytes_not_the_scene` | evaluation.json | IMPLEMENTED_VERIFIED |
| Edits | AVIC | `avic/edits.py` | `TransformationRecord` | new scene/svg/preview/evaluation versions | service | `test_edits_are_bounded_by_brief_brand_and_protection` | provenance.json `edits` | IMPLEMENTED_VERIFIED |
| H3 repair | AVIC | `avic/repair.py` | `DefectIR`, `RepairProposal` | evaluation.json `repairs` | service, CLI | five repair tests incl. Chromium | repair attempts | IMPLEMENTED_VERIFIED |
| H1 fidelity | AVIC | `avic/optimize.py` | candidate rows | benchmark_results.json | CLI | `test_reconstruction_is_deterministic_native_and_improves_with_budget`, `test_h1_measured_fidelity_with_real_render` | measured ΔE76 | PARTIAL |
| H2 brand mutation | AVIC | `avic/brand.mutate_brand` | `MutationRecord` | caller-owned | variants | `test_brand_mutations_need_approval_and_never_touch_protected_invariants` | record | IMPLEMENTED_VERIFIED |
| H4 branches | AVIC | `avic/brand.explore` | `VariantBranch` | variants.json (CLI) | selection | `test_h4_branches_keep_immutable_constraints_and_never_carry_approval` | variants.json | IMPLEMENTED_VERIFIED |
| H5 materials | AVIC | `avic/materials.py` | `MaterialSpec` | scene.json (`material_ref`, gradients) | scene | `test_material_parameters_carry_provenance_and_make_no_physical_claim` | gradients | IMPLEMENTED_VERIFIED (illustrative only) |
| Authorization | security/auth + Project OS | `service._authorize` | `Principal` | — | every service call | `test_cross_tenant_and_out_of_scope_principals_are_denied` | `AvicAccessDenied` | IMPLEMENTED_VERIFIED |
| N3 output authority | Kernel | `assert_role_may_produce` | `RoleContract` | — | `service._put` | lineage test (role per stage) | stage roles | IMPLEMENTED_VERIFIED |
| Approval | Approvals | `intake.release.open_artifact_approval` | `approvals` row | approvals table | `/approvals/{id}/decide` | lineage test (self-approval 403, second person 200) | approval id | IMPLEMENTED_VERIFIED |
| Release | Delivery (shared) | `intake.release.artifact_release_verdict` | `ReleaseManifest` | `-release` (release_record) | operator | lineage + tamper tests | release.json | IMPLEMENTED_VERIFIED (local record only) |
| Cache identity | AVIC | `service.cache_identity` | hash | provenance.json | recompile | `test_cache_divergence_is_rejected` | `CACHE_DIVERGENCE` | IMPLEMENTED_VERIFIED |
| Telemetry | AVIC | `service._produce`, `run.run_local` | dict | returned, not stored | CLI summary | demo output | measured ms | IMPLEMENTED_UNTESTED (values are measurements; no assertion on magnitude) |

Records listed in the directive that map onto existing schemas instead of new ones: `ImageIntentIR` is folded into
`IntentIR` + `SceneIR.composition` (no field needed a separate record); `RequirementMapping` is the coverage row; there is
no separate `constraints.json` artifact in Project OS (constraints live in `scene.json`; the CLI package writes
`constraints.json` as a convenience copy).
