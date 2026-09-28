"""Source-spec functional roles mapped onto the sealed RoleOS registry.

The v10 specification names 26 functional responsibilities. They are *not* new
runtime roles: each maps to an existing sealed RoleOS skill (exact, or the
nearest equivalent where the registry has no identically named role). Role
identity grants nothing -- no publication, spend, secret or approval authority.
RoleOS contracts and N3 remain the only permission sources.
"""

from __future__ import annotations

from dataclasses import dataclass

from services.langgraph.agency.prompt_compiler import PromptFamily

from .models import ProductionMedium


@dataclass(frozen=True)
class FunctionalRoleBinding:
    functional_role: str
    skill_name: str
    department: str
    match: str  # EXACT | NEAREST_EQUIVALENT


FUNCTIONAL_ROLE_BINDINGS: dict[str, FunctionalRoleBinding] = {
    b.functional_role: b
    for b in (
        FunctionalRoleBinding("brand_strategist", "brand-strategist", "brand", "EXACT"),
        FunctionalRoleBinding("verbal_identity_architect", "verbal-identity-strategist", "brand", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("messaging_architect", "brand-narrative-strategist", "brand", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("copywriter", "copywriter", "creative", "EXACT"),
        FunctionalRoleBinding("editor", "copy-editor", "creative", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("UX_writer", "ux-writer", "creative", "EXACT"),
        FunctionalRoleBinding("content_designer", "information-architect", "experience-product", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("content_strategist", "content-strategist", "marketing", "EXACT"),
        FunctionalRoleBinding("research_editor", "research-manager", "strategy", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("SEO_strategist", "seo-strategist", "search-social", "EXACT"),
        FunctionalRoleBinding("creative_director", "creative-director", "creative", "EXACT"),
        FunctionalRoleBinding("art_director", "art-director", "creative", "EXACT"),
        FunctionalRoleBinding("visual_identity_designer", "brand-identity-designer", "creative", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("graphic_designer", "graphic-designer", "creative", "EXACT"),
        FunctionalRoleBinding("production_designer", "production-designer", "creative", "EXACT"),
        FunctionalRoleBinding("environmental_signage_designer", "environmental-graphic-designer", "creative", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("motion_director", "motion-design-director", "production", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("storyboard_artist", "storyboard-artist", "creative", "EXACT"),
        FunctionalRoleBinding("cinematographer", "cinematographer", "production", "EXACT"),
        FunctionalRoleBinding("video_prompt_engineer", "prompt-engineer", "ai-data", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("image_prompt_engineer", "prompt-designer", "ai-data", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("prompt_system_architect", "prompt-architect", "ai-data", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("brand_guardian", "brand-governance-manager", "brand", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("accessibility_reviewer", "accessibility-qa-analyst", "technology", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("rights_claims_reviewer", "rights-and-clearances-manager", "operations", "NEAREST_EQUIVALENT"),
        FunctionalRoleBinding("analytics_experiment_lead", "experimentation-lead", "growth-media", "NEAREST_EQUIVALENT"),
    )
}

_BY_FAMILY: dict[PromptFamily, tuple[str, ...]] = {
    PromptFamily.copy: ("copywriter", "editor"),
    PromptFamily.image: ("art_director", "image_prompt_engineer"),
    PromptFamily.print: ("graphic_designer", "production_designer"),
    PromptFamily.presentation: ("graphic_designer",),
    PromptFamily.video: ("cinematographer", "video_prompt_engineer"),
    PromptFamily.storyboard: ("storyboard_artist",),
    PromptFamily.motion: ("motion_director",),
    PromptFamily.ui_ux: ("UX_writer", "content_designer"),
}


def functional_roles_for(family: PromptFamily, medium: ProductionMedium) -> list[str]:
    """Responsibilities a family's work order should route to (always reviewed)."""
    roles = ["prompt_system_architect", *_BY_FAMILY[family]]
    if medium is ProductionMedium.signage:
        roles.append("environmental_signage_designer")
    elif medium in {ProductionMedium.print, ProductionMedium.merch}:
        roles.append("production_designer")
    roles += ["brand_guardian", "accessibility_reviewer", "rights_claims_reviewer"]
    return list(dict.fromkeys(roles))


def resolve_functional_roles(registry) -> dict[str, str | None]:
    """Resolve every functional role against the sealed RoleOS registry.

    Uses the compiled-agency AuthorityBridge's exact skill-name selection; a
    role with no sealed specialist resolves to ``None`` (a CAPABILITY_GAP),
    never to an invented role.
    """
    from services.langgraph.agency.compiled.authority import AuthorityBridge, SpecialistQuery

    bridge = AuthorityBridge(registry)
    return {
        name: bridge.resolve_specialist(SpecialistQuery(binding.skill_name, binding.department))
        for name, binding in sorted(FUNCTIONAL_ROLE_BINDINGS.items())
    }
