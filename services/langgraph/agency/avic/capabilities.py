"""Capability registry: every AVIC capability, its state, and the tests that back the claim.

The matrix in ``docs/avic.md`` is generated from this table (``docs_table``), and a test checks that every
``IMPLEMENTED_VERIFIED`` / ``PARTIAL`` row names tests that exist, so the documentation cannot claim more than the
test suite proves. States: IMPLEMENTED_VERIFIED, PARTIAL, PROPOSED, BLOCKED, PROVIDER_GAP, NOT_ADDED.
"""

from __future__ import annotations

from typing import NamedTuple


class Capability(NamedTuple):
    name: str
    state: str
    limit: str
    tests: tuple[str, ...] = ()


CAPABILITIES: tuple[Capability, ...] = (
    Capability("ACE intent: classification, injection containment, effects never inferred", "IMPLEMENTED_VERIFIED",
               "Unicode-normalised scan copy (NFKC, invisible characters, lookalike letters); stored text untouched",
               ("test_intent_reuses_promptir_and_classifies_every_item", "test_prompt_injection_and_effects_are_data_not_policy",
                "test_intent_filter_survives_unicode_evasions",
                "test_intent_normalization_does_not_mangle_or_over_block_benign_text")),
    Capability("Output profiles: native editable / fidelity / illustrative", "IMPLEMENTED_VERIFIED",
               "raster refused in native profiles", ("test_scene_ir_rejects_raster_in_native_profile_and_dangling_references",)),
    Capability("HYBRID_SVG, RASTER_FINAL", "BLOCKED", "no raster generation provider; refused, never substituted",
               ("test_raster_and_hybrid_profiles_are_never_silently_substituted",)),
    Capability("SceneIR + deterministic SVG emitter", "IMPLEMENTED_VERIFIED", "same inputs give the same bytes",
               ("test_scene_is_deterministic_and_covers_every_requirement",)),
    Capability("Allowlist SVG validator (elements, attributes, local refs, ids, finite coords, ceilings)", "IMPLEMENTED_VERIFIED",
               "malicious and invalid documents rejected", ("test_malicious_or_invalid_svg_is_rejected",
                                                             "test_resource_ceilings_reject_oversized_and_deep_documents")),
    Capability("Editorial vertical slice (background, headline, motif, material object, lighting, annotation)",
               "IMPLEMENTED_VERIFIED", "`runtime/avic/demo/`", ("test_slice_renders_and_passes_independent_evaluation",)),
    Capability("Edits: inspect, recolor, change_text, set_geometry, validate", "IMPLEMENTED_VERIFIED",
               "exact text, protected geometry and off-palette edits refused",
               ("test_edits_are_bounded_by_brief_brand_and_protection",)),
    Capability("Edit concurrency: stale base and racing writers conflict instead of overwriting", "IMPLEMENTED_VERIFIED",
               "compare-and-set on the head hash read; the scene is the commit record",
               ("test_store_checks_the_head_it_was_computed_from", "test_an_edit_against_a_stale_base_conflicts_and_stores_nothing",
                "test_a_writer_that_slips_in_between_read_and_write_is_detected")),
    Capability("Crash recovery: stale derived stages detected, blocked from release, re-derived from the scene", "IMPLEMENTED_VERIFIED",
               "no transaction across stages; `consistency` + `recompile_asset`",
               ("test_a_crash_between_stage_writes_fails_closed_and_recompile_recovers",)),
    Capability("Independent evaluation (exact text, palette, accent budget, WCAG contrast, text fit estimate, nonblank, headline ink)",
               "IMPLEMENTED_VERIFIED", "reads SVG/PNG bytes, not the compiler objects",
               ("test_evaluator_reads_the_bytes_not_the_scene",)),
    Capability("Margin bands: content in the outer half-margin measured on rendered pixels", "IMPLEMENTED_VERIFIED",
               "reported as a defect with no automatic repair",
               ("test_margin_bands_see_ink_where_nothing_may_be", "test_pixels_catch_an_overflow_that_the_glyph_estimate_misses",
                "test_a_normal_slice_has_clean_margins")),
    Capability("Project OS persistence, lineage, approval, local release, approval non-inheritance, tamper detection, cache divergence",
               "IMPLEMENTED_VERIFIED", "service tests drive the real `/approvals/{id}/decide` route",
               ("test_project_os_lineage_approval_release_and_no_approval_inheritance",
                "test_tampered_stored_bytes_block_approval_and_release", "test_cache_divergence_is_rejected",
                "test_cross_tenant_and_out_of_scope_principals_are_denied")),
    Capability("H3 causal repair (contrast, palette, accent budget, text overflow, exact text)", "IMPLEMENTED_VERIFIED",
               "isolated re-render + independent re-evaluation, rollback, at most 3 attempts",
               ("test_h3_repairs_a_contrast_defect_with_an_isolated_render_and_independent_evaluation",
                "test_failed_repair_rolls_back_and_keeps_the_parent")),
    Capability("H3 automatic repair of blank renders and margin overflow", "PROPOSED",
               "reported as a defect with hypotheses; human review", ("test_detect_only_turns_failures_into_defects_and_reports_missing_evidence",)),
    Capability("H1 coarse-to-fine region reconstruction + linear-gradient fitting + Pareto", "PARTIAL",
               "measured fidelity vs Chromium render; stdlib CPU baseline",
               ("test_reconstruction_is_deterministic_native_and_improves_with_budget", "test_h1_measured_fidelity_with_real_render")),
    Capability("H1 DiffVG / LIVE / Bezier contour fitting / Jacobian constraint projection", "PROPOSED",
               "optional research dependencies not installed or licence-reviewed"),
    Capability("H2 governed brand mutation (approval required, protected invariants, rollback ref)", "IMPLEMENTED_VERIFIED",
               "`mutate_brand`", ("test_brand_mutations_need_approval_and_never_touch_protected_invariants",)),
    Capability("H4 reproducible variant branches, Pareto selection, no approval inheritance", "IMPLEMENTED_VERIFIED",
               "Chromium test + demo `variants.json`", ("test_h4_branches_keep_immutable_constraints_and_never_carry_approval",)),
    Capability("Style profiles: Post-Surrealist Editorial, Swiss Editorial Modernism, Technical Minimalism, Geometric Infographics",
               "IMPLEMENTED_VERIFIED", "the other 12 listed profiles are PROPOSED and refused",
               ("test_proposed_style_profiles_are_refused_not_approximated", "test_psem_profile_uses_the_one_psem_palette")),
    Capability("H5 material parameters with provenance; vector shading for 10 families; bounded vector texture",
               "IMPLEMENTED_VERIFIED", "palette-only shading; `physical_claim = NONE`",
               ("test_material_parameters_carry_provenance_and_make_no_physical_claim",)),
    Capability("Physically based material rendering / inverse rendering", "BLOCKED", "no physics backend"),
    Capability("Semantic reference analysis (subjects, styles)", "PROPOSED",
               "references contribute measured palettes only", ("test_references_are_hashed_measured_and_rights_gated",)),
    Capability("Video / motion", "PROVIDER_GAP", "belongs to cinematic/motion capabilities, not AVIC"),
    Capability("`/avic` API: tenant-scoped, operator-gated writes, idempotent, stale edits are 409, inert SVG serving",
               "IMPLEMENTED_VERIFIED", "brand is the server projection; client authority fields are rejected; route sweep covers every path",
               ("test_another_tenant_learns_nothing", "test_read_only_role_reads_but_cannot_write",
                "test_every_route_requires_authentication", "test_client_supplied_authority_is_rejected",
                "test_stored_svg_is_served_inert", "test_operator_path_edit_conflict_recovery_approval_release",
                "test_recorded_fixture_matches_live_responses")),
    Capability("Visual Compiler section in `/agency` (compile, inspect, edit, recover, request approval, release)", "IMPLEMENTED_VERIFIED",
               "browser test `apps/web/e2e/visuals.spec.ts` (axe WCAG 2.2 AA, stale-edit conflict, phone width); approval is decided in the queue",
               ("test_operator_path_edit_conflict_recovery_approval_release",)),
    Capability("Bounded render concurrency", "IMPLEMENTED_VERIFIED", "`AMC_AVIC_RENDER_CONCURRENCY` (default 2); no slot in time is BLOCKED",
               ("test_render_capacity_is_bounded_and_reported",)),
)

STATES = {"IMPLEMENTED_VERIFIED", "PARTIAL", "PROPOSED", "BLOCKED", "PROVIDER_GAP", "NOT_ADDED"}
MARK_BEGIN, MARK_END = "<!-- avic-capabilities:begin -->", "<!-- avic-capabilities:end -->"


def docs_table() -> str:
    rows = ["| Capability | State | Evidence / limit |", "|---|---|---|"]
    for c in CAPABILITIES:
        evidence = c.limit + (f" (tests: {', '.join(f'`{t}`' for t in c.tests)})" if c.tests else "")
        rows.append(f"| {c.name} | {c.state} | {evidence} |")
    return "\n".join(rows)


__all__ = ["CAPABILITIES", "Capability", "MARK_BEGIN", "MARK_END", "STATES", "docs_table"]
