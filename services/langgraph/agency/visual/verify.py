"""Independent verification of rendered media from its persisted bytes.

The verifier never trusts the renderer's report. It reopens the bytes and
climbs the quality ladder as far as a machine can honestly go:

    Q0 valid file      magic bytes match the declared type
    Q1 decodable       Pillow decodes the image / ffprobe reads the video / SVG parses safely
    Q2 dims/format     dimensions, frame rate, codec match the intent
    Q3 nonblank        real tonal variation, not a flat, black, white or corrupt frame
    Q4 rights          every source asset has a licence (procedural = owned)

SVG reuses the fabric's ``svg_safety`` and ``palette_conformance`` and, when
``expect["render_sizes"]`` is set, renders the persisted bytes in a real local
Chromium at each size and requires a decoded, non-blank capture.

Q5 visual constraints, Q6 realism/brand and Q7 approval are subjective or
authority decisions. They are always returned as ``human_required`` and are
never passed by this module, whatever the pixels look like.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Optional

from .contracts import MediaVerification, QualityLevel, SourceAsset

VERIFIER = "visual.verify_media/v1 (independent byte reopen)"
HUMAN_LEVELS = (QualityLevel.Q5_VISUAL_CONSTRAINTS, QualityLevel.Q6_REALISM_BRAND, QualityLevel.Q7_APPROVAL)
MIN_STDDEV = 4.0          # 8-bit luminance; below this the frame is effectively flat
MIN_UNIQUE_COLOURS = 256  # a real render has far more; a blank or posterised frame has few


def _image_checks(data: bytes, expect: dict) -> tuple[list[dict], Optional[QualityLevel], list[str]]:
    checks, findings, highest = [], [], None

    def ok(level: QualityLevel, name: str, passed: bool, detail: str) -> bool:
        nonlocal highest
        checks.append({"level": level.value, "check": name, "passed": passed, "detail": detail})
        if passed:
            highest = level
        else:
            findings.append(f"{level.value}:{name}")
        return passed

    if not ok(QualityLevel.Q0_VALID_FILE, "png_magic", data[:8] == b"\x89PNG\r\n\x1a\n", "first 8 bytes"):
        return checks, highest, findings
    try:
        from PIL import Image, ImageStat
    except ImportError:
        checks.append({"level": QualityLevel.Q1_DECODABLE.value, "check": "pillow_decode", "passed": None,
                       "detail": "NOT_RUN: Pillow is not installed (pip install -e './services/langgraph[visual]')"})
        findings.append("PNG_DECODE_NOT_RUN")
        return checks, highest, findings
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # structural check (CRC, chunk layout)
        image = Image.open(io.BytesIO(data))
        image.load()  # full decode of every pixel
    except Exception as exc:  # noqa: BLE001 - any decoder error is a failed verification
        ok(QualityLevel.Q1_DECODABLE, "pillow_decode", False, type(exc).__name__)
        return checks, highest, findings
    ok(QualityLevel.Q1_DECODABLE, "pillow_decode", True, f"{image.format} {image.mode}")
    dims_ok = (image.width, image.height) == (expect["width"], expect["height"]) and image.format == "PNG"
    if not ok(QualityLevel.Q2_DIMENSIONS_FORMAT, "dimensions_format", dims_ok,
              f"{image.width}x{image.height} {image.format} vs {expect['width']}x{expect['height']} PNG"):
        return checks, highest, findings
    rgb = image.convert("RGB")
    luma = ImageStat.Stat(rgb.convert("L"))
    stddev, mean = luma.stddev[0], luma.mean[0]
    unique = len(rgb.resize((min(256, rgb.width), min(256, rgb.height))).getcolors(1 << 16) or []) or 1 << 16
    nonblank = stddev >= MIN_STDDEV and unique >= MIN_UNIQUE_COLOURS and 2.0 < mean < 253.0
    ok(QualityLevel.Q3_NONBLANK, "tonal_variation", nonblank,
       f"luma mean {mean:.1f}, stddev {stddev:.1f}, unique colours (256px sample) {unique}")
    return checks, highest, findings


def _probe_video(path: Path) -> dict:
    proc = subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if proc.returncode != 0:
        raise ValueError(proc.stderr[-300:])
    data = json.loads(proc.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    rate = stream.get("avg_frame_rate") or "0/1"
    return {"codec": stream.get("codec_name"), "width": stream.get("width"), "height": stream.get("height"),
            "fps": float(Fraction(rate)) if rate not in ("0/0",) else 0.0, "frames": int(stream.get("nb_read_frames") or 0),
            "duration": float((data.get("format") or {}).get("duration") or 0.0)}


def _video_checks(data: bytes, expect: dict) -> tuple[list[dict], Optional[QualityLevel], list[str]]:
    checks, findings, highest = [], [], None

    def ok(level: QualityLevel, name: str, passed: bool, detail: str) -> bool:
        nonlocal highest
        checks.append({"level": level.value, "check": name, "passed": passed, "detail": detail})
        if passed:
            highest = level
        else:
            findings.append(f"{level.value}:{name}")
        return passed

    if not ok(QualityLevel.Q0_VALID_FILE, "mp4_ftyp_box", len(data) > 12 and data[4:8] == b"ftyp", "bytes 4-8"):
        return checks, highest, findings
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "master.mp4"
        path.write_bytes(data)
        try:
            probe = _probe_video(path)
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            ok(QualityLevel.Q1_DECODABLE, "ffprobe", False, str(exc)[:200])
            return checks, highest, findings
    ok(QualityLevel.Q1_DECODABLE, "ffprobe", True, f"{probe['codec']} {probe['frames']} frames")
    good = (probe["width"], probe["height"]) == (expect["width"], expect["height"]) and abs(probe["fps"] - expect["fps"]) < 0.01 \
        and probe["frames"] == expect["frames"] and probe["codec"] == "h264"
    if not ok(QualityLevel.Q2_DIMENSIONS_FORMAT, "dims_fps_frames_codec", good,
              f"{probe['width']}x{probe['height']} {probe['fps']}fps {probe['frames']}f {probe['codec']} "
              f"vs {expect['width']}x{expect['height']} {expect['fps']}fps {expect['frames']}f h264"):
        return checks, highest, findings
    ok(QualityLevel.Q3_NONBLANK, "nonzero_duration", probe["duration"] > 0, f"{probe['duration']}s")
    return checks, highest, findings


_GEOMETRY = {"rect", "circle", "ellipse", "path", "polygon", "polyline", "line", "text"}


def _svg_checks(data: bytes, expect: dict) -> tuple[list[dict], Optional[QualityLevel], list[str]]:
    """Vector route: reuse the fabric's deterministic SVG verifiers, plus viewBox/geometry and real multi-size renders."""
    import re
    from xml.etree import ElementTree

    from services.langgraph.agency.execution_fabric.verifiers import palette_conformance, svg_safety

    checks: list[dict] = []
    findings: list[str] = []
    highest: Optional[QualityLevel] = None

    def ok(level: QualityLevel, name: str, passed: bool, detail: str) -> bool:
        nonlocal highest
        checks.append({"level": level.value, "check": name, "passed": passed, "detail": detail})
        if passed:
            highest = level
        else:
            findings.append(f"{level.value}:{name}")
        return passed

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        ok(QualityLevel.Q0_VALID_FILE, "utf8_svg", False, "not UTF-8")
        return checks, highest, findings
    if not ok(QualityLevel.Q0_VALID_FILE, "svg_root", text.lstrip().startswith(("<svg", "<?xml")), "starts with <svg or <?xml"):
        return checks, highest, findings
    safety = svg_safety(text)
    if not ok(QualityLevel.Q1_DECODABLE, "svg_safety", safety.passed, safety.detail):
        return checks, highest, findings
    root = ElementTree.fromstring(text)
    box = [float(v) for v in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()) if v]
    box_ok = len(box) == 4 and box[2] > 0 and box[3] > 0
    if not ok(QualityLevel.Q2_DIMENSIONS_FORMAT, "viewbox", box_ok, root.get("viewBox") or "missing viewBox"):
        return checks, highest, findings
    shapes = sum(1 for el in root.iter() if el.tag.split("}", 1)[-1] in _GEOMETRY)
    if not ok(QualityLevel.Q3_NONBLANK, "geometry_present", shapes > 0, f"{shapes} geometry element(s)"):
        return checks, highest, findings
    palette = expect.get("palette")
    if palette:
        verdict = palette_conformance(text, palette)
        if not ok(QualityLevel.Q3_NONBLANK, "palette_conformance", verdict.passed, verdict.detail):
            return checks, highest, findings
    sizes = expect.get("render_sizes")
    if sizes:
        from .browser import capture_svg_sizes, probe_browser

        probe = probe_browser()
        if not probe["available"]:
            checks.append({"level": QualityLevel.Q3_NONBLANK.value, "check": "multi_size_render", "passed": None,
                           "detail": "NOT_RUN: " + "; ".join(probe["blockers"])})
            findings.append("MULTI_SIZE_RENDER_NOT_RUN")
            return checks, highest, findings
        with tempfile.TemporaryDirectory() as tmp:
            run = capture_svg_sizes(text, sizes=sizes, out_dir=Path(tmp))
            nonblank = []
            if run["status"] == "PASSED":
                try:
                    from PIL import Image, ImageStat
                except ImportError:
                    checks.append({"level": QualityLevel.Q3_NONBLANK.value, "check": "multi_size_render", "passed": None,
                                   "detail": "NOT_RUN: Pillow is not installed to measure the captures"})
                    findings.append("MULTI_SIZE_RENDER_NOT_RUN")
                    return checks, highest, findings

                for cap in run["captures"]:
                    with Image.open(cap) as im:
                        nonblank.append(ImageStat.Stat(im.convert("L")).stddev[0] > 1.0)
            ok(QualityLevel.Q3_NONBLANK, "multi_size_render", run["status"] == "PASSED" and all(nonblank) and bool(nonblank),
               f"chromium rendered {list(sizes)}: {run['findings'] or 'decoded, non-blank'}")
    return checks, highest, findings


