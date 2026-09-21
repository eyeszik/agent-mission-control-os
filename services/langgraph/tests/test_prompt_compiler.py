from __future__ import annotations

import json

from services.langgraph.agency.cli import main
from services.langgraph.agency.prompt_compiler import (
    AdapterStatus,
    AssetRequirement,
    ClaimSeed,
    ClaimType,
    CompilerState,
    PromptCompilerRequest,
    PromptFamily,
    ProviderCapability,
    ProviderCapabilityName,
    SourceClass,
    SourceEvidence,
    compile_prompt_packages,
    stable_hash,
)


def _brand_core() -> dict:
    return {
        "brand_name": "Northwind Coffee",
        "positioning_essence": "Coffee for people who take their mornings seriously.",
        "voice": {
            "tone_attributes": ["confident", "warm", "direct"],
            "writing_dos": ["Use short, concrete sentences."],
            "writing_donts": ["Do not use hype."],
        },
        "color_story": [
            {
                "role": "primary",
                "description": "Deep indigo used as the authority color.",
                "reference_hex": "#1a2b4c",
            },
            {
                "role": "accent",
                "description": "Warm amber used for emphasis.",
                "reference_hex": "#e08a2c",
            },
        ],
        "typography_direction": "Humanist serif headlines with a neutral grotesk body.",
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
                "clear_space_rule": "One cap-height around the full mark.",
                "placement_notes": "Prefer top-left on digital surfaces.",
                "generation_reference": "Indigo wordmark with a compact compass-needle symbol.",
            }
        ],
    }


def _requirement() -> AssetRequirement:
    return AssetRequirement(
        asset_id="homepage-hero",
        family=PromptFamily.image,
        asset_type="homepage hero image",
        objective="Create a documentary-style hero image that communicates disciplined mornings.",
        audience="Busy professionals who value a deliberate morning ritual.",
        channel="web",
        destination="/",
        content_requirements=["Show a ceramic coffee cup and natural morning light."],
        negative_constraints=["No visible text.", "No glossy studio treatment."],
        quality_constraints=["Readable focal hierarchy.", "Natural material texture."],
        production={"width": 1600, "height": 900, "format": "webp"},
    )


def _request(**overrides) -> PromptCompilerRequest:
    payload = {
        "project_name": "Northwind launch",
        "content": "The campaign should communicate disciplined, calm mornings.",
        "brand_core": _brand_core(),
        "asset_requirements": [_requirement().model_dump(mode="json")],
    }
    payload.update(overrides)
    return PromptCompilerRequest.model_validate(payload)


def test_compiler_stops_at_prompt_package_ready_and_never_returns_assets():
    result = compile_prompt_packages(_request())
    assert result.final_state is CompilerState.prompt_package_ready
    assert result.generation_firewall == "PROMPT_PACKAGE_READY"
    assert len(result.prompt_packages) == 1

    dumped = result.model_dump(mode="json")
    assert "rendered_assets" not in dumped
    assert "generated_assets" not in dumped
    assert dumped["prompt_packages"][0]["handoff_only"] is True
    assert dumped["prompt_packages"][0]["terminal_state"] == "PROMPT_PACKAGE_READY"


def test_missing_brand_core_fails_closed_before_prompt_compilation():
    request = _request(brand_core=None)
    result = compile_prompt_packages(request)
    assert result.final_state is CompilerState.brand_system_incomplete
    assert result.prompt_packages == []
    assert "brand" in result.completeness.blocking_domains


def test_missing_asset_requirements_blocks_without_inventing_deliverables():
    result = compile_prompt_packages(_request(asset_requirements=[]))
    assert result.final_state is CompilerState.blocked
    assert result.prompt_packages == []
    assert "[VOID_DETECTED:ASSET_REQUIREMENTS]" in result.voids


def test_high_risk_undocumented_api_claim_emits_research_request_and_blocks():
    result = compile_prompt_packages(
        _request(
            content="Provider X API guarantees 99.99% availability for every image generation request."
        )
    )
    assert result.final_state is CompilerState.research_incomplete
    assert result.research_requests
    assert any(gap.category.value == "UNDOCUMENTED_API" for gap in result.gaps)
    assert result.prompt_packages == []


