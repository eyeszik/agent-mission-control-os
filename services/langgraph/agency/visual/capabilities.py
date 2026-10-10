"""Observe which local visual routes can actually run on this host.

Each probe looks at the installed thing itself (import, binary, files on disk),
not at configuration flags. Results are cached per process; tests replace
``PROBES`` to simulate hosts.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .contracts import Capability, CapabilityStatus, Route

REPO_ROOT = Path(__file__).resolve().parents[4]
DIFFUSION_MODEL_DIR_ENV = "AMC_LOCAL_DIFFUSION_MODEL_DIR"
MODEL_MANIFEST = "amc-model.json"  # {"license": "...", "weights_sha256": {"file": "sha"}, "source": "..."}


def hardware() -> dict:
    info = {"cpu_count": os.cpu_count(), "gpu": None}
    try:
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        info["memory_gb"] = round(pages * size / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        info["memory_gb"] = None
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=10)
            info["gpu"] = out.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            info["gpu"] = None
    return info


@lru_cache(maxsize=1)
def _blender_version() -> tuple[str | None, str]:
    if importlib.util.find_spec("bpy") is None:
        return None, "bpy (Blender as a Python module) is not installed"
    try:
        out = subprocess.run([sys.executable, "-I", "-c", "import bpy; print(bpy.app.version_string)"],
                             capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None, "bpy import timed out"
    if out.returncode != 0:
        return None, f"bpy failed to import: {out.stderr.strip()[-200:]}"
    return out.stdout.strip().splitlines()[-1], "bpy imports in an isolated interpreter"


def probe_blender() -> Capability:
    version, detail = _blender_version()
    if version is None:
        return Capability(route=Route.BLENDER_CYCLES, status=CapabilityStatus.BLOCKED_ENVIRONMENT, detail=detail,
                          hardware=hardware(), blockers=("BLOCKED_ENVIRONMENT:blender",))
    return Capability(route=Route.BLENDER_CYCLES, status=CapabilityStatus.VERIFIED_AVAILABLE, version=version,
                      detail=f"{detail}; Cycles on CPU", hardware=hardware())


def probe_diffusion() -> Capability:
    blockers: list[str] = []
    for module in ("torch", "diffusers"):
        if importlib.util.find_spec(module) is None:
            blockers.append(f"MISSING_DEPENDENCY:{module}")
    raw = os.environ.get(DIFFUSION_MODEL_DIR_ENV, "").strip()
    if not raw:
        blockers.append(f"NO_LOCAL_MODEL: {DIFFUSION_MODEL_DIR_ENV} is not set")
    else:
        model_dir = Path(raw)
        if not (model_dir / "model_index.json").is_file():
            blockers.append("NO_LOCAL_MODEL: model_index.json missing in the model directory")
        manifest = model_dir / MODEL_MANIFEST
        if not manifest.is_file():
            blockers.append(f"NO_LICENSE_RECORD: {MODEL_MANIFEST} missing (licence and weight hashes)")
        else:
            try:
                data = json.loads(manifest.read_text())
            except json.JSONDecodeError:
                data = {}
            if not data.get("license"):
                blockers.append("NO_LICENSE_RECORD: licence not stated")
            if not data.get("weights_sha256"):
                blockers.append("UNVERIFIED_WEIGHTS: weight hashes not recorded")
    if blockers:
        return Capability(route=Route.OFFLINE_DIFFUSION, status=CapabilityStatus.BLOCKED_LOCAL_MODEL,
                          detail="; ".join(blockers), hardware=hardware(), blockers=tuple(blockers))
    return Capability(route=Route.OFFLINE_DIFFUSION, status=CapabilityStatus.VERIFIED_AVAILABLE,
                      detail="local weights with licence record", hardware=hardware())


def probe_three() -> Capability:
    blockers = []
    pkg = REPO_ROOT / "apps" / "web" / "node_modules" / "three" / "package.json"
    declared = json.loads((REPO_ROOT / "apps" / "web" / "package.json").read_text()) if (REPO_ROOT / "apps/web/package.json").is_file() else {}
    deps = {**declared.get("dependencies", {}), **declared.get("devDependencies", {})}
    if "three" not in deps:
        blockers.append("MISSING_DEPENDENCY:three (not a declared apps/web dependency)")
    if not pkg.is_file():
        blockers.append("MISSING_DEPENDENCY:three (not installed)")
    if blockers:
        return Capability(route=Route.THREE_JS, status=CapabilityStatus.MISSING_DEPENDENCIES, detail="; ".join(blockers),
                          blockers=tuple(blockers))
    version = json.loads(pkg.read_text()).get("version")
    return Capability(route=Route.THREE_JS, status=CapabilityStatus.VERIFIED_AVAILABLE, version=version,
                      detail="three installed; renderer choice depends on the scene's shader architecture")


def probe_vector() -> Capability:
    return Capability(route=Route.VECTOR, status=CapabilityStatus.VERIFIED_AVAILABLE, version="agency.assets",
                      detail="deterministic SVG templates (pure Python)")


def probe_video() -> Capability:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        return Capability(route=Route.LOCAL_VIDEO, status=CapabilityStatus.BLOCKED_ENVIRONMENT,
                          detail=f"missing {', '.join(missing)}", blockers=tuple(f"BLOCKED_ENVIRONMENT:{m}" for m in missing))
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=30)
    version = (out.stdout.splitlines() or ["ffmpeg"])[0]
    return Capability(route=Route.LOCAL_VIDEO, status=CapabilityStatus.VERIFIED_AVAILABLE, version=version,
                      detail="frames rendered locally, encoded with FFmpeg, measured with ffprobe")


PROBES: dict[Route, Callable[[], Capability]] = {
    Route.BLENDER_CYCLES: probe_blender,
    Route.OFFLINE_DIFFUSION: probe_diffusion,
    Route.THREE_JS: probe_three,
    Route.VECTOR: probe_vector,
    Route.LOCAL_VIDEO: probe_video,
}


def probe_all() -> dict[Route, Capability]:
    return {route: probe() for route, probe in PROBES.items()}


__all__ = ["DIFFUSION_MODEL_DIR_ENV", "MODEL_MANIFEST", "PROBES", "hardware", "probe_all"]
