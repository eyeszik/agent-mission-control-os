"""Cinematic adapter: ingest and verify a FreeVideoForge render.

Rendering happens out of band (``freevideoforge generate``); this adapter does
what the existing bridge (``project_os.video``) leaves to the caller:

1. ``read_freevideoforge_output`` validates the seven-file run contract and
   refuses runs that do not certify zero paid-API spend;
2. ``ffprobe`` measures the master: container duration, video codec, colour
   primaries, frame rate and frame count;
3. the measurements are checked against the expectation the server supplied
   (duration within tolerance, codec, fps, frames ≈ duration × fps, optional
   BT.709 primaries), and the master's SHA-256 is recorded.

A corrupt or mismatched render fails validation; nothing is "repaired". The
check proves the file matches its declared shape, not that a re-render would
be byte-identical: FreeVideoForge itself reports its reproducibility guarantee
(``SEEDED_BEST_EFFORT`` or ``DETERMINISTIC_PIPELINE``) and that is recorded.

AI video generation has no installed provider; that skill exists only so the
fabric can classify it as PROVIDER_GAP.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from services.langgraph.agency.project_os.video import VideoBridgeError, read_freevideoforge_output

from ..verifiers import Verdict

DURATION_TOLERANCE_S = 0.25


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,avg_frame_rate,nb_read_frames,color_primaries:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if proc.returncode != 0:
        raise VideoBridgeError(f"ffprobe could not read the master: {proc.stderr[-300:]}")
    data = json.loads(proc.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    return {
        "duration": float((data.get("format") or {}).get("duration") or 0.0),
        "codec": stream.get("codec_name"),
        "fps": float(Fraction(stream.get("avg_frame_rate") or "0/1")) if stream.get("avg_frame_rate") not in (None, "0/0") else 0.0,
        "frames": int(stream.get("nb_read_frames") or 0),
        "color_primaries": stream.get("color_primaries"),
    }


# Replaceable in tests (no FFmpeg on most CI hosts).
PROBE: Callable[[Path], dict[str, Any]] = ffprobe


def check_render(probe: dict[str, Any], expect: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    duration, fps, frames = probe["duration"], probe["fps"], probe["frames"]
    check("nonzero_duration", duration > 0, f"duration={duration}")
    if "duration" in expect:
        check("duration", abs(duration - float(expect["duration"])) <= DURATION_TOLERANCE_S,
              f"{duration}s vs {expect['duration']}s ±{DURATION_TOLERANCE_S}")
    if "codec" in expect:
        check("codec", probe["codec"] == expect["codec"], f"{probe['codec']} vs {expect['codec']}")
    if "fps" in expect:
        check("fps", abs(fps - float(expect["fps"])) < 0.01, f"{fps} vs {expect['fps']}")
    if fps > 0:
        check("frame_count", abs(frames - round(duration * fps)) <= 1, f"{frames} frames vs {round(duration * fps)} expected")
    else:
        check("frame_count", False, "frame rate unreadable")
    if expect.get("color_primaries"):
        check("color_primaries", probe.get("color_primaries") == expect["color_primaries"],
              f"{probe.get('color_primaries')} vs {expect['color_primaries']}")
    return checks


def fvf_ingest_verify(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = payload.get("inputs", {})
    output_dir = Path(str(inputs.get("output_dir") or ""))
    if not output_dir.is_dir():
        raise VideoBridgeError("inputs.output_dir must be a finished FreeVideoForge run directory")
    bundle = read_freevideoforge_output(output_dir)
    master = Path(bundle["files"]["final.mp4"]["path"])
    probe = PROBE(master)
    checks = check_render(probe, dict(inputs.get("expect") or {}))
    qc_failed = bundle["qc"]["status"] == "FAIL"
    report = {
        "kind": "video_render_verification",
        "run_id": bundle["run_id"],
        "master_sha256": bundle["files"]["final.mp4"]["sha256"],
        "master_bytes": bundle["files"]["final.mp4"]["bytes"],
        "probe": probe,
        "checks": checks,
        "fvf_qc": bundle["qc"],
        "passed": all(c["passed"] for c in checks) and not qc_failed,
        "reproducibility_guarantee": bundle["reproducibility"].guarantee,
    }
    return {
        "content": json.dumps(report, sort_keys=True, indent=2),
        "mime_type": "application/json",
        "subtype": "video_render_verification",
        "content_file": str(master),
        "content_file_mime": "video/mp4",
    }


def ai_video(payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - never dispatched
    raise RuntimeError("no AI video provider is installed")


def validate_render(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    report = json.loads(output["content"])
    failed = [c["name"] for c in report.get("checks", []) if not c["passed"]]
    if failed or not report.get("passed"):
        return Verdict("video_render_checks", False, f"render checks failed: {failed or report.get('fvf_qc')}")
    return Verdict("video_render_checks", True, "duration, codec, fps and frame count match the expectation")
