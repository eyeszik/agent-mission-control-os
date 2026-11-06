"""Local-first generation routing, recorded per deliverable.

Order: reuse an unchanged artifact -> compose owned assets -> procedural local
render -> local 3D/vector/motion scene -> licensed retrieval (if enabled) ->
installed local model (if authorized) -> typed capability gap. A hosted
image/video model is never a route. Each decision records the routes it
rejected and why, the evidence it used, and later the observed elapsed time.
"""

from __future__ import annotations

from typing import Mapping

from .contracts import CapabilityManifest

ROUTE_ORDER = ("reuse_existing_artifact", "compose_owned_assets", "procedural_local", "local_scene_render",
               "licensed_retrieval", "local_model", "capability_gap")

NEEDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "genome": ("procedural_local", ()),
    "design_tokens": ("procedural_local", ("web.design_tokens",)),
    "logo_family": ("procedural_local", ("vector.svg",)),
    "icon_family": ("procedural_local", ("vector.svg",)),
    "poster": ("procedural_local", ("vector.svg",)),
    "variants": ("procedural_local", ("vector.svg", "raster.chromium")),
    "website_section": ("procedural_local", ("web.html_css", "web.design_tokens")),
    "product_scene": ("local_scene_render", ("spatial.blender", "raster.chromium")),
    "motion": ("local_scene_render", ("vector.svg", "raster.chromium", "motion.ffmpeg")),
}


def route_deliverable(deliverable: str, caps: Mapping[str, CapabilityManifest], *, owned_assets: int = 0,
                      licensed_enabled: bool = False, local_model_status: str = "BLOCKED") -> dict:
    target, needed = NEEDS[deliverable]
    missing = [c for c in needed if c not in caps or caps[c].status != "AVAILABLE"]
    rejected = [{"route": "reuse_existing_artifact", "reason": "decided at persistence time: unchanged bytes are reused, not re-versioned"},
                {"route": "compose_owned_assets", "reason": "no owned source assets referenced" if not owned_assets
                 else "owned assets are referenced as inputs, not as the deliverable"}]
    evidence = {c: (caps[c].status if c in caps else "UNKNOWN") for c in needed}
    if not missing:
        return {"deliverable": deliverable, "selected": target, "rejected": rejected, "evidence": evidence, "status": "SELECTED"}
    rejected.append({"route": target, "reason": f"missing capabilities {missing}"})
    rejected.append({"route": "licensed_retrieval", "reason": "DISABLED: no discovery adapter is configured and validated"
                     if not licensed_enabled else "does not produce this deliverable type"})
    rejected.append({"route": "local_model", "reason": f"local model status {local_model_status}"})
    rejected.append({"route": "hosted_generation", "reason": "FORBIDDEN: no hosted image/video model is ever a route"})
    return {"deliverable": deliverable, "selected": "capability_gap", "rejected": rejected, "evidence": evidence,
            "status": "BLOCKED", "gap": {"missing": missing,
                                         "blockers": [b for c in missing if c in caps for b in caps[c].blockers]}}


__all__ = ["NEEDS", "ROUTE_ORDER", "route_deliverable"]
