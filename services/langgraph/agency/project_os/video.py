"""Governed bridge: cinematic compiler → FreeVideoForge → project artifacts.

Neither side is rewritten. The cinematic capability compiles a request into a
ProjectIR with ShotIR shots and prompts and stops at its generation firewall
(``PROMPT_PACKAGE_READY``). FreeVideoForge renders locally with no paid API.
This module only translates between them and back into the project graph:

1. :func:`plan_video_production` runs the cinematic pipeline, normalizes shot
   metadata, and builds a FreeVideoForge ``GenerateRequest`` payload.
2. Rendering happens out of band (``freevideoforge generate`` or the
   ``video-production`` skill). :func:`freevideoforge_capability` discovers
   whether this machine can render at all; it never assumes.
3. :func:`read_freevideoforge_output` reads a finished run directory using
   FreeVideoForge's documented output contract (seven files) and returns what
   to register: the master video, thumbnail, script, storyboard, captions and
   QC report, with shot metadata and a reproducibility record.

FreeVideoForge is read by file contract, not imported: its package imports
Pillow at load time, and the bridge must work where rendering is unavailable.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Optional

from .models import ReproducibilityRecord
from .workspace import canonical_json, sha256_bytes

VIDEO_PIPELINE_STAGES: tuple[str, ...] = (
    "IDEA", "RESEARCH", "PREMISE", "CHARACTER_BIBLE", "WORLD_BIBLE", "TREATMENT", "SCRIPT", "BEAT_SHEET",
    "SCENES", "STORYBOARD", "PREVIZ", "SHOT_LIST", "SHOT_IR", "PROMPT_COMPILE", "PROVIDER_ROUTE", "GENERATION",
    "INGEST", "VOICE", "MUSIC", "SOUND", "EDIT", "MOTION_VFX", "COLOR", "CAPTIONS", "QC", "MASTER",
    "PLATFORM_VARIANTS", "THUMBNAILS", "DISTRIBUTION", "ARCHIVE",
)

# Stages the cinematic compiler completes before its firewall.
_CINEMATIC_STAGES = {"PREMISE", "CHARACTER_BIBLE", "WORLD_BIBLE", "SCENES", "STORYBOARD", "SHOT_LIST", "SHOT_IR", "PROMPT_COMPILE"}
# Stages FreeVideoForge performs in one local run.
_FVF_STAGES = {"GENERATION", "VOICE", "MUSIC", "EDIT", "CAPTIONS", "QC", "MASTER", "THUMBNAILS"}

FVF_OUTPUTS = {
    "final.mp4": ("video/mp4", "video_master"),
    "thumbnail.jpg": ("image/jpeg", "thumbnail"),
    "script.json": ("application/json", "video_script"),
    "storyboard.json": ("application/json", "storyboard"),
    "captions.srt": ("application/x-subrip", "captions"),
    "manifest.json": ("application/json", "provenance"),
    "quality-report.json": ("application/json", "video_qc"),
}
FVF_REQUEST_FIELDS = (
    "topic", "brief", "duration", "aspect", "preset", "style", "scenes", "fps", "height", "voice", "music", "seed",
    "language", "burn_captions", "output_dir", "run_id", "allow_paid", "script_provider", "speech_provider", "quality_preset",
)
_ASPECTS = {"9:16", "1:1", "16:9", "4:5"}


class VideoBridgeError(ValueError):
    pass


def freevideoforge_capability() -> dict[str, Any]:
    """Discover, never assume. Reports exactly what would block a local render."""
    root = Path(__file__).resolve().parents[4] / "services" / "freevideoforge"
    package_present = (root / "freevideoforge" / "__init__.py").is_file()
    pillow = importlib.util.find_spec("PIL") is not None
    ffmpeg = shutil.which("ffmpeg") is not None
    ffprobe = shutil.which("ffprobe") is not None
    blockers = []
    if not package_present:
        blockers.append("FreeVideoForge package not found in services/freevideoforge")
    if not pillow:
        blockers.append("Pillow is not installed (pip install pillow)")
    if not ffmpeg:
        blockers.append("FFmpeg is not installed")
    if not ffprobe:
        blockers.append("ffprobe is not installed (needed for the structural QC gate)")
    return {
        "provider": "freevideoforge",
        "locality": "local",
        "paid_api": False,
        "package_present": package_present,
        "pillow": pillow,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "can_render": not blockers,
        "blockers": blockers,
        "status": "LOCAL_ONLY" if not blockers else "NOT_AVAILABLE",
    }


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _shot_meta(shot: Any, prompts_by_shot: Mapping[str, str]) -> dict[str, Any]:
    data = shot.model_dump(mode="json") if hasattr(shot, "model_dump") else dict(shot)
    camera = data.get("camera") or {}
    return {
        "shot_id": data.get("id"),
        "scene_id": (data.get("location") or {}).get("scene_id"),
        "character_state": data.get("character_state") or {},
        "start_state": data.get("start_frame") or {},
        "end_state": data.get("final_frame") or {},
        "camera": {"size": data.get("shot_size"), "angle": data.get("angle"), **camera},
        "lens": data.get("lens"),
        "movement": camera.get("move") or camera.get("movement"),
        "lighting": data.get("light") or {},
        "environment": {"location": data.get("location") or {}, "atmosphere": data.get("atmosphere") or {}},
        "performance": data.get("performance") or {},
        "dialogue": data.get("dialogue"),
        "duration": data.get("duration"),
        "references": list(data.get("identity_refs") or []),
        "prompt": prompts_by_shot.get(str(data.get("id"))),
        "model_profile": "portable",
        "seed": None,
        "generation_refs": [],
        "continuity_refs": data.get("continuity") or {},
        "qc": {"failure_risks": list(data.get("failure_risks") or [])},
    }


def plan_video_production(
    cinematic_request: Mapping[str, Any],
    *,
    aspect: str = "9:16",
    duration: Optional[float] = None,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    from services.langgraph.agency.cinematic import CinematicRequest, run_pipeline

    if aspect not in _ASPECTS:
        raise VideoBridgeError(f"aspect must be one of {sorted(_ASPECTS)}")
    result = run_pipeline(CinematicRequest.model_validate(dict(cinematic_request)))
    project = result.project
    shots = list(project.shots) if project is not None else []
    prompts_by_shot: dict[str, str] = {}
    for prompt in result.prompts:
        data = prompt.model_dump(mode="json")
        shot_id = str(data.get("shot_id") or data.get("ref") or "")
        text = data.get("text") or data.get("prompt") or ""
        if shot_id and text:
            prompts_by_shot[shot_id] = text
    shot_meta = [_shot_meta(shot, prompts_by_shot) for shot in shots]
    meta = _as_dict(getattr(project, "meta", None))
    story = _as_dict(getattr(project, "story", None))
    title = str(meta.get("title") or (cinematic_request.get("text") or "Untitled film"))[:120]
    beats = [beat.get("summary") for scene in (story.get("scenes") or []) for beat in (scene.get("beats") or []) if beat.get("summary")]
    shot_seconds = sum(float(s["duration"]) for s in shot_meta if isinstance(s.get("duration"), (int, float)))
    total = duration or (shot_seconds if 3.0 <= shot_seconds <= 600.0 else 30.0)
    fvf_request = {
        "topic": title,
        "brief": " ".join(beats)[:4000] or str(story.get("logline") or ""),
        "duration": float(total),
        "aspect": aspect,
        "scenes": max(1, min(len(shot_meta) or 1, 60)),
        "seed": seed,
        "allow_paid": False,
    }
    assert set(fvf_request) <= set(FVF_REQUEST_FIELDS)
    capability = freevideoforge_capability()
    stages = []
    for stage in VIDEO_PIPELINE_STAGES:
        if stage in _CINEMATIC_STAGES:
            status = "COMPLETE" if result.generative else "SKIPPED_NON_GENERATIVE"
        elif stage == "PROVIDER_ROUTE":
            status = "ROUTED_LOCAL" if capability["can_render"] else "BLOCKED_NO_LOCAL_RENDERER"
        elif stage in _FVF_STAGES:
            status = "PENDING_LOCAL_RENDER" if capability["can_render"] else "BLOCKED_NO_LOCAL_RENDERER"
        elif stage == "INGEST":
            status = "AWAITING_RENDER_OUTPUT"
        elif stage in {"DISTRIBUTION"}:
            status = "VIA_PUBLICATION_PIPELINE"
        else:
            status = "MANUAL_OR_NOT_COVERED"
        stages.append({"stage": stage, "status": status})
    return {
        "title": title,
        "generation_firewall": result.generation_firewall,
        "cinematic_mode": str(result.mode.value if hasattr(result.mode, "value") else result.mode),
        "shots": shot_meta,
        "storyboard_panels": len(result.storyboard),
        "unresolved": list(result.unresolved),
        "freevideoforge_request": fvf_request,
        "renderer": capability,
        "stages": stages,
        "plan_hash": sha256_bytes(canonical_json({"request": fvf_request, "shots": shot_meta})),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_freevideoforge_output(output_dir: Path) -> dict[str, Any]:
    """Validate a finished FreeVideoForge run directory against its contract."""
    output_dir = Path(output_dir)
    missing = [name for name in FVF_OUTPUTS if not (output_dir / name).is_file()]
    if missing:
        raise VideoBridgeError(f"not a complete FreeVideoForge run: missing {', '.join(missing)}")
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    quality = json.loads((output_dir / "quality-report.json").read_text(encoding="utf-8"))
    storyboard = json.loads((output_dir / "storyboard.json").read_text(encoding="utf-8"))
    for key in ("run_id", "version", "config_hash", "providers", "assets", "environment"):
        if key not in manifest:
            raise VideoBridgeError(f"manifest.json lacks required key {key!r}")
    if manifest.get("zero_paid_api_spend") is not True:
        raise VideoBridgeError("run did not certify zero paid-API spend; refusing to ingest as a local render")
    files = {
        name: {"path": str(output_dir / name), "sha256": _sha256_file(output_dir / name), "bytes": (output_dir / name).stat().st_size,
               "mime_type": mime, "subtype": subtype}
        for name, (mime, subtype) in FVF_OUTPUTS.items()
    }
    project = manifest.get("project") or {}
    scenes = storyboard.get("scenes") if isinstance(storyboard, dict) else storyboard
    seeds = sorted({asset.get("seed") for asset in manifest.get("assets") or [] if isinstance(asset, dict) and asset.get("seed") is not None})
    checks = quality.get("checks") or []
    failed = [check.get("name") for check in checks if isinstance(check, dict) and check.get("status") == "FAIL"]
    record = ReproducibilityRecord(
        subject_ref=f"freevideoforge:{manifest['run_id']}",
        source_hashes=tuple(sorted(item["sha256"] for name, item in files.items() if name in {"script.json", "storyboard.json"})),
        schema_version=str(manifest.get("version")),
        provider="freevideoforge",
        model=",".join(sorted(str(v) for v in (manifest.get("providers") or {}).values() if isinstance(v, str))) or None,
        seed=seeds[0] if len(seeds) == 1 else None,
        generation_config_hash=str(manifest.get("config_hash")) if manifest.get("config_hash") else None,
        tool_contract_version=str(manifest.get("version")),
        environment_signature=sha256_bytes(canonical_json(manifest.get("environment") or {})),
        execution_args_hash=sha256_bytes(canonical_json(project)),
        output_hash=files["final.mp4"]["sha256"],
        guarantee="SEEDED_BEST_EFFORT" if seeds else "DETERMINISTIC_PIPELINE",
    )
    return {
        "run_id": manifest["run_id"],
        "files": files,
        "qc": {"status": "FAIL" if failed else "PASS_OR_NOT_VERIFIED", "failed_checks": failed, "check_count": len(checks)},
        "duration_seconds": (project.get("render") or {}).get("duration") or project.get("duration"),
        "aspect": (project.get("render") or {}).get("aspect") or project.get("aspect"),
        "scene_count": len(scenes or []),
        "reproducibility": record,
    }
