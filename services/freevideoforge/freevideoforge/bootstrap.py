"""Environment bootstrap.

``bootstrap`` verifies what FreeVideoForge needs, creates the workspace, and
prints the exact commands for anything missing. It deliberately does **not**
install system packages or download models on your behalf: those are decisions
with licence, disk and security consequences that belong to a human.

The one thing it will offer to do is the project-local pip install of Pillow and
the optional static ffmpeg wheel, and only when you ask with ``--install``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any, Optional

from . import doctor
from .config import Settings

INSTALL_COMMANDS = {
    "pillow": [sys.executable, "-m", "pip", "install", "pillow"],
    "imageio-ffmpeg": [sys.executable, "-m", "pip", "install", "imageio-ffmpeg"],
}


def plan(workspace: Optional[str] = None) -> dict[str, Any]:
    """What is present, what is missing, and the command that fixes each gap."""
    report = doctor.collect(workspace)
    steps: list[dict[str, Any]] = []

    if report["toolchain"]["pillow"] is None:
        steps.append({
            "id": "pillow", "required": True,
            "why": "Pillow renders every frame.",
            "command": " ".join(INSTALL_COMMANDS["pillow"]),
            "auto_installable": True,
        })
    if not report["toolchain"]["ffmpeg"]:
        steps.append({
            "id": "ffmpeg", "required": True,
            "why": "FFmpeg encodes the video and mixes the audio.",
            "command": "sudo apt-get install -y ffmpeg   # or: brew install ffmpeg",
            "alternative": " ".join(INSTALL_COMMANDS["imageio-ffmpeg"]),
            "auto_installable": False,
        })
    if not report["toolchain"]["ffprobe"]:
        steps.append({
            "id": "ffprobe", "required": True,
            "why": "ffprobe backs the mandatory structural QC gate.",
            "command": "sudo apt-get install -y ffmpeg   # or: brew install ffmpeg",
            "auto_installable": False,
        })
    if not report["narration"]["real_tts_available"]:
        steps.append({
            "id": "tts", "required": False,
            "why": "Without a local TTS engine the narration track is timed silence.",
            "command": "sudo apt-get install -y espeak-ng   # or: brew install espeak-ng",
            "auto_installable": False,
        })
    if report["toolchain"]["font_degraded"]:
        steps.append({
            "id": "fonts", "required": False,
            "why": "No TrueType face was found; type falls back to a bitmap font.",
            "command": "sudo apt-get install -y fonts-dejavu-core",
            "auto_installable": False,
        })
    return {
        "ready": report["can_render"],
        "capability_tier": report["capability_tier"],
        "steps": steps,
        "workspace": report["workspace"],
    }


def bootstrap(
    workspace: Optional[str] = None, *, install: bool = False, json_mode: bool = False
) -> int:
    settings = Settings.resolve(workspace)
    settings.ensure_dirs()
    result = plan(workspace)

    if install:
        performed = []
        for step in result["steps"]:
            if step.get("auto_installable") and step["id"] in INSTALL_COMMANDS:
                command = INSTALL_COMMANDS[step["id"]]
                proc = subprocess.run(command, check=False)  # noqa: S603 - fixed argv
                performed.append({"id": step["id"], "returncode": proc.returncode})
        result["installed"] = performed
        result = {**plan(workspace), "installed": performed}

    if json_mode:
        print(json.dumps(result, indent=2))
        return 0 if result["ready"] else 3

    print("FreeVideoForge bootstrap")
    print("=" * 52)
    print(f"workspace : {result['workspace']['root']}")
    print(f"outputs   : {result['workspace']['output']}")
    print(f"state     : {result['workspace']['state_db']}")
    print(f"tier      : {result['capability_tier']}")
    print()
    required = [s for s in result["steps"] if s["required"]]
    optional = [s for s in result["steps"] if not s["required"]]

    if not required:
        print("All required dependencies are present.")
    else:
        print("Missing required dependencies:")
        for step in required:
            print(f"  ! {step['id']}: {step['why']}")
            print(f"      {step['command']}")
            if step.get("alternative"):
                print(f"      alternative: {step['alternative']}")
    if optional:
        print("\nOptional improvements:")
        for step in optional:
            print(f"  - {step['id']}: {step['why']}")
            print(f"      {step['command']}")
    print()
    print("Nothing was installed system-wide and no model was downloaded.")
    if result["ready"]:
        print('\nReady. Try:\n  freevideoforge generate --topic "Why the moon changes '
              'shape" --duration 30 --aspect 9:16 --preset auto')
    return 0 if result["ready"] else 3
