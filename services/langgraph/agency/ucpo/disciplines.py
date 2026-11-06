"""Fifteen creative disciplines, one shared router over discovered capabilities.

A discipline declares what it needs (``routes``: alternatives, each an all-of set of
capability ids). ``route`` picks the first alternative whose capabilities this host
actually has, using the Foundry capability discovery (never configuration) plus the UCPO
sandbox probe for website work. When no alternative is satisfied the result is
``CAPABILITY_GAP`` with the discipline's fallback, which is always a specification or
prompt package that stops at ``PROMPT_PACKAGE_READY`` -- never a fabricated artifact.
Hosted image/video generation has no adapter here, so ``provider.t2i`` / ``provider.t2v``
are always missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PROVIDER_GAPS = {
    "provider.t2i": "no verified text-to-image provider adapter is installed",
    "provider.t2v": "no verified text-to-video provider adapter is installed",
    "provider.xr_runtime": "no WebXR/OpenXR runtime or device adapter is installed",
    "provider.print": "no print or fabrication vendor adapter is installed",
}


@dataclass(frozen=True)
class Discipline:
    discipline_id: str
    name: str
    purpose: str
    input_schema: str
    output_schema: str
    routes: tuple[tuple[str, ...], ...]          # alternatives; each is all-of
    quality_checks: tuple[str, ...]
    accessibility: tuple[str, ...]
    rights: str
    fallback: str
    approval: str = "human review through /approvals/{id}/decide before any release; approval never deploys or publishes"

    def describe(self) -> dict:
        return {k: getattr(self, k) for k in ("discipline_id", "name", "purpose", "input_schema", "output_schema", "routes",
                                              "quality_checks", "accessibility", "rights", "fallback", "approval")}


_OWN = "procedural or operator-supplied with a recorded licence; references contribute principles only"
DISCIPLINES: tuple[Discipline, ...] = (
    Discipline("01.art_direction", "Art Direction", "Set the visual direction a family of deliverables shares.",
               "UserBrief + CreativeGenome", "CompositionIR (SVG)", (("vector.svg",),),
               ("palette_conformance", "one accent per composition", "svg_safety"), ("contrast floors per pairing",), _OWN,
               "compile the genome and direction notes only"),
    Discipline("02.brand_identity", "Brand Identity", "Mark, lockup and tokens derived from one genome.",
               "CreativeGenome", "mark/lockup SVG + DTCG tokens", (("vector.svg", "web.design_tokens"),),
               ("svg_safety", "dtcg_compile", "palette_conformance"), ("mark legible at 24px", "contrast of lockup text"),
               _OWN, "compile the genome and token document only"),
    Discipline("03.typography", "Typography", "Type scale, families and specimen.", "CreativeGenome",
               "DTCG typography tokens + HTML specimen", (("web.design_tokens", "web.html_css"),),
               ("dtcg_compile", "text_scaling", "font_fallback"), ("min body 16px", "200% text zoom without loss"),
               "system and fallback stacks only; no font files are fetched", "token document only"),
    Discipline("04.editorial_design", "Editorial Design", "Editorial pages: grids, hierarchy, serial numbering.",
               "WebsiteBrief", "verified static site (UCPO)", (("web.ucpo_site",),),
               ("semantic_coverage", "reflow", "headings", "psem_colours"), ("axe-core automated checks", "keyboard focus"),
               _OWN, "generate source only and report BLOCKED_ISOLATION"),
    Discipline("05.conceptual_photography", "Conceptual Photography", "Impossible-yet-photographic still images.",
               "ImageSpec", "photograph (image/*)", (("provider.t2i",),),
               ("rights_record", "no identifiable people", "provenance"), ("alt text authored by a person",),
               "only verified providers or licensed photography; nothing is generated without one",
               "compile an ImageSpec prompt package (PROMPT_PACKAGE_READY)"),
    Discipline("06.ui_ux", "UI/UX", "Interface specification and working pages.", "UIUXDesignIR / WebsiteBrief",
               "UIUX_SPEC_READY + verified static site", (("web.ucpo_site",), ("web.html_css",)),
               ("keyboard_flow", "labels", "contrast", "reflow", "reduced_motion"), ("WCAG 2.2 AA automated subset",),
               _OWN, "compile the UI/UX spec only"),
    Discipline("07.interactive_3d", "Interactive 3D", "Real-time 3D scenes in the browser.", "SceneIR",
               "WebGL/WebGPU page", (("spatial.threejs",), ("spatial.r3f",)),
               ("webgl_capture", "frame budget"), ("reduced-motion still fallback", "keyboard camera controls"), _OWN,
               "render Blender stills where available; otherwise SceneIR spec only"),
    Discipline("08.ar_vr_xr", "AR/VR/XR", "Immersive experiences on XR runtimes.", "SceneIR + interaction spec",
               "XR build", (("provider.xr_runtime",),), ("comfort", "frame budget"), ("seated mode", "captions"), _OWN,
               "scene and interaction specification only"),
    Discipline("09.narrative_web", "Narrative Web", "Long-form story told across sections.", "WebsiteBrief",
               "verified static site (UCPO)", (("web.ucpo_site",),), ("semantic_coverage", "reading order", "reflow"),
               ("reduced motion", "skip link", "headings"), _OWN, "generate source only and report BLOCKED_ISOLATION"),
    Discipline("10.campaigns_posters", "Campaigns/Posters", "Poster and campaign sets.", "CreativeGenome + copy",
               "SVG + PNG", (("vector.svg", "raster.chromium"), ("vector.svg",)),
               ("svg_safety", "palette_conformance", "png_decode"), ("text contrast",), _OWN, "SVG only, without rasters"),
    Discipline("11.motion_design", "Motion Design", "Keyframed brand motion.", "MotionIR",
               "MP4 (H.264)", (("vector.svg", "raster.chromium", "motion.ffmpeg"),),
               ("ffprobe_dims_fps_frames_codec",), ("reduced-motion still", "no flashing above 3 per second"), _OWN,
               "keyframe specification and SVG frames only"),
    Discipline("12.technical_information_design", "Technical/Information Design", "Diagrams, indexes and data pages.",
               "WebsiteBrief / CompositionIR", "static site or SVG", (("web.ucpo_site",), ("vector.svg",)),
               ("semantic_coverage", "text alternatives"), ("data available as text, not only as graphics",), _OWN,
               "SVG composition only"),
    Discipline("13.environmental_graphics", "Environmental/Physical Graphics", "Signage and wayfinding mock scenes.",
               "SceneIR", "Blender still + print spec", (("spatial.blender", "provider.print"), ("spatial.blender",)),
               ("png_decode", "dimensions"), ("legibility distance", "contrast in situ"), _OWN,
               "scene and print specification only; fabrication is never ordered"),
    Discipline("14.spatial_branding", "Spatial Branding", "Brand applied to spaces.", "SceneIR + CreativeGenome",
               "Blender still", (("spatial.blender",),), ("png_decode", "nonblank"), ("wayfinding contrast",), _OWN,
               "scene specification only"),
    Discipline("15.cross_media_identity", "Cross-Media Identity", "One identity across print, web and motion.",
               "CreativeGenome", "SVG + tokens + site + MP4", (("vector.svg", "web.design_tokens", "web.ucpo_site",
                                                                  "motion.ffmpeg"),),
               ("palette_conformance", "dtcg_compile", "semantic_coverage", "ffprobe_dims_fps_frames_codec"),
               ("each medium's own checks",), _OWN, "route each medium separately; report each gap"),
)


def availability() -> dict[str, dict]:
    """Capability id -> {status, blockers}, discovered on this host."""
    from services.langgraph.agency.foundry.capabilities import discover

    from .sandbox import probe_isolation

    out = {c.capability_id: {"status": c.status, "blockers": list(c.blockers)} for c in discover()}
    iso = probe_isolation()
    out["web.ucpo_site"] = {"status": "AVAILABLE" if iso.available else "MISSING", "blockers": list(iso.reasons)}
    for cap, why in PROVIDER_GAPS.items():
        out[cap] = {"status": "MISSING", "blockers": [why]}
    return out


def route(discipline_id: str, *, available: Optional[dict[str, dict]] = None) -> dict:
    d = next((x for x in DISCIPLINES if x.discipline_id == discipline_id), None)
    if d is None:
        raise KeyError(f"unknown discipline {discipline_id}")
    caps = available if available is not None else availability()
    for alternative in d.routes:
        if all(caps.get(c, {}).get("status") == "AVAILABLE" for c in alternative):
            return {"discipline_id": d.discipline_id, "status": "ROUTED", "capabilities": list(alternative),
                    "approval": d.approval}
    missing = sorted({c for alt in d.routes for c in alt if caps.get(c, {}).get("status") != "AVAILABLE"})
    return {"discipline_id": d.discipline_id, "status": "CAPABILITY_GAP", "missing": missing,
            "blockers": {c: caps.get(c, {}).get("blockers", ["not discovered"]) for c in missing},
            "fallback": d.fallback, "terminal_state": "PROMPT_PACKAGE_READY"}


__all__ = ["DISCIPLINES", "PROVIDER_GAPS", "Discipline", "availability", "route"]
