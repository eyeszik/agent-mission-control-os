"""RENDER: SVG -> PNG through the repository's one local rasterizer (``visual.browser.rasterize_svg``).

Chromium runs headless in a network namespace with every non-``data:`` request
aborted (see ``visual/browser.py``). The PNG is a preview, stored separately from the
SVG source; it is never fed back into the SVG.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional

from services.langgraph.agency.visual.browser import probe_browser, rasterize_svg

from .contracts import CapabilityState

RENDERER = "raster.chromium"
# Each render starts a Chromium process. Bound how many run at once on this host (API threads, CLI, tests share it);
# a caller that cannot get a slot in time is told so (BLOCKED, RENDER_CAPACITY) rather than queued without limit.
RENDER_SLOTS = max(1, int(os.environ.get("AMC_AVIC_RENDER_CONCURRENCY", "2") or 2))
SLOT_WAIT_S = 90
_slots = threading.BoundedSemaphore(RENDER_SLOTS)
_state_lock = threading.Lock()
_in_use = 0


def render_slots_free() -> int:
    """How many render slots are available right now, without reserving one.

    ``BoundedSemaphore`` exposes no length, so the count is tracked alongside
    it. A diagnostic probe that claims to report capacity must not consume the
    resource it is measuring -- that would make the report itself the outage.
    """
    with _state_lock:
        return max(0, RENDER_SLOTS - _in_use)


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
    # Non-blocking by design. This runs inside a sync FastAPI route, which the
    # server executes on a bounded anyio threadpool; park a worker thread here
    # for up to SLOT_WAIT_S (90s) and a handful of concurrent compiles can hold
    # every threadpool slot, so unrelated requests -- including /health -- stop
    # being answered. Refusing immediately with a truthful BLOCKED is better
    # than a fleet-wide stall, and the caller can retry.
    if not _slots.acquire(blocking=False):
        return {"status": "BLOCKED", "png": None, "renderer_version": None, "render_ms": None,
                "findings": [f"RENDER_CAPACITY: {RENDER_SLOTS} render(s) already running; retry shortly"]}
    global _in_use
    with _state_lock:
        _in_use += 1
    try:
        t = time.perf_counter()
        r = rasterize_svg(svg_text, width=width, height=height, out_dir=work_dir, timeout_s=timeout_s)
        ms = round((time.perf_counter() - t) * 1000, 1)
    finally:
        with _state_lock:
            _in_use -= 1
        _slots.release()
    version = (r.get("result") or {}).get("browser_version")
    if r["status"] != "PASSED":
        return {"status": "FAILED", "png": None, "renderer_version": version, "render_ms": ms,
                "findings": r.get("findings") or [r.get("stderr_tail", "")[-300:]]}
    return {"status": "PASSED", "png": Path(r["capture"]).read_bytes(), "renderer_version": version, "render_ms": ms,
            "findings": [], "network_isolated": r.get("network_isolated")}


__all__ = ["RENDERER", "render", "renderer_state"]
