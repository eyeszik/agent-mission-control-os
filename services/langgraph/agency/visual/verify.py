"""Independent verification of rendered media from its persisted bytes.

The verifier never trusts the renderer's report. It reopens the bytes and
climbs the quality ladder as far as a machine can honestly go:

    Q0 valid file      magic bytes match the declared type
    Q1 decodable       Pillow decodes the image / ffprobe reads the video / SVG parses safely
    Q2 dims/format     dimensions, frame rate, codec match the intent
    Q3 nonblank        real tonal variation, not a flat, black, white or corrupt frame
    Q4 rights          licence fields exist for the *declared* sources; an empty
                       list is the caller's procedural-only assumption, not an
                       independently verified inventory or font clearance

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
    min_unique = int(expect.get("min_unique_colours", MIN_UNIQUE_COLOURS))  # flat vector art legitimately has few
    nonblank = stddev >= MIN_STDDEV and unique >= min_unique and 2.0 < mean < 253.0
    ok(QualityLevel.Q3_NONBLANK, "tonal_variation", nonblank,
       f"luma mean {mean:.1f}, stddev {stddev:.1f}, unique colours (256px sample) {unique}")
    return checks, highest, findings


class VideoProbeUnavailable(RuntimeError):
    """A video check could not safely execute; it is not a passing check."""


def _probe_video(path: Path) -> dict:
    from services.langgraph.agency.ucpo.sandbox import probe_isolation, wrap
    from services.langgraph.agency.visual.file_staging import UnsafeInput, copy_regular_bounded

    executable = shutil.which("ffprobe")
    if not executable:
        raise VideoProbeUnavailable("ffprobe not installed")
    isolation = probe_isolation()
    if not isolation.available:
        raise VideoProbeUnavailable("isolation unavailable: " + "; ".join(isolation.reasons))
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix="amc-video-probe-input-") as inp, tempfile.TemporaryDirectory(prefix="amc-video-probe-") as tmp:
        inputs, work = Path(inp), Path(tmp)
        staged = inputs / "video.mp4"
        try:
            copy_regular_bounded(path, staged, max_bytes=256 * 1024 * 1024)
        except (OSError, UnsafeInput) as exc:
            raise ValueError("invalid or oversized video input") from exc
        cmd = wrap(["/usr/bin/prlimit", "--as=2147483648", "--cpu=120", "--fsize=8388608", "--", executable, "-v", "error",
                    "-protocol_whitelist", "file,pipe", "-count_frames", "-select_streams", "v:0", "-show_entries",
                    "stream=codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration", "-of", "json", str(staged)],
                   cwd=work, home=work, node=isolation.node or "node", timeout_s=120,
                   readonly_paths=(Path(executable), inputs))
        result_file, error_file = work / "probe.json", work / "probe.err"
        try:
            with result_file.open("wb") as result, error_file.open("wb") as errors:
                proc = subprocess.run(cmd, stdout=result, stderr=errors, timeout=150)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VideoProbeUnavailable(type(exc).__name__) from exc
        if proc.returncode != 0 or result_file.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("ffprobe failed or exceeded its output budget")
        data = json.loads(result_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("streams"), list) or len(data["streams"]) != 1:
        raise ValueError("ffprobe did not return exactly one video stream")
    stream, fmt = data["streams"][0], data.get("format") or {}
    if not isinstance(stream, dict) or not isinstance(fmt, dict):
        raise ValueError("invalid ffprobe result")
    rate = stream.get("avg_frame_rate") or "0/1"
    try:
        return {"codec": stream.get("codec_name"), "width": stream.get("width"), "height": stream.get("height"),
                "fps": float(Fraction(rate)) if rate not in ("0/0",) else 0.0, "frames": int(stream.get("nb_read_frames") or 0),
                "duration": float(fmt.get("duration") or 0.0)}
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("invalid ffprobe numeric result") from exc


def _sample_video_pixels(path: Path, frames: int) -> tuple[bool, str]:
    """Decode bounded representative frames; duration alone is not nonblank proof."""
    from services.langgraph.agency.ucpo.sandbox import probe_isolation, wrap
    from services.langgraph.agency.visual.file_staging import UnsafeInput, copy_regular_bounded

    try:
        from PIL import Image, ImageStat
    except ImportError as exc:
        raise VideoProbeUnavailable("Pillow is unavailable") from exc
    executable = shutil.which("ffmpeg")
    isolation = probe_isolation()
    if not executable or not isolation.available:
        raise VideoProbeUnavailable("ffmpeg or isolation unavailable for pixel sampling")
    if not 1 <= frames <= 900:
        raise ValueError("video frame count exceeds pixel-verification budget")
    executable = str(Path(executable).resolve())
    centers = (min(frames - 1, frames // 10), frames // 2, min(frames - 1, frames * 9 // 10))
    # A single frame may legitimately be in a fade. Sample two nearby frames
    # in each region and require variation in every region, while explicitly
    # reporting flat observations instead of claiming every frame is nonblank.
    offset = max(1, min(12, frames // 20))
    regions = [tuple(sorted({index, min(frames - 1, index + offset)})) for index in centers]
    indexes = sorted({index for region in regions for index in region})
    expression = "+".join(f"eq(n\\,{index})" for index in indexes)
    with tempfile.TemporaryDirectory(prefix="amc-video-sample-input-") as inp, tempfile.TemporaryDirectory(prefix="amc-video-sample-") as tmp:
        inputs, work = Path(inp), Path(tmp)
        staged = inputs / "video.mp4"
        try:
            copy_regular_bounded(path, staged, max_bytes=256 * 1024 * 1024)
        except (OSError, UnsafeInput) as exc:
            raise ValueError("invalid or oversized video input") from exc
        cmd = wrap(["/usr/bin/prlimit", "--as=2147483648", "--cpu=120", "--fsize=16777216", "--", executable,
                    "-nostdin", "-v", "error", "-threads", "2", "-protocol_whitelist", "file,pipe", "-i", str(staged),
                    "-vf", f"select={expression},scale=256:256:force_original_aspect_ratio=decrease", "-fps_mode", "passthrough",
                    "-frames:v", str(len(indexes)), str(work / "sample_%02d.png")], cwd=work, home=work,
                   node=isolation.node or "node", timeout_s=120, readonly_paths=(Path(executable), inputs))
        try:
            with (work / "sample.err").open("wb") as errors:
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=errors, timeout=150)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VideoProbeUnavailable(type(exc).__name__) from exc
        samples = sorted(work.glob("sample_*.png"))
        if proc.returncode != 0 or len(samples) != len(indexes):
            raise ValueError("could not decode all requested video samples")
        measured: dict[int, tuple[float, int]] = {}
        for index, sample in zip(indexes, samples):
            if sample.is_symlink() or not sample.is_file() or sample.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("invalid sampled frame")
            try:
                with Image.open(sample) as image:
                    image.load()
                    if image.width > 256 or image.height > 256:
                        raise ValueError("sample dimensions exceed bound")
                    gray = image.convert("L")
                    stddev = float(ImageStat.Stat(gray).stddev[0])
                    colors = gray.getcolors(256) or []
                    measured[index] = (stddev, len(colors))
            except (OSError, ValueError) as exc:
                raise ValueError("sample image could not be decoded") from exc
    def varied(index: int) -> bool:
        stddev, colors = measured[index]
        return stddev >= MIN_STDDEV and colors >= 2

    passed = all(any(varied(index) for index in region) for region in regions)
    flat = [index for index in indexes if not varied(index)]
    return passed, (f"{len(measured)} sampled frames in 3 regions at indexes {indexes}; low-variation samples {flat}; "
                    "luma standard deviations " + ", ".join(f"{measured[index][0]:.1f}" for index in indexes)
                    + "; unsampled frames and creative quality still require review")


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
    if len(data) > 256 * 1024 * 1024:
        ok(QualityLevel.Q1_DECODABLE, "video_size_limit", False, "video exceeds the 256 MiB verification budget")
        return checks, highest, findings
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "master.mp4"
        path.write_bytes(data)
        try:
            probe = _probe_video(path)
        except VideoProbeUnavailable as exc:
            checks.append({"level": QualityLevel.Q1_DECODABLE.value, "check": "ffprobe", "passed": None,
                           "detail": f"NOT_RUN: {str(exc)[:160]}"})
            findings.append("FFPROBE_NOT_RUN")
            return checks, highest, findings
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
        if not ok(QualityLevel.Q2_DIMENSIONS_FORMAT, "positive_duration", probe["duration"] > 0, f"{probe['duration']}s"):
            return checks, highest, findings
        try:
            nonblank, detail = _sample_video_pixels(path, probe["frames"])
        except VideoProbeUnavailable as exc:
            checks.append({"level": QualityLevel.Q3_NONBLANK.value, "check": "sampled_pixel_variation", "passed": None,
                           "detail": f"NOT_RUN: {str(exc)[:160]}"})
            findings.append("VIDEO_PIXEL_SAMPLING_NOT_RUN")
            return checks, highest, findings
        except (ValueError, OSError) as exc:
            ok(QualityLevel.Q3_NONBLANK, "sampled_pixel_variation", False, str(exc)[:200])
            return checks, highest, findings
        ok(QualityLevel.Q3_NONBLANK, "sampled_pixel_variation", nonblank, detail)
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
                       "detail": (f"{len(source_assets)} declared source(s) checked for a licence field; "
                                  "inventory completeness, implicit resources and licence validity not verified")})
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
