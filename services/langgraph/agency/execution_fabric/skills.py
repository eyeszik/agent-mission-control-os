"""Domain skills, providers and validators the fabric can dispatch.

Skills are registered in the canonical dispatcher (``agency.skills.dispatcher``)
with the N3 capability that gates them; the fabric always invokes them through
``dispatch_skill``, so capability authorization is never re-implemented here.

Providers are declared, not assumed. A provider that has no adapter in this
repository is ``installed=False`` and yields PROVIDER_GAP; one that is
installed but not reachable yields BLOCKED_PROVIDER; a missing local binary
yields BLOCKED_TOOL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from services.langgraph.agency.kernel.ontology import ArtifactType, Capability
from services.langgraph.agency.skills.dispatcher import Skill, register_skill
from services.langgraph.integrations.zo import zo_available

from .adapters import brand, cinematic, code_sandbox, seo, uiux
from .verifiers import Verdict


@dataclass(frozen=True)
class Provider:
    name: str
    kind: Literal["PROVIDER", "LOCAL_TOOL"]
    installed: bool
    availability: Callable[[], bool] | None = None
    note: str = ""


PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (
        Provider("llm_drafting", "PROVIDER", False, note=(
            "No reviewed adapter drafts arbitrary N1 artifacts from the fabric. Layer 1's generate_structured "
            "is bound to its own node schemas and is not reused for unreviewed artifact types.")),
        Provider("t2i", "PROVIDER", False, note="No text-to-image provider adapter is installed."),
        Provider("ai_video", "PROVIDER", False, note="No AI video provider adapter is installed."),
        Provider("search_volume", "PROVIDER", False, note="No search-data provider is installed."),
        Provider("zo", "PROVIDER", True, zo_available, note="integrations/zo.py, AMC_ZO_MODE-gated."),
        Provider("ffprobe", "LOCAL_TOOL", True, cinematic.ffprobe_available, note="FFmpeg's ffprobe, local binary."),
    )
}

# Sentinel the SEO domain uses verbatim for missing search demand data.
_GAP_CODES = {"search_volume": "GAP_NO_SEARCH_PROVIDER"}


def provider_blocker(name: str | None) -> str | None:
    if name is None:
        return None
    provider = PROVIDERS.get(name)
    if provider is None or not provider.installed:
        return _GAP_CODES.get(name, f"PROVIDER_GAP:{name}")
    if provider.availability is not None and not provider.availability():
        return f"{'TOOL_UNAVAILABLE' if provider.kind == 'LOCAL_TOOL' else 'PROVIDER_UNAVAILABLE'}:{name}"
    return None


def sandbox_blocker(requirement: str) -> str | None:
    if requirement == "NETWORK_ISOLATED" and not code_sandbox.network_namespace_available():
        return "SANDBOX_UNAVAILABLE:NETWORK_ISOLATED"
    return None


Validator = Callable[[dict[str, Any], dict[str, Any]], Verdict]
VALIDATORS: dict[str, Validator] = {
    "svg_safety": brand.validate_svg,
    "palette_delta_e": brand.validate_palette,
    "dtcg_recompile": brand.validate_dtcg,
    "wcag_contrast_aa": uiux.validate_contrast,
    "report_wellformed": uiux.validate_report,
    "seo_no_fabricated_demand": seo.validate_no_fabricated_demand,
    "sandbox_commands_passed": code_sandbox.validate_commands_passed,
    "video_render_checks": cinematic.validate_render,
}


@dataclass(frozen=True)
class SkillSpec:
    skill: Skill
    produces: ArtifactType


def _spec(skill_id, capability, produces, handler, description, **meta) -> SkillSpec:
    return SkillSpec(Skill(skill_id=skill_id, capability=capability, description=description, handler=handler, **meta), produces)


FABRIC_SKILLS: dict[str, SkillSpec] = {
    s.skill.skill_id: s
    for s in (
        _spec("brand_logo_svg", Capability.art_direction, ArtifactType.media_asset, brand.brand_logo_svg,
              "Deterministic SVG mark from the brand capsule (agency.assets.render_logo_svg).",
              side_effect_class="DRAFT", validator_ids=("svg_safety", "palette_delta_e"), timeout_class="FAST"),
        _spec("dtcg_token_compile", Capability.art_direction, ArtifactType.design_token_set, brand.dtcg_token_compile,
              "Tiered DTCG token set compiled by agency.design_tokens.",
              side_effect_class="DRAFT", validator_ids=("dtcg_recompile", "palette_delta_e"), timeout_class="FAST"),
        _spec("t2i_image_generate", Capability.art_direction, ArtifactType.media_asset, brand.text_to_image,
              "Text-to-image render (no provider installed).",
              side_effect_class="DRAFT", provider_requirement="t2i", timeout_class="LONG"),
        _spec("design_system_spec_compile", Capability.art_direction, ArtifactType.design_system_spec, uiux.design_system_spec,
              "Colour pairs with WCAG 2.2 verdicts plus a DOM-audited preview.",
              side_effect_class="DRAFT", validator_ids=("wcag_contrast_aa",), timeout_class="FAST"),
        _spec("uiux_dom_audit", Capability.brand_safety_review, ArtifactType.qa_report, uiux.uiux_dom_audit,
              "Headless DOM audit (contrast, viewport, lang, alt, target size, reflow).",
              side_effect_class="DRAFT", validator_ids=("report_wellformed",), timeout_class="FAST"),
        _spec("seo_audit", Capability.brand_safety_review, ArtifactType.qa_report, seo.seo_audit,
              "Deterministic on-page SEO checks over a supplied page set.",
              side_effect_class="DRAFT", validator_ids=("report_wellformed", "seo_no_fabricated_demand"), timeout_class="FAST"),
        _spec("seo_search_volume", Capability.brand_safety_review, ArtifactType.qa_report, seo.search_volume,
              "Search demand data (no provider installed).",
              side_effect_class="DRAFT", provider_requirement="search_volume"),
        _spec("code_patch_sandbox", Capability.implementation, ArtifactType.implementation_plan, code_sandbox.code_patch_sandbox,
              "Validate a Python patch in an isolated scratch copy; never applied to the repository.",
              side_effect_class="DRAFT", sandbox_requirement="NETWORK_ISOLATED",
              validator_ids=("sandbox_commands_passed",), timeout_class="LONG"),
        _spec("fvf_ingest_verify", Capability.art_direction, ArtifactType.media_asset, cinematic.fvf_ingest_verify,
              "Ingest a FreeVideoForge render and verify it with ffprobe.",
              side_effect_class="DRAFT", provider_requirement="ffprobe", sandbox_requirement="PROCESS",
              validator_ids=("video_render_checks",), timeout_class="LONG"),
        _spec("ai_video_generate", Capability.art_direction, ArtifactType.media_asset, cinematic.ai_video,
              "AI video generation (no provider installed).",
              side_effect_class="DRAFT", provider_requirement="ai_video", timeout_class="LONG"),
    )
}

for _s in FABRIC_SKILLS.values():
    register_skill(_s.skill)

# Default skill per artifact contract. Anything else that needs authored
# content has no installed generator and reports PROVIDER_GAP:llm_drafting.
ARTIFACT_SKILLS: dict[str, str] = {
    ArtifactType.design_token_set.value: "dtcg_token_compile",
    ArtifactType.design_system_spec.value: "design_system_spec_compile",
    ArtifactType.media_asset.value: "brand_logo_svg",
}
# A release record is a human decision, never a skill output.
HUMAN_ONLY_ARTIFACTS = frozenset({ArtifactType.release_record.value})


def skill_binding_blockers(artifact_type: str | None, skill_id: str | None) -> tuple[str, ...]:
    if artifact_type in HUMAN_ONLY_ARTIFACTS:
        return ("APPROVAL_RELEASE_IS_HUMAN_ONLY",)
    if skill_id is None:
        return ("PROVIDER_GAP:llm_drafting",)
    spec = FABRIC_SKILLS.get(skill_id)
    if spec is None:
        return (f"NO_SKILL_FOR_CONTRACT:{artifact_type}",)
    if artifact_type is not None and spec.produces.value != artifact_type:
        return (f"CONTRACT_SKILL_OUTPUT_MISMATCH:{skill_id}->{spec.produces.value}!={artifact_type}",)
    return ()


__all__ = [
    "ARTIFACT_SKILLS",
    "FABRIC_SKILLS",
    "HUMAN_ONLY_ARTIFACTS",
    "PROVIDERS",
    "Provider",
    "SkillSpec",
    "VALIDATORS",
    "provider_blocker",
    "sandbox_blocker",
    "skill_binding_blockers",
]