def test_authoritative_evidence_can_resolve_a_blocking_claim_gap():
    request = _request(
        content="",
        claims=[
            ClaimSeed(
                text="Provider X API supports text-to-image generation.",
                claim_type=ClaimType.api_claim,
            )
        ],
    )
    first = compile_prompt_packages(request)
    claim_id = first.claims[0].claim_id

    resolved = _request(
        content="",
        claims=request.claims,
        evidence=[
            SourceEvidence(
                source_id="src-provider-docs",
                title="Provider X official API documentation",
                source_class=SourceClass.official,
                claim_ids=[claim_id],
                supports=True,
                uri="https://example.invalid/provider-docs",
                summary="Official documentation states that text-to-image is supported.",
            )
        ],
    )
    result = compile_prompt_packages(resolved)
    assert result.final_state is CompilerState.prompt_package_ready
    assert result.claims[0].status.value == "VERIFIED"


def test_unverified_provider_is_reported_but_never_treated_as_verified_adapter():
    provider = ProviderCapability(
        provider="ExampleAI",
        model="image-v1",
        verified=False,
        families=[PromptFamily.image],
        capabilities=[ProviderCapabilityName.text_to_image],
    )
    result = compile_prompt_packages(_request(providers=[provider]))
    variants = result.prompt_packages[0].provider_prompts
    assert len(variants) == 1
    assert variants[0].status is AdapterStatus.unverified


def test_verified_provider_with_missing_capability_is_blocked_without_fabrication():
    provider = ProviderCapability(
        provider="ExampleAI",
        model="text-only-v1",
        verified=True,
        source_ref="official-provider-docs",
        families=[PromptFamily.image],
        capabilities=[ProviderCapabilityName.structured_text],
    )
    result = compile_prompt_packages(_request(providers=[provider]))
    variant = result.prompt_packages[0].provider_prompts[0]
    assert variant.status is AdapterStatus.blocked
    assert variant.unsupported_requirements == ["TEXT_TO_IMAGE"]
    assert result.final_state is CompilerState.prompt_package_ready


def test_verified_compatible_provider_receives_generic_compatible_prompt_only():
    provider = ProviderCapability(
        provider="ExampleAI",
        model="image-v2",
        verified=True,
        source_ref="official-provider-docs",
        families=[PromptFamily.image],
        capabilities=[ProviderCapabilityName.text_to_image],
    )
    result = compile_prompt_packages(_request(providers=[provider]))
    variant = result.prompt_packages[0].provider_prompts[0]
    assert variant.status is AdapterStatus.generic_compatible
    assert variant.prompt == result.prompt_packages[0].generic_master_prompt


def test_prompt_and_context_hashes_are_deterministic():
    first = compile_prompt_packages(_request())
    second = compile_prompt_packages(_request())
    assert first.prompt_packages[0].prompt_hash == second.prompt_packages[0].prompt_hash
    assert first.prompt_packages[0].context_manifest.context_hash == second.prompt_packages[0].context_manifest.context_hash
    assert stable_hash(first.prompt_packages[0].asset_spec) == stable_hash(second.prompt_packages[0].asset_spec)


def test_selective_context_excludes_unneeded_motion_for_image_prompt():
    result = compile_prompt_packages(_request())
    context = result.prompt_packages[0].context_manifest
    assert context.included_domains == ["strategy", "visual"]
    assert "motion" in context.excluded_domains
    assert "motion" not in context.brand_context


def test_cli_compile_prompts_writes_machine_readable_result(tmp_path):
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "result.json"
    request_path.write_text(
        _request().model_dump_json(indent=2),
        encoding="utf-8",
    )

    code = main(
        [
            "compile-prompts",
            "--input",
            str(request_path),
            "--output",
            str(output_path),
        ]
    )

    assert code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["final_state"] == "PROMPT_PACKAGE_READY"
    assert payload["generation_firewall"] == "PROMPT_PACKAGE_READY"
    assert len(payload["prompt_packages"]) == 1


def test_cli_returns_nonzero_when_brand_is_incomplete(tmp_path):
    request = _request(brand_core=None)
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    code = main(["compile-prompts", "--input", str(request_path), "--json"])
    assert code == 1
