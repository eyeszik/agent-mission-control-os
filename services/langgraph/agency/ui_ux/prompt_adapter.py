"""Map a UIUXDesignIR onto prompt-compiler inputs.

Kept free of any import from ``agency.prompt_compiler`` so the dependency runs
one way (prompt_compiler -> ui_ux). The adapter selects the parts of the spec a
generation prompt needs; it never dumps the whole IR into every prompt.
"""

from __future__ import annotations

from typing import Any

from .models import BrandContext, SourceKind, SurfaceMode, UIUXDesignIR, UIUXRequest

_ASSET_TYPE_SURFACE = (
    (("landing", "homepage", "website", "marketing page", "microsite"), SurfaceMode.landing_page),
    (("dashboard", "analytics", "report"), SurfaceMode.dashboard),
    (("assistant", "chat", "copilot", "ai interface"), SurfaceMode.ai_interface),
    (("checkout", "signup", "onboarding", "form", "wizard"), SurfaceMode.form_flow),
    (("app", "application", "screen", "ui", "product", "tool", "portal"), SurfaceMode.application),
)


def surface_for_asset_type(asset_type: str) -> SurfaceMode | None:
    lowered = asset_type.lower()
    for words, mode in _ASSET_TYPE_SURFACE:
        if any(word in lowered for word in words):
            return mode
    return None


def brand_context_from_core(brand: Any) -> BrandContext:
    """Read (never write) the slice of canonical BrandCore the compiler needs.

    ``ColorRole.reference_hex`` is optional reference data on a qualitative
    color story; when every role lacks it, the palette stays unresolved rather
    than being guessed.
    """
    palette = [role.reference_hex for role in brand.color_story if getattr(role, "reference_hex", None)]
    return BrandContext(
        brand_name=brand.brand_name,
        positioning=brand.positioning_essence,
        tone_attributes=list(brand.voice.tone_attributes),
        typography_direction=brand.typography_direction,
        imagery_style=brand.imagery_style,
        motion_pace=brand.motion.pace,
        reduced_motion_fallback=brand.motion.reduced_motion_fallback,
        palette_hex=palette,
        palette_source=SourceKind.brand_core if palette else SourceKind.compiler_default,
    )


def request_from_asset_requirement(requirement: Any, brand: Any) -> UIUXRequest:
    return UIUXRequest(
        project_ref=requirement.asset_id,
        surface=surface_for_asset_type(requirement.asset_type),
        surface_hint=requirement.asset_type,
        purpose=requirement.objective,
        primary_user=requirement.audience,
        primary_task=requirement.objective,
        business_goal=requirement.business_reason or "",
        content_requirements=list(requirement.content_requirements),
        constraints=list(requirement.quality_constraints),
        negative_constraints=list(requirement.negative_constraints),
        brand=brand_context_from_core(brand),
    )


def directive_buckets(ir: UIUXDesignIR) -> dict[str, list[str]]:
    """Concise, deduplicated directives keyed by the prompt compiler's bucket names."""
    screens = [f"UI/UX compiler: {line}" for line in ir.generation_prompts]
    buckets: dict[str, list[str]] = {
        "composition": [
            f"UI/UX compiler: direction — {ir.selected_direction}",
            f"UI/UX compiler: genome hierarchy — {ir.design_genome.hierarchy}; density {ir.design_genome.density}",
            *screens,
        ],
        "interaction": [
            *(f"UI/UX compiler: {rule}" for rule in ir.design_system.patterns),
            *(f"UI/UX compiler: {i.component_ref} {i.trigger} via {', '.join(i.input_modes)}; feedback: {i.feedback}"
              + (f"; fallback: {i.fallback}" if i.fallback else "")
              for i in ir.interactions),
        ],
        "accessibility": [
            f"UI/UX compiler: {req.criterion} — {req.rule} [{req.verification.value}]"
            for req in ir.accessibility.requirements
        ],
        "tokens": [
            f"UI/UX compiler: tokens are DTCG 2025.10, tiers {'/'.join(ir.tokens.tiers)}, CSS prefix --{ir.tokens.css_prefix}-; "
            "consumers reference semantic/component tokens only.",
            f"UI/UX compiler: palette — {ir.tokens.palette_resolution}",
        ],
        "motion": [f"UI/UX compiler: {rule}" for rule in ir.design_system.motion_rules],
        "engineering": [
            *(f"UI/UX compiler: {rule}" for rule in ir.performance.requirements),
            *(f"UI/UX compiler: contract {c}" for c in ir.implementation_mapping.contracts),
        ],
        "quality": [
            *(f"UI/UX compiler: {rule}" for rule in ir.design_system.state_rules),
            *(f"UI/UX compiler: {rule}" for rule in ir.design_system.content_rules),
            *(f"UI/UX compiler: unresolved {f.engine.value} — {f.subject}: {f.message}"
              for f in ir.evaluation if not f.repaired and f.severity.value != "INFO"),
        ],
        "governance": [
            *(f"UI/UX compiler: approval — {item}" for item in ir.approval_required),
            *(f"UI/UX compiler: AI trust — {rule}" for rule in ir.ai_trust.provenance_rules + ir.ai_trust.uncertainty_rules),
        ],
    }
    return {key: list(dict.fromkeys(values)) for key, values in buckets.items()}


def serialize_spec_section(ir: UIUXDesignIR) -> list[str]:
    lines = [
        "## UI/UX design specification (compiled)",
        f"- Surface: {ir.mode.value}; platform {ir.product_model.platform.value}; terminal {ir.terminal.value}",
        f"- Primary user: {ir.product_model.primary_user}",
        f"- Primary task: {ir.product_model.primary_task}",
        "- IA: " + ", ".join(f"{item.label} ({item.priority.value})" for item in ir.information_architecture.primary_nav),
        "- Flows: " + "; ".join(f"{flow.name} -> {flow.success_signal}" for flow in ir.flows),
        "- Components: " + ", ".join(component.name for component in ir.components),
        f"- Spec hash: {ir.spec_hash}",
        "",
    ]
    return lines
