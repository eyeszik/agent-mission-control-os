"""Motion-graphics / brand-motion, plus edit/audio/delivery/rights helpers.

Brand behaviour is preserved: for restrained/luxury identities, movement is
low-amplitude with deliberate holds and no arbitrary spring/bounce unless the
brand explicitly allows it.
"""

from __future__ import annotations

from typing import Any

from .schemas import BrandMotion, ShotIR


def compile_brand_motion(brand: BrandMotion) -> str:
    parts: list[str] = []
    if brand.identity:
        parts.append(brand.identity)
    if brand.restraint:
        parts.append(brand.restraint)
    else:
        parts.append("restrained, low-amplitude movement")
    if brand.holds:
        parts.append("deliberate holds on " + ", ".join(brand.holds))
    if brand.amplitude:
        parts.append(f"amplitude {brand.amplitude}")
    if brand.timing:
        parts.append(f"timing {brand.timing}")
    if not brand.allow_spring_bounce:
        parts.append("no spring or bounce easing")
    return "; ".join(parts)


def apply_brand_motion(shot: ShotIR, brand: BrandMotion) -> ShotIR:
    """Fold brand-motion guidance into a shot's atmosphere without overwriting
    declared canon."""

    atmosphere = dict(shot.atmosphere)
    atmosphere.setdefault("brand_motion", compile_brand_motion(brand))
    return shot.model_copy(update={"atmosphere": atmosphere})


def edit_plan(project_edit: dict[str, Any]) -> dict[str, Any]:
    """Normalise an edit/audio/delivery block, preserving rights metadata.

    Platform adaptations are represented explicitly; they never mutate canon.
    """

    return {
        "transitions": list(project_edit.get("transitions", [])),
        "timecodes": list(project_edit.get("timecodes", [])),
        "audio_sources": list(project_edit.get("audio_sources", [])),
        "platform_adaptations": list(project_edit.get("platform_adaptations", [])),
    }
