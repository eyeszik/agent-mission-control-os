"""Deterministic generators that wrap existing repository owners.

- logo: ``agency.assets.render_logo_svg`` (the canonical fixed SVG template);
- design system: ``execution_fabric.adapters.uiux.design_system_spec`` (WCAG
  2.2 colour pairs + headless DOM audit of a preview).

Both return ``(ArtifactIR, rendering)``. Neither calls a model or a network.
"""

from __future__ import annotations

from typing import Any

from services.langgraph.agency.assets import render_logo_svg
from services.langgraph.agency.execution_fabric.adapters.uiux import design_system_spec

from .ir import ArtifactIR, ConstraintKind, DesignSystemIR, LogoIR, MissionIR, seal_artifact
from .mission import mission_constraint

GENERATOR_VERSION = "amc-creative-generators/v1"


def _brand(mission: MissionIR) -> dict[str, Any]:
    return mission_constraint(mission, ConstraintKind.BRAND_PALETTE)[0].params


def generate_logo(mission: MissionIR, *, candidate_id: str, provenance: dict[str, Any] | None = None) -> tuple[ArtifactIR, str]:
    b = _brand(mission)
    palette = dict(b["palette"])
    svg = render_logo_svg(brand_name=mission.brand_name, primary=palette["primary"], secondary=palette["secondary"],
                          surface=palette["surface"], tagline=None)
    artifact = seal_artifact(
        artifact_id=candidate_id, mission_id=mission.mission_id, artifact_type="logo",
        semantic_intent=f"{mission.brand_name} mark"[:500], hierarchy=("mark", "wordmark_initials"),
        brand_bindings={"brand_name": mission.brand_name, "palette": palette},
        provenance={"generator": GENERATOR_VERSION, "owner": "agency.assets.render_logo_svg", **(provenance or {})},
        logo=LogoIR(brand_name=mission.brand_name, palette=palette),
    )
    return artifact, svg


def generate_design_system(mission: MissionIR, *, candidate_id: str,
                           provenance: dict[str, Any] | None = None) -> tuple[ArtifactIR, str]:
    b = _brand(mission)
    palette = dict(b["palette"])
    out = design_system_spec({"brand": {"brand_name": mission.brand_name, "palette": palette,
                                        "heading_font": b["heading_font"], "body_font": b["body_font"]}})
    artifact = seal_artifact(
        artifact_id=candidate_id, mission_id=mission.mission_id, artifact_type="design_system",
        semantic_intent=f"{mission.brand_name} design system specification"[:500],
        hierarchy=("color_pairs", "typography", "target_size", "preview"),
        brand_bindings={"brand_name": mission.brand_name, "palette": palette,
                        "heading_font": b["heading_font"], "body_font": b["body_font"]},
        provenance={"generator": GENERATOR_VERSION, "owner": "execution_fabric.adapters.uiux.design_system_spec",
                    **(provenance or {})},
        design_system=DesignSystemIR(palette=palette, heading_font=b["heading_font"], body_font=b["body_font"]),
    )
    return artifact, out["content"]


__all__ = ["GENERATOR_VERSION", "generate_design_system", "generate_logo"]
