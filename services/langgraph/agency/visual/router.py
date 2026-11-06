"""CapabilityAwareVisualRouter: pick the one local route that fits the intent.

Selection uses the intent's own facts (output format, interactivity, exactness,
realism, category) and the source assets' rights. It never substitutes a
different kind of output when the right route is unavailable: an unavailable
route is BLOCKED with the probe's reasons, and an asset with unknown rights
blocks before any route is considered.
"""

from __future__ import annotations

from typing import Mapping

from .contracts import Capability, Route, RouteDecision, VisualIntent


def _required_routes(intent: VisualIntent) -> tuple[Route, ...]:
    if intent.output == "svg" or intent.category == "brand_mark":
        return (Route.VECTOR,)
    if intent.interactivity or intent.category == "interactive_scene":
        return (Route.THREE_JS,)
    if intent.output == "video" or intent.category == "product_turntable":
        # Frames come from the path tracer; FFmpeg only encodes what was rendered.
        return (Route.LOCAL_VIDEO, Route.BLENDER_CYCLES)
    if intent.category == "concept_image" and intent.exactness == "approximate":
        return (Route.OFFLINE_DIFFUSION,)
    # Exact geometry, controllable product and brand imagery: physically based rendering.
    return (Route.BLENDER_CYCLES,)


def route(intent: VisualIntent, capabilities: Mapping[Route, Capability]) -> RouteDecision:
    considered = {r.value: c.status.value for r, c in sorted(capabilities.items(), key=lambda kv: kv[0].value)}
    unknown_rights = [a.ref for a in intent.source_assets if not a.license]
    if unknown_rights:
        return RouteDecision(route=None, status="BLOCKED", considered=considered,
                             reasons=tuple(f"RIGHTS_UNVERIFIED:{ref}" for ref in unknown_rights))
    needed = _required_routes(intent)
    reasons: list[str] = []
    for r in needed:
        cap = capabilities.get(r)
        if cap is None:
            reasons.append(f"{r.value}:NOT_PROBED")
        elif not cap.available:
            reasons.extend(f"{r.value}:{b}" for b in (cap.blockers or (cap.status.value,)))
    if reasons:
        return RouteDecision(route=None, status="BLOCKED", considered=considered, reasons=tuple(reasons))
    return RouteDecision(route=needed[0], status="SELECTED", considered=considered,
                         reasons=(f"{needed[0].value}: fits {intent.category}/{intent.output}/{intent.exactness}",))


__all__ = ["route"]
