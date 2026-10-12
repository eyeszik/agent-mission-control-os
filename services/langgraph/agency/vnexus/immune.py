"""VNEXUS design immune system: continuous, evidence-backed checks against the approved creative system.

A scan reads the approved genome, the brand graph and the stored bytes of
every produced output linked into that graph, and reports findings with a
severity (INFO, WARNING, ERROR, BLOCKING) and the evidence behind each.

Remediation is deliberately narrow: only deterministic, reversible repairs
are offered, and only when asked for explicitly. Today that is (a) snapping
an off-palette colour that sits within a small perceptual distance of an
approved colour, written as a new artifact revision so the old version
stays recoverable, and (b) restoring a missing graph provenance edge whose
target is recorded on the artifact. Approved genome decisions are never
changed here, and nothing is repaired on subjective grounds.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution_fabric.verifiers import colors_in, delta_e76
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .genome import Resolution

SEVERITIES = ("INFO", "WARNING", "ERROR", "BLOCKING")
SNAP_DELTA_E = 6.0  # beyond a just-noticeable difference, below an obvious colour change
_FONT = re.compile(r'font-family="([^"]+)"')
_TEXT_FILL = re.compile(r'<text[^>]*\sfill="(#[0-9a-fA-F]{6})"')
_BG = re.compile(r'<rect width="(\d+)" height="(\d+)" fill="(#[0-9a-fA-F]{6})"/>')
_DIMS = re.compile(r'<svg[^>]*\swidth="(\d+)"[^>]*\sheight="(\d+)"')


def finding(code: str, severity: str, subject: str, detail: str, *, evidence: Optional[dict[str, Any]] = None,
            remediation: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    body = {"code": code, "severity": severity, "subject": subject, "detail": detail, "evidence": evidence or {},
            "remediation": remediation}
    return {**body, "finding_id": "fnd-" + canonical_hash({k: body[k] for k in ("code", "subject", "detail")})[:16]}


def palette_from(resolution: Resolution) -> dict[str, str]:
    return {k.split(".")[-1]: str(v).lower() for k, v in resolution.values.items()
            if k.startswith("visual.color.") and isinstance(v, str) and re.fullmatch(r"#[0-9a-f]{6}", str(v).lower())}


def approved_fonts(resolution: Resolution) -> set[str]:
    return {str(v) for k, v in resolution.values.items() if k.startswith("visual.typography.") and isinstance(v, str)}


def genome_findings(resolution: Resolution) -> list[dict[str, Any]]:
    out = []
    for f in resolution.findings:
        if not f.passed:
            sev = "BLOCKING" if f.severity.value == "BLOCKING" else f.severity.value
            out.append(finding(f"GENOME_{f.kind.value}", sev, f"genome:{f.key}", f.detail, evidence={"constraint_id": f.constraint_id,
                                                                                                      "declared_by": f.declared_by}))
    for c in resolution.conflicts:
        out.append(finding(f"INHERITANCE_{c.reason.value}", "ERROR" if c.reason.value != "UNAPPROVED_OVERRIDE" else "INFO",
                           f"genome:{c.key}", c.detail or c.reason.value, evidence={"scope_ref": c.scope_ref, "constraint_id": c.constraint_id}))
    return out


def svg_findings(name: str, svg: str, *, palette: dict[str, str], fonts: set[str], expected: Optional[tuple[int, int]] = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    allowed = sorted(set(palette.values()))
    if allowed:
        for colour in sorted(set(colors_in(svg))):
            nearest = min(allowed, key=lambda p: delta_e76(colour, p))
            d = delta_e76(colour, nearest)
            if d > 2.3:
                remediation = {"kind": "SNAP_COLOUR", "from": colour, "to": nearest, "delta_e76": round(d, 2)} if d <= SNAP_DELTA_E else None
                out.append(finding("OFF_PALETTE_COLOUR", "ERROR", name, f"{colour} is {d:.1f} dE76 from the nearest approved colour {nearest}",
                                   evidence={"colour": colour, "nearest": nearest, "delta_e76": round(d, 2)}, remediation=remediation))
    if fonts:
        for family in sorted(set(_FONT.findall(svg))):
            first = family.split(",")[0].strip().strip("'\"")
            if first not in fonts and first not in {"sans-serif", "serif", "monospace"}:
                out.append(finding("UNAPPROVED_TYPEFACE", "ERROR", name, f"'{first}' is not an approved typeface",
                                   evidence={"approved": sorted(fonts), "found": family}))
    bg = _BG.search(svg)
    if bg:
        for fill in sorted(set(_TEXT_FILL.findall(svg))):
            ratio = wcag_contrast_ratio(fill.lower(), bg.group(3).lower())
            if ratio < 3.0:
                out.append(finding("TEXT_CONTRAST", "ERROR", name, f"text {fill} on {bg.group(3)} is {ratio}:1",
                                   evidence={"ratio": ratio, "threshold": 3.0}))
    if expected:
        dims = _DIMS.search(svg)
        if dims and (int(dims.group(1)), int(dims.group(2))) != expected:
            out.append(finding("ASSET_DIMENSIONS", "ERROR", name, f"{dims.group(1)}x{dims.group(2)} != expected {expected[0]}x{expected[1]}"))
    return out


def png_dims(data: bytes) -> Optional[tuple[int, int]]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def snap_colours(svg: str, swaps: dict[str, str]) -> str:
    """Replace exact colour literals (case-insensitive). Deterministic and reversible through artifact history."""
    out = svg
    for old, new in sorted(swaps.items()):
        out = re.sub(re.escape(old), new, out, flags=re.IGNORECASE)
    return out


__all__ = ["SEVERITIES", "SNAP_DELTA_E", "approved_fonts", "finding", "genome_findings", "palette_from", "png_dims", "snap_colours",
           "svg_findings"]
