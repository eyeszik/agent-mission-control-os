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

import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from pydantic import Field

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
                  camera="slow push-in (scale 1.00 -> 1.04)", transition="crossfade 0.4s", path="A_PROCEDURAL")]
    if brief.points:
        shots.append(Shot(shot_id="s3", kind=ShotKind.VALUE_POINTS, duration_s=1.2 * len(brief.points) + 0.8, text=brief.points,
                          camera="static; points stagger in", transition="crossfade 0.4s", path="A_PROCEDURAL"))
    for i, kind in enumerate(brief.include_shots):
        shots.append(Shot(shot_id=f"x{i + 1}", kind=kind, duration_s=3.0, camera="unspecified", transition="cut",
                          path="A_PROCEDURAL" if kind in PROCEDURAL else "B_AI_PROVIDER"))
    shots.append(Shot(shot_id="s9", kind=ShotKind.CALL_TO_ACTION, duration_s=2.5, text=(brief.cta or "[CALL TO ACTION NOT PROVIDED]",),
                      camera="static", transition="fade to paper", path="A_PROCEDURAL"))
    budget, kept = brief.max_duration_s, []
    for shot in shots:
        if shot.path == "B_AI_PROVIDER" or sum(s.duration_s for s in kept if s.path == "A_PROCEDURAL") + shot.duration_s <= budget + 1e-9:
            kept.append(shot)
    return kept


def _ease(t: float) -> float:
    return EASING["ease_out"](max(0.0, min(1.0, t)))


def _text(x: float, y: float, size: float, fill: str, family: str, text: str, *, weight: int = 700, opacity: float = 1.0,
          anchor: str = "start") -> str:
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="{escape(family, {chr(34): "&quot;"})}" font-size="{size:.2f}" '
            f'font-weight="{weight}" fill="{fill}" opacity="{opacity:.3f}" text-anchor="{anchor}">{escape(text)}</text>')


def shot_frame(shot: Shot, genome: CreativeGenome, t: float, *, width: int, height: int) -> str:
    """One frame of a procedural shot at local time t in [0, 1]. Pure."""
    pal = genome.palette.roles()
    display = ", ".join(genome.typography_rules["stacks"]["display"])
    body = ", ".join(genome.typography_rules["stacks"]["text"])
    layers: list[str] = [f'<rect width="{width}" height="{height}" fill="{pal["paper"]}"/>']
    if shot.kind is ShotKind.MARK_REVEAL:
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
        size = height * (0.11 if shot.kind is ShotKind.HEADLINE else 0.09)
        words, lines, line = shot.text[0].split(), [], ""
        for w in words:
            if len(line + " " + w) * size * 0.55 > width * 0.8 and line:
                lines.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        lines.append(line)
        y0 = height / 2 - (len(lines) - 1) * size * 0.6
        g = "".join(_text(width * 0.1, y0 + i * size * 1.15, size, pal["ink"], display, ln, opacity=_ease((t - i * 0.1) / 0.35))
                    for i, ln in enumerate(lines))
        layers.append(f'<g transform="translate({width / 2:.2f} {height / 2:.2f}) scale({zoom:.4f}) translate({-width / 2:.2f} {-height / 2:.2f})">{g}</g>')
        layers.append(f'<rect x="{width * 0.1:.2f}" y="{y0 + len(lines) * size * 1.15 - size * 0.4:.2f}" '
                      f'width="{width * 0.3 * _ease(t / 0.7):.2f}" height="{max(4, height * 0.012):.2f}" fill="{pal["accent"]}"/>')
    elif shot.kind is ShotKind.VALUE_POINTS:
        n = len(shot.text)
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
    def ts(s: float) -> str:
        return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{s % 60:06.3f}"

    by_id = {s.shot_id: s for s in shots}
    cues = ["WEBVTT", ""]
    for i, entry in enumerate(timeline, start=1):
        text = " / ".join(by_id[entry["shot_id"]].text) or by_id[entry["shot_id"]].kind.value.replace("_", " ").lower()
        cues += [str(i), f"{ts(entry['start_s'])} --> {ts(entry['end_s'])}", text, ""]
    return "\n".join(cues)


def mux_audio(video: Path, audio: Path, out: Path) -> dict[str, Any]:
    """Copy the video stream, encode the supplied audio to AAC, stop at the shorter input."""
    if shutil.which("ffmpeg") is None:
        return {"status": "NOT_RUN", "reason": "ffmpeg missing"}
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    ok = proc.returncode == 0 and out.is_file()
    return {"status": "SUCCEEDED" if ok else "FAILED", "stderr": proc.stderr[-400:]}


def probe_streams(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        return {"status": "NOT_RUN"}
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,duration",
                           "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    import json

    data = json.loads(proc.stdout or "{}")
    return {"status": "OK" if proc.returncode == 0 else "FAILED", "streams": data.get("streams", [])}


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

