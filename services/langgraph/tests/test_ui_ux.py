"""UI/UX design compiler: IR, principles, engines, tokens, prompt + runtime seams."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.langgraph.agency.prompt_compiler import (
    AssetRequirement,
    CompilerState,
    PromptCompilerRequest,
    PromptFamily,
    PromptValidationStatus,
    compile_prompt_packages,
    load_request,
)
from services.langgraph.agency.ui_ux import BrandContext, UIUXRequest, compile_uiux
from services.langgraph.agency.ui_ux.compiler import _STATE_TABLE
from services.langgraph.agency.ui_ux.evaluator import MAX_REPAIR_ITERATIONS
from services.langgraph.agency.ui_ux.models import (
    EvaluationEngine,
    Metric,
    MetricTruth,
    Severity,
    UIState,
    UIUXDesignIR,
    UIUXTerminal,
)
from services.langgraph.agency.ui_ux.principles import CATALOG
from services.langgraph.agency.ui_ux.tokens import apca_lc, wcag_contrast_ratio

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages/shared/tests/fixtures/uiux-design-ir.json"
PALETTE = ["#1F2937", "#F59E0B", "#F9FAFB"]


def _brand(**overrides) -> BrandContext:
    base = {"brand_name": "Acme", "tone_attributes": ["calm", "precise"], "palette_hex": PALETTE,
            "palette_source": "DESIGN_BRIEF"}
    return BrandContext(**{**base, **overrides})


def _request(**overrides) -> UIUXRequest:
    base = {
        "project_ref": "acme",
        "purpose": "Help operators resolve incidents quickly",
        "primary_user": "On-call operators",
        "primary_task": "Find and resolve the highest-priority incident",
        "business_goal": "Reduce time to resolution",
        "brand": _brand(),
    }
    return UIUXRequest(**{**base, **overrides})


def _fixture_request() -> UIUXRequest:
    # Must match the request that generated packages/shared/tests/fixtures/uiux-design-ir.json.
    return UIUXRequest(
        project_ref="fixture-assistant",
        surface="AI_INTERFACE",
        purpose="Help support leads draft accurate replies to customer tickets",
        primary_user="Support team leads",
        primary_task="Draft and verify a reply to a ticket",
        business_goal="Reduce time to first accurate reply",
        content_requirements=["Reorder saved reply snippets"],
        constraints=["Replies must cite the knowledge-base article used"],
        ai_provider_known=False,
        brand=BrandContext(brand_name="Fixture Co", tone_attributes=["calm", "precise"],
                           palette_hex=PALETTE, palette_source="DESIGN_BRIEF"),
    )


# --------------------------------------------------------------------------- #
# Surfaces
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("surface,component", [
    ("LANDING_PAGE", "PrimaryCTA"),
    ("APPLICATION", "TaskList"),
    ("DASHBOARD", "MetricTile"),
    ("AI_INTERFACE", "AITrustEnvelope"),
    ("FORM_FLOW", "ProgressStepper"),
])
def test_each_surface_compiles_to_a_ready_spec(surface, component):
    ir = compile_uiux(_request(surface=surface))
    assert ir.mode.value == surface
    assert ir.terminal is UIUXTerminal.spec_ready
    assert component in {c.name for c in ir.components}
    assert not [f for f in ir.evaluation if f.severity is Severity.blocking and not f.repaired]
    assert ir.handoff_only is True


def test_minimal_request_records_assumptions_instead_of_inventing():
    ir = compile_uiux(UIUXRequest(project_ref="bare"))
    ids = {a.id for a in ir.assumptions}
    assert {"assume.surface", "assume.platform", "assume.purpose", "assume.primary_user", "assume.palette"} <= ids
    assert ir.product_model.business_goal.startswith("Unstated")
    assert ir.terminal is UIUXTerminal.requires_approval  # palette decision outstanding
    assert ir.confidence.value < 0.85
    assert any("palette" in item for item in ir.approval_required)


def test_surface_is_inferred_from_wording():
    assert compile_uiux(_request(purpose="An analytics dashboard for store managers")).mode.value == "DASHBOARD"
    assert compile_uiux(_request(surface_hint="landing page")).mode.value == "LANDING_PAGE"
    # An explicit hint (a brief's product type) outranks description wording.
    booking = compile_uiux(_request(surface_hint="app", purpose="Booking app for independent barbers"))
    assert booking.mode.value == "APPLICATION"
    assert "surface hint" in next(a.reason for a in booking.assumptions if a.id == "assume.surface")


# --------------------------------------------------------------------------- #
# Principles, genome, determinism
# --------------------------------------------------------------------------- #


def test_principles_are_selective_and_each_one_changes_output():
    ir = compile_uiux(_request(surface="LANDING_PAGE"))
    applied = {p.id for p in ir.principles_applied}
    assert "platform.rtl" not in applied
    assert "system.ai_trust" not in applied
    assert "interaction.forms" not in applied
    assert all(p.changes for p in ir.principles_applied)
    assert len(applied) < len(CATALOG)


def test_features_activate_matching_principles():
    rtl = compile_uiux(_request(locale_rtl=True))
    assert "platform.rtl" in {p.id for p in rtl.principles_applied}
    assert "logical" in rtl.design_genome.geometry
    ai = compile_uiux(_request(ai_features=True))
    assert "system.ai_trust" in {p.id for p in ai.principles_applied}
    assert ai.ai_trust.required and ai.ai_trust.confidence_display == "NOT_MEASURED"


def test_compilation_is_deterministic():
    first, second = compile_uiux(_request()), compile_uiux(_request())
    assert first.spec_hash == second.spec_hash
    assert first.design_genome.genome_hash == second.design_genome.genome_hash
    assert first.model_dump() == second.model_dump()


def test_genome_tracks_brand_tone():
    warm = compile_uiux(_request(surface="LANDING_PAGE", brand=_brand(tone_attributes=["warm", "friendly"])))
    assert warm.selected_direction.startswith("Editorial Warmth")
    rejected = [t for t in warm.territories if not t.selected]
    assert rejected and all(t.rejection_reason for t in rejected)


# --------------------------------------------------------------------------- #
# Engines and repair
# --------------------------------------------------------------------------- #


def test_anti_generic_challenges_unjustified_motifs_and_generic_copy():
    ir = compile_uiux(_request(
        surface="LANDING_PAGE",
        purpose="Supercharge your workflow with our seamless platform",
        content_requirements=["purple gradient hero with glow", "customer testimonials"],
    ))
    messages = [f.message for f in ir.evaluation if f.engine is EvaluationEngine.anti_generic]
    assert any("purple gradient" in m for m in messages)
    assert any("supercharge" in m for m in messages)
    assert any("testimonials" in rule and "sourced" in rule for rule in ir.design_system.content_rules)


def test_anti_generic_respects_an_explicit_brand_justification():
    ir = compile_uiux(_request(
        surface="LANDING_PAGE",
        content_requirements=["gradient hero"],
        constraints=["brand required gradient from the approved guidelines"],
    ))
    assert not [f for f in ir.evaluation if f.engine is EvaluationEngine.anti_generic and "gradient" in f.message]


def test_interaction_debt_is_repaired_or_escalated_never_invented():
    ir = compile_uiux(_request(content_requirements=["drag cards between columns"]))
    nonstandard = [i for i in ir.interactions if not i.standard]
    assert nonstandard and nonstandard[0].fallback and "KEYBOARD" in nonstandard[0].input_modes
    assert nonstandard[0].justification is None  # the compiler cannot invent user value
    assert ir.terminal is UIUXTerminal.requires_approval
    assert any(item.startswith("DECISION: justify") for item in ir.approval_required)
    assert 1 <= ir.repair_iterations <= MAX_REPAIR_ITERATIONS


def test_complete_state_matrix_with_non_color_channels():
    assert set(_STATE_TABLE) == set(UIState)
    status_like = {UIState.error, UIState.invalid, UIState.degraded, UIState.offline,
                   UIState.unavailable, UIState.pending_approval, UIState.focus_visible, UIState.disabled}
    ir = compile_uiux(_request(surface="DASHBOARD"))
    for state in ir.states:
        if state.state in status_like:
            assert state.non_color_channel, state
    # State entropy: materially different states never look identical.
    pairs = {(row[1], row[2]) for row in _STATE_TABLE.values()}
    assert len(pairs) == len(_STATE_TABLE)


def test_counterfactuals_are_designed_for():
    ir = compile_uiux(_request(surface="AI_INTERFACE"))
    by_component = {c.name: set(c.states) for c in ir.components}
    assert {UIState.unavailable, UIState.degraded, UIState.streaming} <= by_component["AITrustEnvelope"]
    assert {UIState.empty, UIState.offline, UIState.loading} <= by_component["MessageList"]
    assert all("KEYBOARD" in i.input_modes for i in ir.interactions)
    assert any("reduced-motion" in rule for rule in ir.design_system.motion_rules)


def test_responsive_rules_transform_representation():
    ir = compile_uiux(_request(surface="DASHBOARD"))
    regions = {r.id: r for s in ir.screens for r in s.regions}
    assert len(ir.responsive_rules) == len(regions)
    assert regions["table"].responsive_transform.value == "SCROLL"
    assert regions["filters"].responsive_transform.value in {"WRAP", "DRAWER"}


def test_salience_budget_keeps_p3_below_p0():
    for surface in ("LANDING_PAGE", "AI_INTERFACE"):
        for screen in compile_uiux(_request(surface=surface)).screens:
            p0 = max(r.emphasis for r in screen.regions if r.priority.value == "P0")
            assert all(r.emphasis < p0 for r in screen.regions if r.priority.value == "P3")


def test_every_screen_is_fully_traceable():
    ir = compile_uiux(_request(surface="FORM_FLOW"))
    names = {c.name for c in ir.components}
    for screen in ir.screens:
        assert set(screen.components) <= names
        assert all(value for value in screen.trace.model_dump().values())


# --------------------------------------------------------------------------- #
# Truthfulness: metrics, accessibility, tokens
# --------------------------------------------------------------------------- #


def test_metrics_are_never_claimed_as_measured():
    ir = compile_uiux(_request(surface="DASHBOARD"))
    assert ir.performance.budgets and all(m.truth is MetricTruth.not_measured for m in ir.performance.budgets)
    with pytest.raises(ValidationError, match="MEASURED metric requires"):
        Metric(name="x", target="y", truth=MetricTruth.measured, source="s", formula="f",
               freshness="f", uncertainty="u", fallback="f")


def test_wcag_is_normative_and_apca_advisory():
    assert wcag_contrast_ratio("#ffffff", "#000000") == 21.0
    assert wcag_contrast_ratio("#777777", "#ffffff") == 4.48  # just below AA
    ir = compile_uiux(_request())
    for check in ir.tokens.contrast:
        threshold = {"AAA_NORMAL": 7.0, "AA_NORMAL": 4.5, "AA_LARGE": 3.0, "NON_TEXT": 3.0}[check.wcag_requirement.value]
        assert check.passes is (check.wcag_ratio >= threshold)  # pass/fail from WCAG only
        assert "advisory" in check.apca_note and "not WCAG" in check.apca_note
    # Published APCA-W3 0.0.98G reference values (advisory analysis only).
    assert apca_lc("#000000", "#ffffff") == pytest.approx(106.0, abs=0.1)
    assert apca_lc("#ffffff", "#000000") == pytest.approx(-107.9, abs=0.1)
    only_static = {r.verification.value for r in ir.accessibility.requirements if "1.4.3" in r.criterion}
    assert only_static == {"VERIFIED_STATIC"}
    assert any(r.verification.value == "REQUIRES_ASSISTIVE_TECH" for r in ir.accessibility.requirements)


def test_tokens_are_tiered_dtcg_and_brand_accent_passes_non_text_contrast():
    ir = compile_uiux(_request())
    assert ir.tokens.format == "DTCG 2025.10"
    assert "--ui-semantic-color-accent: var(--ui-primitive-color-accent-base);" in ir.tokens.css
    accent = next(c for c in ir.tokens.contrast if c.foreground == "semantic.color.focus-ring")
    assert accent.passes


def test_unresolvable_palette_falls_back_visibly():
    ir = compile_uiux(_request(brand=_brand(palette_hex=["#fafafa", "not-a-color"])))
    assert "baseline accent" in ir.tokens.palette_resolution


def test_schema_rejects_unknown_fields_and_generated_terminals():
    with pytest.raises(ValidationError):
        UIUXRequest(project_ref="x", surprise=True)
    payload = compile_uiux(_request()).model_dump(mode="json")
    with pytest.raises(ValidationError):
        UIUXDesignIR.model_validate({**payload, "terminal": "UI_GENERATED"})
    with pytest.raises(ValidationError):
        UIUXDesignIR.model_validate({**payload, "extra": 1})


def test_shared_zod_fixture_matches_the_compiler():
    """packages/shared/tests/uiux.test.ts parses this fixture with the Zod twin;
    this test proves the fixture is exactly what the compiler emits today."""
    expected = json.loads(compile_uiux(_fixture_request()).model_dump_json())
    assert json.loads(FIXTURE.read_text()) == expected, (
        "UIUX IR changed: regenerate packages/shared/tests/fixtures/uiux-design-ir.json "
        "and update packages/shared/src/schemas/uiux.ts to match"
    )


# --------------------------------------------------------------------------- #
# Prompt compiler integration
# --------------------------------------------------------------------------- #


def _ui_prompt_request() -> PromptCompilerRequest:
    base = load_request(str(ROOT / "sample_prompt_request.json"))
    ui = AssetRequirement(
        asset_id="ops-dashboard", family=PromptFamily.ui_ux, asset_type="dashboard",
        objective="Let operators triage incidents fast", audience="On-call operators",
        channel="web app", destination="product", content_requirements=["incident table", "status filters"],
    )
    return base.model_copy(update={"asset_requirements": [*base.asset_requirements, ui]})


def test_ui_ux_family_packages_carry_the_compiled_spec():
    result = compile_prompt_packages(_ui_prompt_request())
    assert result.final_state is CompilerState.prompt_package_ready
    package = next(p for p in result.prompt_packages if p.asset_spec.family is PromptFamily.ui_ux)
    spec = package.ui_ux_design
    assert spec is not None and spec.mode.value == "DASHBOARD"
    assert spec.spec_hash in package.generic_master_prompt
    assert "## UI/UX design specification (compiled)" in package.generic_master_prompt
    assert spec.spec_hash in package.prompt_ir.provenance_refs
    assert any("UI/UX compiler" in d for d in package.prompt_ir.accessibility_directives)
    assert any(section.startswith("pg.ui_ux.core:") for section in package.context_manifest.included_guidance)
    assert "UI_UX_SPEC" in package.validation.checked_dimensions
    assert package.terminal_state == "PROMPT_PACKAGE_READY"


def test_non_ui_families_are_unchanged():
    result = compile_prompt_packages(_ui_prompt_request())
    image = next(p for p in result.prompt_packages if p.asset_spec.family is PromptFamily.image)
    assert image.ui_ux_design is None
    assert "UI/UX" not in image.generic_master_prompt
    assert "UI_UX_SPEC" not in image.validation.checked_dimensions
    assert not any(s.startswith("pg.ui_ux.core") for s in image.context_manifest.included_guidance)
    # Byte-identical serialized prompt to the pre-UI/UX compiler for the sample asset.
    assert image.prompt_hash == "66cdd5cdb25be8e43c2d609de3ffce9da307e5510efc4c8e915381fbc7bb5eb8"


def test_a_blocked_ui_spec_blocks_the_package(monkeypatch):
    import services.langgraph.agency.prompt_compiler as pc

    real = pc.compile_uiux

    def blocked(request):
        return real(request).model_copy(update={"terminal": UIUXTerminal.blocked})

    monkeypatch.setattr(pc, "compile_uiux", blocked)
    result = compile_prompt_packages(_ui_prompt_request())
    package = next(p for p in result.prompt_packages if p.asset_spec.family is PromptFamily.ui_ux)
    assert package.validation.status is PromptValidationStatus.blocked
    assert result.final_state is CompilerState.blocked


# --------------------------------------------------------------------------- #
# Runtime seam: design_brief
# --------------------------------------------------------------------------- #


def _run(**brief_overrides):
    from services.langgraph.graph.models import AgentRun

    brief = {"brand_name": "Northwind Coffee", "goals": ["Grow awareness"], "target_audience": "Urban professionals",
             "tone": "warm and confident", "channels": ["instagram", "email"], "constraints": ["No health claims"]}
    brief.update(brief_overrides)
    now = datetime.utcnow()
    return AgentRun(id=uuid4(), tenant_id="tenant-uiux", project_id="proj-uiux", status="running",
                    created_at=now, updated_at=now, metadata={"input_data": {"brief": brief}})


def _invoke(run):
    from services.langgraph.graph.agency.build import build_agency_workflow

    graph = build_agency_workflow()
    config = {"configurable": {"thread_id": str(run.id)}}
    state = graph.invoke({"run": run, "current_node": "start", "messages": [], "extracted_data": {},
                          "validation_status": "pending"}, config=config)
    return graph, config, state


def test_non_ui_brief_design_brief_is_unchanged():
    _, _, state = _invoke(_run())
    agency = state["extracted_data"]["agency"]
    assert agency["design_brief"]["ui_ux"] is None
    assert agency["ui_ux_compilation"]["status"] == "SKIPPED"
    recipes = [d["path"] for d in agency["campaign_package"]["design_system"]["asset_recipes"]]
    assert not any("ui-ux" in path for path in recipes)


def test_ui_brief_compiles_a_spec_and_keeps_degraded_and_hitl_semantics():
    graph, config, state = _invoke(_run(product_type="app", business_idea="Booking app for independent barbers",
                                        workflow_idea="Book a haircut slot in under a minute"))
    agency = state["extracted_data"]["agency"]
    spec = UIUXDesignIR.model_validate(agency["design_brief"]["ui_ux"])
    assert agency["ui_ux_compilation"] == {"status": spec.terminal.value, "spec_hash": spec.spec_hash, "mode": spec.mode.value}
    # No provider key in tests -> degraded upstream; the spec says so and lowers confidence.
    assert any(s.detail == "FALLBACK_DEGRADED" for s in spec.sources)
    assert "derived from degraded (fallback) upstream output" in spec.confidence.basis
    assert agency.get("degraded") is True
    assert agency["qa_report"]["release_blocked"] is True  # release semantics unchanged
    # HITL unchanged: the graph still pauses before delivery.
    assert state["current_node"] == "hitl_gate"
    assert graph.get_state(config).next == ("delivery",)
    recipes = {d["path"] for d in agency["campaign_package"]["design_system"]["asset_recipes"]}
    assert {"branding/design-system/ui-ux/design-spec.json", "branding/design-system/ui-ux/tokens.css"} <= recipes


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_prints_by_default_and_writes_only_on_request(tmp_path, capsys):
    from services.langgraph.agency.cli import main

    sample = str(ROOT / "sample_ui_ux_request.json")
    assert main(["ui-ux", "--input", sample]) == 0
    assert "UIUX_SPEC_READY" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []

    spec_path, css_path = tmp_path / "spec.json", tmp_path / "tokens.css"
    assert main(["ui-ux", "--input", sample, "--output", str(spec_path), "--css", str(css_path)]) == 0
    written = UIUXDesignIR.model_validate_json(spec_path.read_text())
    assert css_path.read_text() == written.tokens.css
    assert main(["ui-ux", "--input", str(tmp_path / "missing.json")]) == 2
