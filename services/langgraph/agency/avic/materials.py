"""H5 material intelligence: appearance parameters with provenance -> vector shading.

This is illustrative vector shading, not physically based rendering. Every
``MaterialSpec`` states ``physical_claim="NONE"``; parameters are ``ARTIST_DEFINED``
or ``APPROXIMATED`` unless an observation backs them (``OBSERVED`` needs an
evidence reference). Shading uses palette colours only (opacity and gradient
structure carry the variation), so brand palette rules still hold. A physics
backend (BRDF fitting, inverse rendering) does not exist here: ``PHYSICS_BACKEND``
is ``BLOCKED``.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import Field, model_validator

from .contracts import (Appearance, CapabilityState, Geometry, Gradient, GradientStop, PathCommand, Provenance, SceneObject,
                        Strict, Unit)

PHYSICS_BACKEND = CapabilityState.BLOCKED
Family = Literal["matte", "glossy", "metallic", "glass", "ceramic", "plastic", "paper", "fabric", "translucent", "layered"]

# (roughness, reflectance, opacity, highlight) per family: artist defaults, not measurements.
FAMILY_DEFAULTS: dict[str, tuple[float, float, float, str]] = {
    "matte": (0.9, 0.04, 1.0, "none"), "glossy": (0.15, 0.5, 1.0, "tight"), "metallic": (0.25, 0.9, 1.0, "tight"),
    "glass": (0.05, 0.4, 0.45, "tight"), "ceramic": (0.35, 0.3, 1.0, "broad"), "plastic": (0.4, 0.25, 1.0, "broad"),
    "paper": (0.95, 0.02, 1.0, "none"), "fabric": (0.98, 0.01, 1.0, "none"), "translucent": (0.3, 0.2, 0.6, "broad"),
    "layered": (0.5, 0.3, 0.85, "broad"),
}
MAX_TEXTURE_STROKES = 24


class MaterialSpec(Strict):
    material_id: str = Field(pattern=r"^mat-[a-z0-9-]{1,40}$")
    family: Family
    roughness: Unit
    reflectance: Unit
    opacity: Unit = 1.0
    texture_scale: Unit = 0.0
    light_direction: float = Field(default=315.0, ge=0, lt=360, allow_inf_nan=False)  # degrees, screen space, 0 = +x
    highlight_distribution: Literal["broad", "tight", "none"]
    shadow_behavior: Literal["contact", "cast", "none"] = "contact"
    surface_color: str   # palette key
    light_color: str     # palette key
    shade_color: str     # palette key
    uncertainty: Unit = 0.5
    provenance: Provenance = Provenance.ARTIST_DEFINED
    evidence_ref: Optional[str] = None
    physical_claim: Literal["NONE"] = "NONE"

    @model_validator(mode="after")
    def observed_needs_evidence(self):
        if self.provenance == Provenance.OBSERVED and not self.evidence_ref:
            raise ValueError("an OBSERVED material parameter needs an evidence reference")
        return self


def material(material_id: str, family: Family, *, surface: str, light: str, shade: str, light_direction: float = 315.0,
             texture_scale: float = 0.0) -> MaterialSpec:
    r, refl, op, hl = FAMILY_DEFAULTS[family]
    return MaterialSpec(material_id=material_id, family=family, roughness=r, reflectance=refl, opacity=op,
                        texture_scale=texture_scale, light_direction=light_direction, highlight_distribution=hl,  # type: ignore[arg-type]
                        surface_color=surface, light_color=light, shade_color=shade, provenance=Provenance.APPROXIMATED)


def shade_disc(spec: MaterialSpec, palette: dict[str, str], *, object_id: str, cx: float, cy: float, r: float,
               ground: Optional[str] = None, requirement_refs: tuple[str, ...] = ()
               ) -> tuple[tuple[Gradient, ...], tuple[SceneObject, ...]]:
    """A shaded disc: body gradient, optional highlight, contact/cast shadow, bounded vector texture.

    A shadow is only drawn when the shade colour is visibly darker than the ground; on a ground that is
    already the darkest palette colour there is nothing to draw it with, so it is omitted rather than faked.
    """
    from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

    for key in (spec.surface_color, spec.light_color, spec.shade_color):
        if key not in palette:
            raise ValueError(f"material colour {key!r} is not in the brand palette")
    s, lt, sh = palette[spec.surface_color], palette[spec.light_color], palette[spec.shade_color]
    ang = math.radians(spec.light_direction)
    fx, fy = 0.5 + 0.28 * math.cos(ang), 0.5 - 0.28 * math.sin(ang)  # focal point toward the light (y is down)
    rough = spec.roughness
    if spec.family == "metallic":
        stops = ((0.0, lt, 1.0), (0.18, s, 1.0), (0.4, sh, 1.0), (0.55, lt, 0.9), (0.72, s, 1.0), (1.0, sh, 1.0))
    else:
        mid = 0.25 + 0.45 * rough
        stops = ((0.0, lt, min(1.0, 0.35 + spec.reflectance)), (mid, s, 1.0), (1.0, sh, 1.0))
    body_grad = Gradient(gradient_id=f"{object_id}-body", kind="radial",
                         coords={"cx": 0.5, "cy": 0.5, "r": 0.5, "fx": round(fx, 3), "fy": round(fy, 3)},
                         stops=tuple(GradientStop(offset=o, color=c, opacity=a) for o, c, a in stops),
                         provenance=spec.provenance)
    objects: list[SceneObject] = []
    grads = [body_grad]
    shadow_visible = ground is None or wcag_contrast_ratio(palette[spec.shade_color], ground) >= 1.2
    if spec.shadow_behavior != "none" and shadow_visible:
        dy = r * (1.04 if spec.shadow_behavior == "contact" else 1.2)
        objects.append(SceneObject(object_id=f"{object_id}-shadow", semantic_role="shadow",
                                   geometry=Geometry(primitive="ellipse", params={"cx": cx - 0.15 * r * math.cos(ang),
                                                                                  "cy": cy + dy, "rx": r * 0.9, "ry": r * 0.12}),
                                   appearance=Appearance(fill=palette[spec.shade_color], opacity=0.55, blur="soft"),
                                   dependencies=(object_id,), material_ref=spec.material_id))
    objects.append(SceneObject(object_id=object_id, semantic_role="material_object",
                               geometry=Geometry(primitive="circle", params={"cx": cx, "cy": cy, "r": r}),
                               appearance=Appearance(fill=f"url(#{body_grad.gradient_id})", opacity=spec.opacity),
                               requirement_refs=requirement_refs, material_ref=spec.material_id))
    if spec.highlight_distribution != "none":
        size = 0.18 if spec.highlight_distribution == "tight" else 0.34
        hx, hy = cx + 0.45 * r * math.cos(ang), cy - 0.45 * r * math.sin(ang)
        objects.append(SceneObject(object_id=f"{object_id}-highlight", semantic_role="highlight",
                                   geometry=Geometry(primitive="ellipse", params={"cx": hx, "cy": hy, "rx": r * size * 1.4,
                                                                                  "ry": r * size * 0.7},
                                                     rotate=-spec.light_direction % 180, clip_to=object_id),
                                   appearance=Appearance(fill=lt, opacity=round(0.25 + 0.6 * spec.reflectance * (1 - rough), 3),
                                                         blur="soft"),
                                   dependencies=(object_id,), material_ref=spec.material_id))
    strokes = int(round(spec.texture_scale * MAX_TEXTURE_STROKES))
    if strokes:
        cmds: list[PathCommand] = []
        for i in range(strokes):
            y = cy - r + (i + 0.5) * (2 * r / strokes)
            half = math.sqrt(max(r * r - (y - cy) ** 2, 0.0))
            cmds += [PathCommand(op="M", coords=(cx - half, y)), PathCommand(op="L", coords=(cx + half, y))]
        objects.append(SceneObject(object_id=f"{object_id}-texture", semantic_role="texture",
                                   geometry=Geometry(primitive="path", path=tuple(cmds), clip_to=object_id),
                                   appearance=Appearance(fill="none", stroke=sh, stroke_width=max(0.5, r * 0.004), opacity=0.25),
                                   dependencies=(object_id,), material_ref=spec.material_id))
    return tuple(grads), tuple(objects)


__all__ = ["FAMILY_DEFAULTS", "MAX_TEXTURE_STROKES", "PHYSICS_BACKEND", "MaterialSpec", "material", "shade_disc"]
