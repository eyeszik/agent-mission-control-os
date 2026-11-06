"""Environment diagnosis.

``freevideoforge doctor`` answers one question honestly: what can this machine
actually do right now, and what exactly would I have to install to do more?

It never installs anything, never downloads a model and never contacts a paid
service. Every "unavailable" line carries the command that would fix it.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg import FFTools
from .providers.registry import TIER_FFMPEG_MOTION, TIER_LETTER, build_default_registry
from .version import __version__

TIER_DESCRIPTION = {
    "A": "local generative video (a local video model is reachable)",
    "B": "local image generation plus procedural animation",
    "C": "deterministic CPU renderer (procedural motion graphics)",
}


def collect(workspace: str | Path | None = None, *, allow_paid: bool = False) -> dict[str, Any]:
    """Gather a full diagnosis as structured data."""
    settings = Settings.resolve(workspace, allow_paid=allow_paid)
    tools = FFTools(settings.ffmpeg_path, settings.ffprobe_path)
    registry = build_default_registry(settings, allow_paid=settings.allow_paid_providers)
    summary = registry.summary()

    try:
        from PIL import Image  # noqa: F401
        import PIL

        pillow_version = PIL.__version__
    except ImportError:
        pillow_version = None

    from .visuals.fonts import FontBook

    fonts = FontBook(settings.font_dirs)
    font_report = fonts.report()

    disk = shutil.disk_usage(
        settings.workspace if settings.workspace.exists() else Path.cwd()
    )
    tier = summary["visual_tier"]
    letter = TIER_LETTER.get(tier, "C")

    blockers: list[str] = []
    if pillow_version is None:
        blockers.append("Pillow is not installed. Fix: pip install pillow")
    if not tools.ffmpeg:
        blockers.append(
            "ffmpeg was not found. Fix: sudo apt-get install -y ffmpeg "
            "(or: pip install imageio-ffmpeg)"
        )
    if not tools.ffprobe:
        blockers.append(
            "ffprobe was not found. Structural QC needs it. "
            "Fix: sudo apt-get install -y ffmpeg"
        )
    if disk.free < settings.governor.min_free_disk_mb * 1024 * 1024:
        blockers.append(
            f"Only {disk.free // (1024 * 1024)} MB free at {settings.workspace}; "
            f"need {settings.governor.min_free_disk_mb} MB."
        )

    speech = [c for c in summary["active"] if c["kind"] == "speech"]
    real_speech = [c for c in speech if c["name"] != "silence"]

    return {
        "schema_version": "freevideoforge/doctor/v1",
        "version": __version__,
        "can_render": not blockers,
        "blockers": blockers,
        "capability_tier": letter,
        "capability_tier_description": TIER_DESCRIPTION[letter],
        "visual_tier": tier,
        "fallback_provider": TIER_FFMPEG_MOTION,
        "zero_required_api_spend": True,
        "zero_required_credentials": True,
        "credentials_read": [],
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "render_workers": settings.governor.resolve_workers(),
            "disk_free_mb": disk.free // (1024 * 1024),
        },
        "toolchain": {
            "ffmpeg": tools.ffmpeg,
            "ffmpeg_version": tools.version("ffmpeg"),
            "ffprobe": tools.ffprobe,
            "ffprobe_version": tools.version("ffprobe"),
            "pillow": pillow_version,
            "fonts": font_report,
            "font_degraded": all(value is None for value in font_report.values()),
        },
        "workspace": {
            "root": str(settings.workspace),
            "output": str(settings.output_root),
            "state_db": str(settings.db_path),
            "state_json": str(settings.state_json_path),
        },
        "security": {
            "remote_url_fetching": settings.allow_remote_fetch,
            "paid_providers_allowed": settings.allow_paid_providers,
        },
        "providers": summary,
        "narration": {
            "real_tts_available": bool(real_speech),
            "engines": [c["name"] for c in real_speech],
            "note": (
                "Real local TTS is available."
                if real_speech
                else "No local TTS engine found. Narration will be timed silence "
                     "until you install espeak-ng or Piper."
            ),
        },
    }


def render_text(report: dict[str, Any]) -> str:
    """Human-readable doctor output."""
    lines: list[str] = []
    ok = "OK" if report["can_render"] else "BLOCKED"
    lines.append(f"FreeVideoForge {report['version']} - doctor")
    lines.append("=" * 62)
    lines.append(f"Status              : {ok}")
    lines.append(
        f"Capability tier     : {report['capability_tier']} "
        f"({report['capability_tier_description']})"
    )
    lines.append(f"Fallback renderer   : {report['fallback_provider']} (always available)")
    lines.append("Paid APIs required  : none")
    lines.append("Credentials required: none")
    lines.append("")

    host = report["host"]
    lines.append("Host")
    lines.append(f"  platform      {host['platform']}")
    lines.append(f"  python        {host['python']}")
    lines.append(f"  cpu / workers {host['cpu_count']} / {host['render_workers']}")
    lines.append(f"  disk free     {host['disk_free_mb']} MB")
    lines.append("")

    tool = report["toolchain"]
    lines.append("Toolchain")
    lines.append(f"  ffmpeg        {tool['ffmpeg'] or 'NOT FOUND'}")
    lines.append(f"  ffprobe       {tool['ffprobe'] or 'NOT FOUND'}")
    lines.append(f"  pillow        {tool['pillow'] or 'NOT FOUND'}")
    display = tool["fonts"].get("display_bold")
    lines.append(f"  display font  {display or 'none (falling back to bitmap type)'}")
    lines.append("")

    lines.append("Providers - active")
    for cap in report["providers"]["active"]:
        version = f" [{cap['version']}]" if cap.get("version") else ""
        lines.append(f"  + {cap['kind']:10} {cap['name']:14}{version} {cap['detail']}")
    lines.append("")

    unavailable = report["providers"]["unavailable"]
    if unavailable:
        lines.append("Providers - unavailable (each with the exact fix)")
        for cap in unavailable:
            lines.append(f"  - {cap['kind']:10} {cap['name']:14} {cap['detail']}")
            for line in (cap.get("remediation") or "").splitlines():
                if line.strip():
                    lines.append(f"      {line}")
        lines.append("")

    lines.append(f"Narration: {report['narration']['note']}")
    lines.append("")

    if report["blockers"]:
        lines.append("Blockers")
        for blocker in report["blockers"]:
            lines.append(f"  ! {blocker}")
    else:
        lines.append("No blockers. You can render right now:")
        lines.append('  freevideoforge generate --topic "Why the moon changes shape" '
                     "--duration 30 --aspect 9:16 --preset auto")
    return "\n".join(lines)
