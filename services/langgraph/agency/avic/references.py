"""REFERENCE_ANALYSIS: bounded decode, hash, observed palette, rights. No semantic inference.

A reference contributes only what is measured from its pixels (a quantised palette
and dimensions), tagged ``OBSERVED``. A reference whose rights are not asserted by
the server is excluded from influence and listed, never silently used. PNG decodes
with the stdlib codec; JPEG needs Pillow and is ``BLOCKED`` without it.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from . import png
from .contracts import PROMPT_ROLE, Evidence, Provenance, ReferenceAsset, ReferenceManifest, ReferenceRole

MAX_REFERENCE_BYTES = 20 * 1024 * 1024
MAX_REFERENCES = 8
ANALYSIS_SIZE = 96


@dataclass(frozen=True)
class ReferenceInput:
    ref_id: str
    data: bytes
    role: ReferenceRole
    rights_authorized: bool  # asserted by the server (project upload with rights), never by the brief


def _mime(data: bytes) -> Optional[str]:
    if data[:8] == png.SIGNATURE:
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return None


def _decode(data: bytes, mime: str) -> png.Raster:
    if mime == "image/png":
        return png.decode(data)
    try:
        import io

        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise png.PngError("BLOCKED: JPEG decoding needs Pillow (the 'visual' extra)") from exc
    Image.MAX_IMAGE_PIXELS = png.MAX_PIXELS
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
        return png.Raster(im.width, im.height, im.tobytes())


def observed_palette(r: png.Raster, k: int = 5) -> tuple[tuple[str, float], ...]:
    """Most frequent colours after 4-bit-per-channel quantisation of a downsampled copy, with weights."""
    small = png.downsample(r, ANALYSIS_SIZE)
    counts: Counter = Counter()
    for i in range(0, len(small.rgba), 4):
        q = tuple((c >> 4) * 17 for c in small.rgba[i:i + 3])
        counts[q] += 1
    total = sum(counts.values()) or 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return tuple(("#%02x%02x%02x" % c, round(n / total, 4)) for c, n in top)


def analyze(inputs: list[ReferenceInput]) -> tuple[ReferenceManifest, tuple[Evidence, ...]]:
    if len(inputs) > MAX_REFERENCES:
        raise ValueError(f"at most {MAX_REFERENCES} references")
    refs, excluded, evidence = [], [], []
    roles: dict[ReferenceRole, list[str]] = {}
    for inp in inputs:
        if len(inp.data) > MAX_REFERENCE_BYTES:
            excluded.append(f"{inp.ref_id}:oversized")
            continue
        mime = _mime(inp.data)
        if mime is None:
            excluded.append(f"{inp.ref_id}:unsupported_format")
            continue
        if not inp.rights_authorized:
            excluded.append(f"{inp.ref_id}:rights_unverified")
            continue
        try:
            raster = _decode(inp.data, mime)
        except png.PngError as exc:
            excluded.append(f"{inp.ref_id}:{'blocked' if str(exc).startswith('BLOCKED') else 'undecodable'}")
            continue
        pal = observed_palette(raster)
        refs.append(ReferenceAsset(ref_id=inp.ref_id, sha256=hashlib.sha256(inp.data).hexdigest(), role=inp.role,
                                   prompt_role=PROMPT_ROLE[inp.role], mime_type=mime, width=raster.width, height=raster.height,
                                   observed_palette=pal, rights="AUTHORIZED"))
        roles.setdefault(inp.role, []).append(inp.ref_id)
        evidence.append(Evidence(source=inp.ref_id, observation=f"quantised palette {[c for c, _ in pal]}",
                                 interpretation=f"{inp.role.value} reference: colour candidates only, no shapes copied",
                                 provenance=Provenance.OBSERVED, confidence=1.0))
    conflicts = tuple(f"{role.value}:{','.join(ids)}" for role, ids in sorted(roles.items(), key=lambda kv: kv[0].value)
                      if len(ids) > 1 and role in {ReferenceRole.COLOR, ReferenceRole.IDENTITY, ReferenceRole.COMPOSITION})
    return ReferenceManifest(references=tuple(refs), excluded=tuple(excluded), conflicts=conflicts), tuple(evidence)


__all__ = ["MAX_REFERENCES", "MAX_REFERENCE_BYTES", "ReferenceInput", "analyze", "observed_palette"]
