"""Canonical identity assets for one build: resolved once, reused on every page, never regenerated per page.

Preference: an approved vector master artifact (``visual.logo.master_artifact``),
then a deterministic vector composed from the approved mark key
(``visual.logo.mark``), then a proposed concept (draft only, labelled). With none
of them the master is ``MISSING`` and the page routes to identity review; nothing
is drawn in its place. An SVG that embeds a raster is classified ``RASTER_IN_SVG``,
never ``VECTOR``.
"""

from __future__ import annotations

import base64
import hashlib
import re
from enum import Enum
from typing import Any, Callable, Optional

from services.langgraph.agency.execution_fabric.verifiers import svg_safety

from .fields import FieldState, FieldStatus
from .manifest import _Strict

_RASTER = re.compile(r"<image\b|data:image/(png|jpe?g|gif|webp)", re.I)
_ACTIVE = re.compile(r"<script\b|<foreignObject\b|\bon[a-z]+\s*=|javascript:|<!ENTITY|<!DOCTYPE", re.I)


class AssetKind(str, Enum):
    VECTOR = "VECTOR"
    RASTER_IN_SVG = "RASTER_IN_SVG"
    PROPOSED_CONCEPT = "PROPOSED_CONCEPT"
    MISSING = "MISSING"


class MarkAsset(_Strict):
    kind: AssetKind
    sha256: Optional[str] = None
    svg: Optional[str] = None
    source: str
    approved: bool = False

    @property
    def data_uri(self) -> Optional[str]:
        if not self.svg:
            return None
        return "data:image/svg+xml;base64," + base64.b64encode(self.svg.encode()).decode()

    def public(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "sha256": self.sha256, "source": self.source, "approved": self.approved}


def classify_svg(svg: str) -> AssetKind:
    return AssetKind.RASTER_IN_SVG if _RASTER.search(svg) else AssetKind.VECTOR


def resolve_mark(states: dict[str, FieldState], *, compose_mark: Callable[[str], Optional[str]],
                 load_master: Callable[[str], Optional[bytes]]) -> MarkAsset:
    """``compose_mark(mark_id)`` returns the deterministic SVG for an allowed mark id; ``load_master(ref)`` the
    authorized stored bytes of an artifact (None if absent or not readable by this principal)."""
    master = states.get("visual.logo.master_artifact")
    if master is not None and master.status in (FieldStatus.VALUE, FieldStatus.PROPOSED) and isinstance(master.value, str):
        data = load_master(master.value)
        if data is None:
            # A named master that cannot be read is never silently replaced by another source.
            return MarkAsset(kind=AssetKind.MISSING, source=f"master artifact {master.value} is not readable here: identity review")
        text = data.decode("utf-8", errors="replace")
        kind = classify_svg(text)
        verdict = svg_safety(text)
        # svg_safety refuses every data: reference; an embedded raster is still placeable (it is shown through <img>, where
        # nothing executes) but it is classified RASTER_IN_SVG, never VECTOR. Anything else unsafe is refused.
        safe = verdict.passed or (kind is AssetKind.RASTER_IN_SVG and not _ACTIVE.search(text))
        if not safe:
            return MarkAsset(kind=AssetKind.MISSING, source=f"master artifact {master.value} failed svg safety: {verdict.detail}")
        if master.status is FieldStatus.PROPOSED:
            kind = AssetKind.PROPOSED_CONCEPT
        return MarkAsset(kind=kind, sha256=hashlib.sha256(data).hexdigest(), svg=text, approved=master.approved,
                         source=f"master artifact {master.value}")
    mark = states.get("visual.logo.mark")
    if mark is not None and mark.status in (FieldStatus.VALUE, FieldStatus.PROPOSED) and isinstance(mark.value, str):
        svg = compose_mark(mark.value)
        if svg is not None:
            kind = AssetKind.VECTOR if mark.status is FieldStatus.VALUE else AssetKind.PROPOSED_CONCEPT
            return MarkAsset(kind=kind, sha256=hashlib.sha256(svg.encode()).hexdigest(), svg=svg, approved=mark.approved,
                             source=f"deterministic composition of visual.logo.mark={mark.value}")
    return MarkAsset(kind=AssetKind.MISSING, source="no approved master: route to identity review")


__all__ = ["AssetKind", "MarkAsset", "classify_svg", "resolve_mark"]