def verify_media(data: bytes, *, mime_type: str, expect: dict, source_assets: tuple[SourceAsset, ...] = (),
                 artifact_id: Optional[str] = None, version: Optional[int] = None,
                 recorded_hash: Optional[str] = None) -> MediaVerification:
    observed = hashlib.sha256(data).hexdigest()
    if mime_type == "image/png":
        checks, highest, findings = _image_checks(data, expect)
    elif mime_type == "video/mp4":
        checks, highest, findings = _video_checks(data, expect)
    elif mime_type == "image/svg+xml":
        checks, highest, findings = _svg_checks(data, expect)
    else:
        checks, highest, findings = [], None, [f"NO_VERIFIER_FOR:{mime_type}"]
    if recorded_hash is not None:
        match = observed == recorded_hash
        checks.insert(0, {"level": "INTEGRITY", "check": "sha256_matches_record", "passed": match, "detail": observed})
        if not match:
            findings.insert(0, "CONTENT_HASH_MISMATCH")
    if highest is QualityLevel.Q3_NONBLANK:
        unlicensed = [a.ref for a in source_assets if not a.license]
        rights_ok = not unlicensed
        checks.append({"level": QualityLevel.Q4_RIGHTS.value, "check": "source_rights", "passed": rights_ok,
                       "detail": "procedural only" if not source_assets else f"{len(source_assets)} licensed asset(s)"})
        if rights_ok:
            highest = QualityLevel.Q4_RIGHTS
        else:
            findings.extend(f"RIGHTS_UNVERIFIED:{r}" for r in unlicensed)
    if not checks or (findings and all(f.endswith("_NOT_RUN") for f in findings)):
        status = "INCONCLUSIVE"  # a check that could not run is never a pass, and not evidence of a defect either
    elif findings:
        status = "FAILED"
    else:
        status = "PASSED"
    return MediaVerification(artifact_id=artifact_id, version=version, content_hash=observed, mime_type=mime_type,
                             byte_size=len(data), status=status, highest_passed=highest, checks=tuple(checks),
                             human_required=HUMAN_LEVELS, findings=tuple(findings), verifier=VERIFIER,
                             verified_at=datetime.now(timezone.utc).isoformat())


__all__ = ["HUMAN_LEVELS", "VERIFIER", "verify_media"]
