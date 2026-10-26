"""RENDER: SVG -> PNG through the repository's one local rasterizer (``visual.browser.rasterize_svg``).

Chromium runs headless in a network namespace with every non-``data:`` request
aborted (see ``visual/browser.py``). The PNG is a preview, stored separately from the
SVG source; it is never fed back into the SVG.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from services.langgraph.agency.visual.browser import probe_browser, rasterize_svg

from .contracts import CapabilityState

RENDERER = "raster.chromium"


def renderer_state() -> tuple[CapabilityState, list[str], Optional[str]]:
    probe = probe_browser()
    if not probe["available"]:
        return CapabilityState.BLOCKED, list(probe["blockers"]), None
    return CapabilityState.IMPLEMENTED_VERIFIED, [], probe.get("chromium")


def render(svg_text: str, *, width: int, height: int, work_dir: Path, timeout_s: int = 120) -> dict:
    """``{"status": PASSED|BLOCKED|FAILED, "png": bytes|None, "renderer_version", "render_ms", "findings"}``."""
    state, blockers, _ = renderer_state()
    if state != CapabilityState.IMPLEMENTED_VERIFIED:
        return {"status": "BLOCKED", "png": None, "renderer_version": None, "render_ms": None, "findings": blockers}
    t = time.perf_counter()
    r = rasterize_svg(svg_text, width=width, height=height, out_dir=work_dir, timeout_s=timeout_s)
    ms = round((time.perf_counter() - t) * 1000, 1)
    version = (r.get("result") or {}).get("browser_version")
    if r["status"] != "PASSED":
        return {"status": "FAILED", "png": None, "renderer_version": version, "render_ms": ms,
                "findings": r.get("findings") or [r.get("stderr_tail", "")[-300:]]}
    return {"status": "PASSED", "png": Path(r["capture"]).read_bytes(), "renderer_version": version, "render_ms": ms,
            "findings": [], "network_isolated": r.get("network_isolated")}


__all__ = ["RENDERER", "render", "renderer_state"]
