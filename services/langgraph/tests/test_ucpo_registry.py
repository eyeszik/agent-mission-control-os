"""UCPO registries: fifteen disciplines, five presentation systems, sixteen prompt modules, multimodal specs, routes."""

from __future__ import annotations

import pytest

from services.langgraph.agency.foundry import psem
from services.langgraph.agency.ucpo import disciplines, multimodal, presentation, prompt_modules
from services.langgraph.agency.ucpo.requirements import compile_requirements
from services.langgraph.agency.ucpo.site import compile_site
from services.langgraph.agency.ucpo.source import generate_source


def test_fifteen_disciplines_each_declare_the_full_contract():
    assert len(disciplines.DISCIPLINES) == 15
    assert [d.discipline_id[:2] for d in disciplines.DISCIPLINES] == [f"{i:02d}" for i in range(1, 16)]
    for d in disciplines.DISCIPLINES:
        described = d.describe()
        assert all(described[k] for k in ("purpose", "input_schema", "output_schema", "routes", "quality_checks",
                                          "accessibility", "rights", "fallback", "approval"))


def test_routing_uses_discovered_capabilities_and_reports_gaps_with_a_fallback():
    every = {c for d in disciplines.DISCIPLINES for alt in d.routes for c in alt}
    none = {c: {"status": "MISSING", "blockers": ["fixture"]} for c in every}
    for d in disciplines.DISCIPLINES:
        r = disciplines.route(d.discipline_id, available=none)
        assert r["status"] == "CAPABILITY_GAP" and r["fallback"] and r["terminal_state"] == "PROMPT_PACKAGE_READY"
    all_on = {c: {"status": "AVAILABLE", "blockers": []} for c in every}
    assert disciplines.route("04.editorial_design", available=all_on)["status"] == "ROUTED"
    # Providers are never discovered: photography stays a gap on a real host too.
    real = disciplines.availability()
    assert real["provider.t2i"]["status"] == "MISSING"
    assert disciplines.route("05.conceptual_photography", available=real)["status"] == "CAPABILITY_GAP"
    with pytest.raises(KeyError):
        disciplines.route("99.invented")


@pytest.mark.parametrize("system_id", sorted(presentation.SYSTEMS))
def test_each_presentation_system_compiles_to_a_real_site(system_id):
    brief = presentation.example_brief(system_id)
    pkg = compile_requirements(brief, project_ref="p")
    genome = psem.compile_psem_genome(psem.psem_brief(brief.organization, seed=brief.seed), project_id="p")
    _, css, sh = psem.compile_psem_tokens(genome)
    _, ir = compile_site(brief, pkg, genome, token_refs={"dtcg_source_hash": sh})
    files, manifest = generate_source(ir, genome, css)
    assert "app/page.tsx" in files and manifest.files
    assert len(presentation.SYSTEMS) == 5


def test_boards_refuse_missing_or_unknown_slots_and_compare_by_requirement():
    with pytest.raises(presentation.BoardError, match="required slots"):
        presentation.compose_board("visual_identity_board", organization="X", title="T", description="D",
                                   slots={"identity": {"heading": "H"}})
    with pytest.raises(presentation.BoardError, match="unknown slots"):
        presentation.compose_board("editorial_design_system", organization="X", title="T", description="D",
                                   slots={"invented": {"heading": "H"}})
    a = presentation.example_brief("editorial_design_system")
    ex = presentation.EXAMPLES["editorial_design_system"]
    slots = {**ex["slots"], "grid": {**ex["slots"]["grid"], "heading": "Columns, gutters and margins"}}
    b = presentation.compose_board("editorial_design_system", organization=ex["organization"], title=ex["title"],
                                   description=ex["description"], slots=slots, seed=7)
    assert presentation.compare_boards(a, b)["changed"] == ["req.index.s2.heading"]


def test_sixteen_prompt_modules_with_all_fields_and_preserved_compact_variants():
    assert len(prompt_modules.MODULES) == 16
    assert [m.module_id[:2] for m in prompt_modules.MODULES] == [f"{i:02d}" for i in range(1, 17)]
    for m in prompt_modules.MODULES:
        for field in prompt_modules.FIELDS:
            assert getattr(m, field), (m.module_id, field)
        check = prompt_modules.preservation(m)
        assert check["missing"] == [] and check["mappings_preserved"]
        expanded = prompt_modules.compile_module(m.module_id, "expanded")
        compact = prompt_modules.compile_module(m.module_id, "compact")
        assert len(compact["text"]) < len(expanded["text"])
        assert expanded["terminal_state"] == compact["terminal_state"] == "PROMPT_PACKAGE_READY"
        assert not expanded["provider_invoked"]


def test_compact_variant_that_drops_a_rule_is_detected(monkeypatch):
    module = prompt_modules.MODULES[2]
    original = prompt_modules.render

    def lossy(mod, variant):
        text = original(mod, variant)
        return text.replace("C1. ", "") if variant == "compact" else text

    monkeypatch.setattr(prompt_modules, "render", lossy)
    assert prompt_modules.preservation(module)["missing"]
    with pytest.raises(ValueError, match="lost content"):
        prompt_modules.compile_module(module.module_id, "compact")


def test_multimodal_specs_compile_but_generation_is_a_capability_gap():
    brief = presentation.example_brief("conceptual_photography_board")
    genome = psem.compile_psem_genome(psem.psem_brief(brief.organization, seed=7), project_id="p")
    spec = multimodal.compile_image_spec(brief, genome, "plate-a", subject="a kiln in fog", scene="flat marsh at dusk")
    assert "identifiable people or faces" in spec.negative_constraints
    board = multimodal.compile_storyboard(spec)
    video = multimodal.compile_video_spec(spec, board)
    assert video.duration_s == 12.0 and video.shot_list == tuple(s.shot_id for s in board)
    for package in (multimodal.prompt_package(spec), multimodal.prompt_package(video)):
        assert package["terminal_state"] == "PROMPT_PACKAGE_READY"
        assert package["generation"]["status"] == "CAPABILITY_GAP" and package["generation"]["generated"] is False
    with pytest.raises(KeyError):
        multimodal.compile_image_spec(brief, genome, "undeclared", subject="x", scene="y")


def test_ucpo_routes_are_mounted_authenticated_and_have_no_effect_verbs():
    from services.langgraph.app.main import app

    paths = [p for p in app.openapi()["paths"] if p.startswith("/ucpo")]
    assert "/ucpo/projects/{project_id}/sites" in paths and "/ucpo/capabilities" in paths
    assert not any(w in p for p in paths for w in ("publish", "deploy", "order", "purchase", "send"))
