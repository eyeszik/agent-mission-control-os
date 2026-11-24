"""VNEXUS video and motion production: brief -> script -> storyboard -> shots -> assets -> animation -> render -> QC -> master.

Two production paths, chosen per shot:

* Path A, procedural: vector shots composed from the approved genome (mark,
  wordmark, headline, rules, grammar primitives), animated by keyframes,
  rendered frame by frame in local Chromium and encoded by FFmpeg through the
  media fabric's ``local.svg_motion`` provider. Compositing is the SVG layer
  stack of each frame.
* Path B, AI media: shots that need footage or photographic imagery become
  jobs on the fabric's hosted providers. Those are DISABLED, so the shots are
  reported BLOCKED with the provider's blockers. They are never simulated or
  substituted.

The script uses only copy the requester supplied; anything missing is a
visible placeholder, never invented messaging. Audio is muxed only from a
supplied, licensed file; otherwise the master is silent and says so. Every
master ships with WebVTT captions generated from the script and a
reduced-motion still.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from pydantic import Field, field_validator

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry import compose
from services.langgraph.agency.foundry.contracts import CreativeGenome
from services.langgraph.agency.foundry.motion import EASING

from .genome import _Strict

VIDEO_PIPELINE = "amc-vnexus-video/v1"
STAGES = ("brief", "script", "storyboard", "shot_list", "asset_plan", "animation_plan", "render_jobs", "compositing", "audio",
          "quality_control", "master")


class ShotKind(str, Enum):
    MARK_REVEAL = "MARK_REVEAL"          # procedural
    HEADLINE = "HEADLINE"                # procedural
    VALUE_POINTS = "VALUE_POINTS"        # procedural
    CALL_TO_ACTION = "CALL_TO_ACTION"    # procedural
    LIVE_ACTION = "LIVE_ACTION"          # needs footage: AI or filmed
    PRODUCT_PHOTO = "PRODUCT_PHOTO"      # needs photographic imagery


PROCEDURAL = frozenset({ShotKind.MARK_REVEAL, ShotKind.HEADLINE, ShotKind.VALUE_POINTS, ShotKind.CALL_TO_ACTION})


class VideoBrief(_Strict):
    objective: str = Field(min_length=1, max_length=500)
    headline: str = Field(default="", max_length=120)
    points: tuple[str, ...] = Field(default=(), max_length=4)
    cta: str = Field(default="", max_length=60)
    width: int = Field(default=960, ge=160, le=1920)
    height: int = Field(default=540, ge=160, le=1920)
    fps: int = Field(default=24, ge=8, le=30)
    max_duration_s: float = Field(default=12.0, gt=0, le=30)
    include_shots: tuple[ShotKind, ...] = ()   # extra non-procedural shots the requester wants (e.g. LIVE_ACTION)
    audio_artifact_id: Optional[str] = None
    audio_licence: str = Field(default="", max_length=300)

    @field_validator("include_shots")
    @classmethod
    def _external_shots_only(cls, kinds: tuple[ShotKind, ...]) -> tuple[ShotKind, ...]:
        if any(kind in PROCEDURAL for kind in kinds):
            raise ValueError("include_shots accepts only extra footage or photographic shots")
        return kinds


class Shot(_Strict):
    shot_id: str
    kind: ShotKind
    duration_s: float
    text: tuple[str, ...] = ()
    camera: str
    transition: str
    path: str  # "A_PROCEDURAL" | "B_AI_PROVIDER"


def script(brief: VideoBrief, brand_name: str) -> dict[str, Any]:
    lines, placeholders = [], []
    headline = brief.headline or "[HEADLINE NOT PROVIDED]"
    if not brief.headline:
        placeholders.append("headline")
    cta = brief.cta or "[CALL TO ACTION NOT PROVIDED]"
    if not brief.cta:
        placeholders.append("cta")
    lines.append({"scene": "open", "on_screen": brand_name})
    lines.append({"scene": "headline", "on_screen": headline})
    for i, point in enumerate(brief.points):
        lines.append({"scene": f"point_{i + 1}", "on_screen": point})
    lines.append({"scene": "close", "on_screen": cta})
    return {"lines": lines, "placeholders": placeholders, "source": "requester copy only; nothing generated"}


def shot_list(brief: VideoBrief, brand_name: str) -> list[Shot]:
    shots = [Shot(shot_id="s1", kind=ShotKind.MARK_REVEAL, duration_s=2.5, text=(brand_name,), camera="static, mark scales in",
                  transition="cut", path="A_PROCEDURAL"),
             Shot(shot_id="s2", kind=ShotKind.HEADLINE, duration_s=3.0, text=(brief.headline or "[HEADLINE NOT PROVIDED]",),
                  camera="slow push-in (scale 1.00 -> 1.04)", transition="cut", path="A_PROCEDURAL")]
    if brief.points:
        shots.append(Shot(shot_id="s3", kind=ShotKind.VALUE_POINTS, duration_s=1.2 * len(brief.points) + 0.8, text=brief.points,
                          camera="static; points stagger in", transition="cut", path="A_PROCEDURAL"))
    for i, kind in enumerate(brief.include_shots):
        shots.append(Shot(shot_id=f"x{i + 1}", kind=kind, duration_s=3.0, camera="unspecified", transition="cut",
                          path="A_PROCEDURAL" if kind in PROCEDURAL else "B_AI_PROVIDER"))
    shots.append(Shot(shot_id="s9", kind=ShotKind.CALL_TO_ACTION, duration_s=2.5, text=(brief.cta or "[CALL TO ACTION NOT PROVIDED]",),
                      camera="static", transition="cut", path="A_PROCEDURAL"))
    # ``max_duration_s`` is an upper bound, not permission to silently discard
    # the last shot. When necessary, fit every procedural shot into that bound
    # on the actual frame grid, keeping at least one second per shot. Extra
    # provider shots remain explicitly blocked and do not count as rendered.
    procedural = [s for s in shots if s.path == "A_PROCEDURAL"]
    budget_frames = int(Fraction(str(brief.max_duration_s)) * brief.fps)
    if budget_frames < len(procedural) * brief.fps:
        raise ValueError("VIDEO_BUDGET_TOO_SHORT: at least one second per procedural shot is required")
    normal_frames = [max(2, round(Fraction(str(s.duration_s)) * brief.fps)) for s in procedural]
    if sum(normal_frames) <= budget_frames:
        allocated = normal_frames
    else:
        minimum = brief.fps
        remaining = budget_frames - minimum * len(procedural)
        weights = [Fraction(str(s.duration_s)) for s in procedural]
        total = sum(weights)
        quotas = [remaining * weight / total for weight in weights]
        allocated = [minimum + int(q) for q in quotas]
        # Largest remainder is deterministic and uses every frame without overflow.
        for index in sorted(range(len(quotas)), key=lambda i: (-(quotas[i] - int(quotas[i])), i))[:budget_frames - sum(allocated)]:
            allocated[index] += 1
    duration_by_id = {shot.shot_id: frames / brief.fps for shot, frames in zip(procedural, allocated)}
    return [shot.model_copy(update={"duration_s": duration_by_id[shot.shot_id]}) if shot.path == "A_PROCEDURAL" else shot
            for shot in shots]


def _ease(t: float) -> float:
    return EASING["ease_out"](max(0.0, min(1.0, t)))


def _text(x: float, y: float, size: float, fill: str, family: str, text: str, *, weight: int = 700, opacity: float = 1.0,
          anchor: str = "start") -> str:
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="{escape(family, {chr(34): "&quot;"})}" font-size="{size:.2f}" '
            f'font-weight="{weight}" fill="{fill}" opacity="{opacity:.3f}" text-anchor="{anchor}">{escape(text)}</text>')


def _headline_lines(text: str, *, width: int, height: int, kind: ShotKind) -> tuple[list[str], float]:
    """Use the renderer's conservative estimate; never silently clip impossible copy.

    These estimates are not a substitute for checking actual browser text bounds
    and a human review of the rendered frames.
    """
    size = height * (0.11 if kind is ShotKind.HEADLINE else 0.09)
    max_width = width * 0.8
    words, lines, line = text.split(), [], ""
    if not words:
        raise ValueError("VIDEO_COPY_EMPTY")
    for word in words:
        if len(word) * size * 0.55 > max_width:
            raise ValueError("VIDEO_COPY_EXCEEDS_LAYOUT: unbroken word is too wide")
        if len(line + " " + word) * size * 0.55 > max_width and line:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    lines.append(line)
    y0 = height / 2 - (len(lines) - 1) * size * 0.6
    if y0 - size < height * 0.06 or y0 + (len(lines) - 1) * size * 1.15 + size * 0.25 > height * 0.94:
        raise ValueError("VIDEO_COPY_EXCEEDS_LAYOUT: too many lines")
    return lines, size


def shot_frame(shot: Shot, genome: CreativeGenome, t: float, *, width: int, height: int) -> str:
    """One frame of a procedural shot at local time t in [0, 1]. Pure."""
    pal = genome.palette.roles()
    display = ", ".join(genome.typography_rules["stacks"]["display"])
    body = ", ".join(genome.typography_rules["stacks"]["text"])
    layers: list[str] = [f'<rect width="{width}" height="{height}" fill="{pal["paper"]}"/>']
    if shot.kind is ShotKind.MARK_REVEAL:
        if not shot.text or not shot.text[0].strip() or len(shot.text[0]) * height * 0.07 * 0.55 > width * 0.88:
            raise ValueError("VIDEO_COPY_EXCEEDS_LAYOUT: wordmark is missing or too wide")
        e = _ease(t / 0.6)
        size = min(width, height) * 0.42
        mark = compose.mark(genome, size=200)
        body_svg = "".join(compose._shape(p, pal) for p in mark.primitives)  # noqa: SLF001 - same renderer
        s = (size / 200) * (0.7 + 0.3 * e)
        layers.append(f'<g opacity="{e:.3f}" transform="translate({width / 2 - 100 * s:.2f} {height * 0.45 - 100 * s:.2f}) scale({s:.4f})">'
                      f"{body_svg}</g>")
        layers.append(_text(width / 2, height * 0.86, height * 0.07, pal["ink"], display, shot.text[0], opacity=_ease((t - 0.4) / 0.4),
                            anchor="middle"))
    elif shot.kind in (ShotKind.HEADLINE, ShotKind.CALL_TO_ACTION):
        zoom = 1.0 + 0.04 * t if shot.kind is ShotKind.HEADLINE else 1.0
        lines, size = _headline_lines(shot.text[0], width=width, height=height, kind=shot.kind)
        y0 = height / 2 - (len(lines) - 1) * size * 0.6
        g = "".join(_text(width * 0.1, y0 + i * size * 1.15, size, pal["ink"], display, ln, opacity=_ease((t - i * 0.1) / 0.35))
                    for i, ln in enumerate(lines))
        layers.append(f'<g transform="translate({width / 2:.2f} {height / 2:.2f}) scale({zoom:.4f}) translate({-width / 2:.2f} {-height / 2:.2f})">{g}</g>')
        layers.append(f'<rect x="{width * 0.1:.2f}" y="{y0 + len(lines) * size * 1.15 - size * 0.4:.2f}" '
                      f'width="{width * 0.3 * _ease(t / 0.7):.2f}" height="{max(4, height * 0.012):.2f}" fill="{pal["accent"]}"/>')
    elif shot.kind is ShotKind.VALUE_POINTS:
        n = len(shot.text)
        if (not n or any(not point.strip() or len(point) * height * 0.055 * 0.55 > width * 0.8 - height * 0.06
                         for point in shot.text)):
            raise ValueError("VIDEO_COPY_EXCEEDS_LAYOUT: value point is missing or too wide")
        for i, point in enumerate(shot.text):
            start = i / (n + 0.6)
            e = _ease((t - start) / 0.25)
            y = height * (0.3 + 0.5 * i / max(1, n - 1 if n > 1 else 1))
            layers.append(f'<rect x="{width * 0.1:.2f}" y="{y - height * 0.035:.2f}" width="{height * 0.03:.2f}" height="{height * 0.03:.2f}" '
                          f'fill="{pal["accent"]}" opacity="{e:.3f}"/>')
            layers.append(_text(width * 0.1 + height * 0.06, y - height * 0.008 + (1 - e) * 12, height * 0.055, pal["ink"], body, point,
                                weight=500, opacity=e))
    else:
        raise ValueError(f"{shot.kind.value} is not a procedural shot")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'{"".join(layers)}</svg>')


def frames_for(shots: list[Shot], genome: CreativeGenome, *, width: int, height: int, fps: int) -> tuple[list[str], list[dict[str, Any]]]:
    frames: list[str] = []
    timeline = []
    for shot in shots:
        if shot.path != "A_PROCEDURAL":
            continue
        n = max(2, int(round(shot.duration_s * fps)))
        start = len(frames)
        frames += [shot_frame(shot, genome, i / (n - 1), width=width, height=height) for i in range(n)]
        timeline.append({"shot_id": shot.shot_id, "start_frame": start, "frames": n, "start_s": start / fps, "end_s": (start + n) / fps})
    return frames, timeline


def webvtt(timeline: list[dict[str, Any]], shots: list[Shot]) -> str:
    def ts(seconds: float) -> str:
        milliseconds = int(Fraction(str(seconds)) * 1000 + Fraction(1, 2))
        if milliseconds < 0:
            raise ValueError("caption time must be nonnegative")
        hours, rest = divmod(milliseconds, 3_600_000)
        minutes, rest = divmod(rest, 60_000)
        whole, millis = divmod(rest, 1000)
        return f"{hours:02d}:{minutes:02d}:{whole:02d}.{millis:03d}"

    by_id = {s.shot_id: s for s in shots}
    cues = ["WEBVTT", "", "NOTE On-screen copy alternative; no spoken audio is implied.", ""]
    for i, entry in enumerate(timeline, start=1):
        shot = by_id[entry["shot_id"]]
        text = " / ".join(" ".join(part.split()) for part in shot.text) or shot.kind.value.replace("_", " ").lower()
        # Literal text only: line breaks or cue delimiters cannot inject new cues.
        cues += [str(i), f"{ts(entry['start_s'])} --> {ts(entry['end_s'])}", escape(text), ""]
    return "\n".join(cues)


def probe_streams(path: Path) -> dict[str, Any]:
    """Probe a staged file in the isolated boundary; unavailable is NOT_RUN."""
    from services.langgraph.agency.ucpo.sandbox import probe_isolation, wrap
    from services.langgraph.agency.visual.file_staging import UnsafeInput, copy_regular_bounded

    executable = shutil.which("ffprobe")
    isolation = probe_isolation()
    if not executable or not isolation.available:
        return {"status": "NOT_RUN", "reason": "ffprobe or isolation unavailable", "streams": []}
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix="amc-vnexus-probe-input-") as inp, tempfile.TemporaryDirectory(prefix="amc-vnexus-probe-") as tmp:
        inputs, work = Path(inp), Path(tmp)
        staged = inputs / "media.bin"
        try:
            copy_regular_bounded(Path(path), staged, max_bytes=256 * 1024 * 1024)
        except (OSError, UnsafeInput):
            return {"status": "FAILED", "reason": "invalid or oversized input", "streams": []}
        cmd = wrap(["/usr/bin/prlimit", "--as=2147483648", "--cpu=60", "--fsize=8388608", "--", executable, "-v", "error",
                    "-protocol_whitelist", "file,pipe", "-count_frames", "-show_entries",
                    "stream=codec_type,codec_name,width,height,duration,avg_frame_rate,nb_read_frames", "-of", "json", str(staged)],
                   cwd=work, home=work, node=isolation.node or "node", timeout_s=60, readonly_paths=(Path(executable), inputs))
        try:
            result_file, error_file = work / "probe.json", work / "probe.err"
            with result_file.open("wb") as result, error_file.open("wb") as errors:
                proc = subprocess.run(cmd, stdout=result, stderr=errors, timeout=90)
            if proc.returncode != 0 or result_file.stat().st_size > 8 * 1024 * 1024:
                return {"status": "FAILED", "reason": "ffprobe failed or output exceeded its budget", "streams": []}
            data = json.loads(result_file.read_text(encoding="utf-8"))
            streams = data.get("streams", []) if isinstance(data, dict) else None
            if not isinstance(streams, list) or len(streams) > 256 or any(not isinstance(s, dict) for s in streams):
                return {"status": "FAILED", "reason": "invalid ffprobe result", "streams": []}
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"status": "FAILED", "reason": type(exc).__name__, "streams": []}
    return {"status": "OK", "streams": streams}


def mux_audio(video: Path, audio: Path, out: Path) -> dict[str, Any]:
    """Mux in isolated scratch, refusing any output that shortens the video."""
    from services.langgraph.agency.ucpo.sandbox import probe_isolation, wrap
    from services.langgraph.agency.visual.file_staging import UnsafeInput, copy_regular_bounded

    executable = shutil.which("ffmpeg")
    isolation = probe_isolation()
    if not executable or not isolation.available:
        return {"status": "NOT_RUN", "reason": "ffmpeg or isolation unavailable"}
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix="amc-vnexus-mux-input-") as inp, tempfile.TemporaryDirectory(prefix="amc-vnexus-mux-work-") as tmp:
        inputs, work = Path(inp), Path(tmp)
        try:
            for source, name in ((video, "video.mp4"), (audio, "audio.bin")):
                copy_regular_bounded(Path(source), inputs / name, max_bytes=256 * 1024 * 1024)
        except (OSError, UnsafeInput):
            return {"status": "FAILED", "reason": "invalid or oversized mux input"}
        original = probe_streams(inputs / "video.mp4")
        original_video = [s for s in original.get("streams", []) if s.get("codec_type") == "video"]
        if original.get("status") != "OK" or len(original_video) != 1 or not str(original_video[0].get("nb_read_frames", "")).isdigit():
            return {"status": "NOT_RUN", "reason": "original video could not be frame-counted"}
        output = work / "muxed.mp4"
        cmd = wrap(["/usr/bin/prlimit", "--as=2147483648", "--cpu=120", "--fsize=268435456", "--", executable, "-nostdin", "-y", "-loglevel", "error",
                    "-protocol_whitelist", "file,pipe", "-i", str(inputs / "video.mp4"), "-protocol_whitelist", "file,pipe",
                    "-i", str(inputs / "audio.bin"), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "128k", "-shortest", str(output)], cwd=work, home=work, node=isolation.node or "node", timeout_s=120,
                   readonly_paths=(Path(executable), inputs))
        log = work / "mux.err"
        try:
            with log.open("wb") as errors:
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=errors, timeout=150)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "FAILED", "reason": type(exc).__name__}
        if proc.returncode != 0 or output.is_symlink() or not output.is_file() or output.stat().st_size > 256 * 1024 * 1024:
            with log.open("rb") as errors:
                errors.seek(max(0, log.stat().st_size - 400))
                detail = errors.read(400).decode("utf-8", "replace")
            return {"status": "FAILED", "reason": "mux failed or output exceeded its budget", "stderr": detail}
        reopened = probe_streams(output)
        streams = reopened.get("streams", [])
        videos = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        keys = ("codec_name", "width", "height", "avg_frame_rate", "nb_read_frames")
        if (reopened.get("status") != "OK" or len(videos) != 1 or len(audio_streams) != 1
                or tuple(videos[0].get(k) for k in keys) != tuple(original_video[0].get(k) for k in keys)):
            return {"status": "FAILED", "reason": "mux changed or could not verify the original video stream"}
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=out.parent, prefix=".amc-mux-", delete=False) as dest:
            temporary = Path(dest.name)
            try:
                with output.open("rb") as source:
                    shutil.copyfileobj(source, dest)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, out)
        finally:
            temporary.unlink(missing_ok=True)
    return {"status": "SUCCEEDED", "streams": ["audio", "video"], "video_frames": original_video[0]["nb_read_frames"]}


def plan(brief: VideoBrief, genome: CreativeGenome) -> dict[str, Any]:
    """Every pre-render stage, deterministic and hashed."""
    s = script(brief, genome.brand_name)
    shots = shot_list(brief, genome.brand_name)
    storyboard = [{"shot_id": sh.shot_id, "kind": sh.kind.value, "path": sh.path, "keyframe_svg_sha":
                   canonical_hash(shot_frame(sh, genome, 1.0, width=brief.width, height=brief.height)) if sh.path == "A_PROCEDURAL" else None}
                  for sh in shots]
    assets = {"available": ["mark (genome)", "wordmark (genome)", "palette (genome)", "typography stacks (genome)"],
              "required_from_providers": [{"shot_id": sh.shot_id, "need": sh.kind.value} for sh in shots if sh.path == "B_AI_PROVIDER"],
              "audio": {"artifact_id": brief.audio_artifact_id, "licence": brief.audio_licence} if brief.audio_artifact_id else None}
    animation = {"easing": "ease_out", "fps": brief.fps, "shots": [{"shot_id": sh.shot_id, "duration_s": sh.duration_s,
                                                                   "camera": sh.camera, "transition": sh.transition} for sh in shots]}
    doc = {"pipeline": VIDEO_PIPELINE, "brief_hash": canonical_hash(brief.model_dump(mode="json")), "genome_hash": genome.content_hash,
           "script": s, "storyboard": storyboard, "shot_list": [sh.model_dump(mode="json") for sh in shots], "asset_plan": assets,
           "animation_plan": animation, "procedural_duration_s": round(sum(sh.duration_s for sh in shots if sh.path == "A_PROCEDURAL"), 3)}
    doc["plan_hash"] = canonical_hash(doc)
    return doc


__all__ = ["PROCEDURAL", "STAGES", "Shot", "ShotKind", "VIDEO_PIPELINE", "VideoBrief", "frames_for", "mux_audio", "plan",
           "probe_streams", "script", "shot_frame", "shot_list", "webvtt"]

