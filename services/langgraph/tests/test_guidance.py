from __future__ import annotations

import json

import pytest

from services.langgraph.agency.guidance import GuidanceOverride, default_registry, route_guidance
from services.langgraph.agency.guidance.registry import GuidanceRegistry
from services.langgraph.agency.prompt_compiler import (
    AssetRequirement,
    CompilerState,
    PromptCompilerRequest,
    PromptFamily,
    compile_prompt_packages,
)


def _brand_core() -> dict:
    return {
        "brand_name": "Northwind Coffee",
        "positioning_essence": "Coffee for deliberate mornings.",
        "voice": {
            "tone_attributes": ["confident", "warm", "direct"],
            "writing_dos": ["Use concrete language."],
            "writing_donts": ["Avoid hype."],
        },
        "color_story": [
            {
                "role": "primary",
                "description": "Deep indigo authority color.",
                "reference_hex": "#1a2b4c",
            },
            {
                "role": "accent",
                "description": "Warm amber emphasis color.",
                "reference_hex": "#e08a2c",
            },
        ],
        "typography_direction": "Humanist serif display with neutral grotesk body.",
        "imagery_style": "Natural light, tactile materials, documentary framing.",
        "motion": {
            "pace": "Brisk with confident deceleration.",
            "emphasis_moments": ["primary CTA activation"],
            "reduced_motion_fallback": "Cross-fade only.",
        },
        "logo_lockups": [
            {
                "lockup_id": "primary",
                "lockup_type": "primary",
                "usage_context": "Default digital and print mark.",
                "minimum_size": "24px digital / 0.5in print",
                "clear_space_rule": "One cap-height around the mark.",
                "placement_notes": "Prefer top-left digitally.",
                "generation_reference": "Indigo wordmark with compact compass symbol.",
            }
        ],
    }


def _requirement(**overrides) -> AssetRequirement:
    payload = {
        "asset_id": "homepage-hero",
        "family": PromptFamily.image,
        "asset_type": "homepage hero image",
        "objective": "Create a documentary-style branded hero image for a marketing website.",
        "audience": "Busy professionals who value a deliberate morning ritual.",
        "channel": "web",
        "destination": "/",
        "content_requirements": ["Show a ceramic coffee cup in natural morning light."],
        "negative_constraints": ["No visible text."],
        "quality_constraints": ["Readable focal hierarchy."],
        "production": {"width": 1600, "height": 900, "format": "webp"},
    }
    payload.update(overrides)
    return AssetRequirement.model_validate(payload)


def test_default_registry_loads_branding_pack_and_has_stable_hash():
    first = default_registry()
    second = default_registry()
    assert [pack.id for pack in first.packs] == ["pg.branding.core"]
    assert first.registry_hash == second.registry_hash
    assert first.get("pg.branding.core").content_hash


def test_registry_rejects_duplicate_json_yaml_keys(tmp_path):
    pack = tmp_path / "bad.yaml"
    pack.write_text('{"id":"one","id":"two"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate guidance key"):
        GuidanceRegistry.from_directory(tmp_path)


def test_routing_is_deterministic_and_selective():
    registry = default_registry()
    requirement = _requirement()
    first = route_guidance(requirement, registry)
    second = route_guidance(requirement, registry)

    assert first.guidance_hash == second.guidance_hash
    assert first.selected_pack_ids == ["pg.branding.core"]
    assert first.selected_section_ids
    assert any("brand.creative_direction" in item for item in first.selected_section_ids)
    assert all("brand.naming" not in item for item in first.selected_section_ids)


def test_explicit_pack_exclusion_wins_over_relevance():
    selection = route_guidance(
        _requirement(),
        default_registry(),
        GuidanceOverride(exclude=["pg.branding.core"]),
    )
    assert selection.selected_pack_ids == []
    assert "pg.branding.core" in selection.rejected_pack_ids
    assert selection.guidance_context == {}


def test_naming_task_activates_naming_guidance():
    requirement = _requirement(
        family=PromptFamily.copy,
        asset_type="brand naming",
        objective="Develop a strategically grounded brand name.",
        channel="brand",
    )
    selection = route_guidance(requirement, default_registry())
    assert any("brand.naming" in item for item in selection.selected_section_ids)


def test_compiler_injects_guidance_without_mutating_canonical_brand_or_firewall():
    request = PromptCompilerRequest.model_validate(
        {
            "project_name": "Northwind launch",
            "brand_core": _brand_core(),
            "asset_requirements": [_requirement().model_dump(mode="json")],
        }
    )
    result = compile_prompt_packages(request)

    assert result.final_state is CompilerState.prompt_package_ready
    package = result.prompt_packages[0]
    assert package.terminal_state == "PROMPT_PACKAGE_READY"
    assert package.handoff_only is True
    assert package.context_manifest.guidance_hash
    assert package.context_manifest.included_guidance
    assert "Selected advisory" in package.generic_master_prompt
    assert "Coffee for deliberate mornings." in package.generic_master_prompt
    assert package.asset_spec.brand_hash == package.brand_hash


def test_guidance_hash_participates_in_prompt_provenance():
    request = PromptCompilerRequest.model_validate(
        {
            "project_name": "Northwind launch",
            "brand_core": _brand_core(),
            "asset_requirements": [_requirement().model_dump(mode="json")],
        }
    )
    package = compile_prompt_packages(request).prompt_packages[0]
    assert package.context_manifest.guidance_hash in package.prompt_ir.provenance_refs


def test_request_can_disable_guidance_without_breaking_prompt_compilation():
    requirement = _requirement(
        guidance_overrides={"exclude": ["pg.branding.core"]}
    )
    request = PromptCompilerRequest.model_validate(
        {
            "project_name": "Northwind launch",
            "brand_core": _brand_core(),
            "asset_requirements": [requirement.model_dump(mode="json")],
        }
    )
    result = compile_prompt_packages(request)
    package = result.prompt_packages[0]
    assert result.final_state is CompilerState.prompt_package_ready
    assert package.context_manifest.included_guidance == []
    assert package.context_manifest.guidance_context == {}
