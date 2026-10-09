"""Run the local renderers as isolated subprocesses and collect their real outputs.

* R1 Blender Cycles: ``blender_runner.py`` under ``python -I``.
* R5 local video: R1 renders the frames, FFmpeg encodes them, nothing else.
* R2 offline diffusion: ``diffusion_runner.py`` with Hugging Face offline
  flags and ``local_files_only``; only reached when the capability probe found
  local weights with a licence record.

When the host supports it, each process runs in its own network namespace
(``unshare -rn``), so "no remote request" is enforced by the kernel, not just
promised. The receipt records whether that isolation was in force.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from services.langgraph.agency.execution_fabric.adapters.code_sandbox import network_namespace_available

from .capabilities import DIFFUSION_MODEL_DIR_ENV, hardware
from .contracts import RenderReceipt, Route, VisualGenome, VisualIntent

HERE = Path(__file__).resolve().parent
BLENDER_TIMEOUT_S = 1800
FFMPEG_TIMEOUT_S = 300
DIFFUSION_TIMEOUT_S = 3600
_ENV_KEEP = ("PATH", "LANG", "HOME", "TMPDIR")


def _env(extra: Optional[dict] = None) -> dict:
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env.setdefault("PATH", "/usr/bin:/bin")
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
                "NO_PROXY": "*", "no_proxy": "*"})
    for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        env.pop(proxy, None)
    env.update(extra or {})
    return env


def _isolated(cmd: list[str]) -> tuple[list[str], bool]:
    if network_namespace_available():
        return [shutil.which("unshare") or "unshare", "-rn", *cmd], True
    return cmd, False


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def scene_spec(intent: VisualIntent) -> dict:
    turntable = intent.output == "video"
    return {
        "palette": intent.palette,
        "render": {"width": intent.width, "height": intent.height, "samples": intent.samples, "seed": intent.seed,
                   "threads": max(1, os.cpu_count() or 1)},
        "camera": {"focal_mm": 85, "fstop": 2.8, "distance": 3.4, "height": 1.15, "azimuth_deg": -62},
        "frames": intent.frames if turntable else 1,
        "turntable_sweep_deg": 40 if turntable else 0,
    }


def render_blender(intent: VisualIntent, out_dir: Path, *, logical_tick: Optional[int] = None,
                   timeout_s: int = BLENDER_TIMEOUT_S) -> RenderReceipt:
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = scene_spec(intent)
    spec_path = out_dir / "scene-spec.json"
    spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True))
    cmd, isolated = _isolated([sys.executable, "-I", str(HERE / "blender_runner.py"), str(spec_path), str(out_dir)])
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=_env())
    except subprocess.TimeoutExpired:
        return RenderReceipt(route=Route.BLENDER_CYCLES, status="FAILED", command=tuple(cmd), observed_at=_now(),
                             reasons=(f"TIMEOUT_AFTER_{timeout_s}S",), logical_tick=logical_tick, network_isolated=isolated)
    wall_ms = int((time.monotonic() - started) * 1000)
    scene_json = out_dir / "scene.json"
    if proc.returncode != 0 or not scene_json.is_file():
        tail = (proc.stderr or proc.stdout or "")[-400:]
        return RenderReceipt(route=Route.BLENDER_CYCLES, status="FAILED", command=tuple(cmd), exit_code=proc.returncode,
                             wall_ms=wall_ms, observed_at=_now(), reasons=(f"RENDERER_EXIT_{proc.returncode}", tail),
                             logical_tick=logical_tick, network_isolated=isolated)
    scene = json.loads(scene_json.read_text())
    outputs = tuple({"path": str(out_dir / f), "sha256": _sha(out_dir / f), "bytes": (out_dir / f).stat().st_size}
                    for f in scene["frames"])
    genome = VisualGenome(
        route=Route.BLENDER_CYCLES, renderer="blender_cycles", renderer_version=scene["blender_version"],
        scene_spec_sha256=_sha(spec_path), geometry="procedural spool, thread, needle, folded wool, plaster wall",
        materials=tuple(scene["materials"]), camera=spec["camera"], lights=("area 'north window' key", "world fill"),
        seed=intent.seed, samples=intent.samples, source_assets=intent.source_assets, hardware=hardware(),
        color_management={k: scene["render"].get(k) for k in ("view_transform", "look", "denoiser")},
    )
    return RenderReceipt(route=Route.BLENDER_CYCLES, status="SUCCEEDED", outputs=outputs, genome=genome,
                         command=tuple(cmd), exit_code=0, wall_ms=wall_ms, observed_at=_now(),
                         logical_tick=logical_tick, network_isolated=isolated)


def encode_video(frames: list[Path], out_path: Path, *, fps: int, logical_tick: Optional[int] = None) -> RenderReceipt:
    if not frames:
        return RenderReceipt(route=Route.LOCAL_VIDEO, status="FAILED", observed_at=_now(), reasons=("NO_FRAMES",))
    pattern = str(frames[0].parent / "frame_%04d.png")
    cmd, isolated = _isolated([shutil.which("ffmpeg") or "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                               "-i", pattern, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                               "-crf", "18", str(out_path)])
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S, env=_env())
    wall_ms = int((time.monotonic() - started) * 1000)
    if proc.returncode != 0 or not out_path.is_file():
        return RenderReceipt(route=Route.LOCAL_VIDEO, status="FAILED", command=tuple(cmd), exit_code=proc.returncode,
                             wall_ms=wall_ms, observed_at=_now(), reasons=(proc.stderr[-400:],), network_isolated=isolated)
    return RenderReceipt(route=Route.LOCAL_VIDEO, status="SUCCEEDED", command=tuple(cmd), exit_code=0, wall_ms=wall_ms,
                         outputs=({"path": str(out_path), "sha256": _sha(out_path), "bytes": out_path.stat().st_size},),
                         observed_at=_now(), logical_tick=logical_tick, network_isolated=isolated)


def render_diffusion(intent: VisualIntent, prompt: str, out_dir: Path, *, logical_tick: Optional[int] = None) -> RenderReceipt:
    """Only called after probe_diffusion() reported VERIFIED_AVAILABLE."""
    model_dir = os.environ.get(DIFFUSION_MODEL_DIR_ENV, "")
    out_dir.mkdir(parents=True, exist_ok=True)
    job = out_dir / "diffusion-job.json"
    job.write_text(json.dumps({"model_dir": model_dir, "prompt": prompt, "seed": intent.seed, "steps": intent.samples,
                               "width": intent.width, "height": intent.height}, sort_keys=True))
    cmd, isolated = _isolated([sys.executable, "-I", str(HERE / "diffusion_runner.py"), str(job), str(out_dir)])
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=DIFFUSION_TIMEOUT_S, env=_env())
    except subprocess.TimeoutExpired:
        return RenderReceipt(route=Route.OFFLINE_DIFFUSION, status="FAILED", observed_at=_now(), reasons=("TIMEOUT",),
                             network_isolated=isolated)
    wall_ms = int((time.monotonic() - started) * 1000)
    result = out_dir / "image.png"
    if proc.returncode != 0 or not result.is_file():
        return RenderReceipt(route=Route.OFFLINE_DIFFUSION, status="FAILED", command=tuple(cmd), exit_code=proc.returncode,
                             wall_ms=wall_ms, observed_at=_now(), reasons=(proc.stderr[-400:],), network_isolated=isolated)
    meta = json.loads((out_dir / "diffusion.json").read_text())
    genome = VisualGenome(route=Route.OFFLINE_DIFFUSION, renderer="diffusers", renderer_version=meta.get("diffusers", "?"),
                          geometry="none (latent diffusion)", materials=(), camera={}, lights=(),
                          model_weights=meta.get("model"), seed=intent.seed, samples=intent.samples, hardware=hardware(),
                          source_assets=intent.source_assets)
    return RenderReceipt(route=Route.OFFLINE_DIFFUSION, status="SUCCEEDED", command=tuple(cmd), exit_code=0, wall_ms=wall_ms,
                         outputs=({"path": str(result), "sha256": _sha(result), "bytes": result.stat().st_size},),
                         genome=genome, observed_at=_now(), logical_tick=logical_tick, network_isolated=isolated)



def render_vector_mark(intent: VisualIntent, out_dir: Path, *, logical_tick: Optional[int] = None) -> RenderReceipt:
    """R4: the existing deterministic SVG template (``agency.assets``), unchanged, with the intent's palette."""
    from services.langgraph.agency.assets import render_logo_svg

    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    svg = render_logo_svg(brand_name=intent.subject or "Brand", primary=intent.palette["primary"],
                          secondary=intent.palette["secondary"], surface=intent.palette["surface"])
    out = out_dir / "mark.svg"
    out.write_text(svg, encoding="utf-8")
    genome = VisualGenome(route=Route.VECTOR, renderer="agency.assets.render_logo_svg", renderer_version="deterministic",
                          scene_spec_sha256=hashlib.sha256(json.dumps(intent.model_dump(mode="json"), sort_keys=True).encode()).hexdigest(),
                          geometry="rounded square, triangle, circle, initials", materials=(), camera={}, lights=(),
                          seed=0, hardware={})
    return RenderReceipt(route=Route.VECTOR, status="SUCCEEDED", genome=genome, logical_tick=logical_tick,
                         outputs=({"path": str(out), "sha256": _sha(out), "bytes": out.stat().st_size},),
                         wall_ms=int((time.monotonic() - start) * 1000), observed_at=_now(), network_isolated=None)

__all__ = ["encode_video", "render_blender", "render_diffusion", "render_vector_mark", "scene_spec"]
