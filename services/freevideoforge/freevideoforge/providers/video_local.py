"""Optional local video-generation backend (capability tier A).

FreeVideoForge treats a local video model as a *replaceable provider*, never an
architectural invariant. This module does exactly two things:

* Detect, honestly, whether a compatible local video backend is reachable
  (a running ComfyUI instance, or an explicitly configured HTTP endpoint).
* Refuse to pretend. If nothing is there, ``probe()`` reports unavailable with
  the reason, the resolver drops to the next tier, and the manifest records
  procedural output as procedural output.

It never downloads a checkpoint, never authenticates, and never reaches outside
the loopback interface unless the operator explicitly configured an endpoint.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from ..errors import ProviderUnavailable
from ..models import Project, Scene
from .base import Capability, MediaResult

#: Default ComfyUI loopback address. Only probed, never started.
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
PROBE_TIMEOUT_SECONDS = 1.5


def _detect_accelerator() -> dict[str, object]:
    """Report GPU presence without importing a deep-learning framework."""
    info: dict[str, object] = {"cuda": False, "mps": False, "device": None, "vram_mb": 0}
    if shutil.which("nvidia-smi"):
        info["cuda"] = True
        info["device"] = "cuda"
    elif Path("/proc/driver/nvidia/version").exists():
        info["cuda"] = True
        info["device"] = "cuda"
    elif os.uname().sysname == "Darwin" and os.uname().machine == "arm64":
        # Apple silicon exposes MPS, but only with a framework installed.
        info["mps"] = True
        info["device"] = "mps"
    return info


def _probe_http(url: str) -> Optional[dict]:
    """GET a loopback endpoint with a short timeout. Returns None on any error."""
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return None
            body = response.read(65536)
        return json.loads(body.decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


class LocalVideoProvider:
    """Tier A probe. Generation is only attempted against a verified backend."""

    name = "local_video"
    kind = "video"

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.endpoint = os.environ.get("FVF_COMFYUI_URL", DEFAULT_COMFY_URL)
        self._system: Optional[dict] = None

    def probe(self) -> Capability:
        accelerator = _detect_accelerator()
        remediation = (
            "Tier A (local generative video) needs all of:\n"
            "  1. A GPU with enough VRAM for the chosen model.\n"
            "  2. A running local backend, e.g. ComfyUI on "
            f"{self.endpoint}.\n"
            "  3. A model checkpoint you have downloaded and whose licence you "
            "have read.\n"
            "FreeVideoForge will not download checkpoints or start services for "
            "you. Once a backend is running, re-run `freevideoforge doctor`."
        )
        self._system = _probe_http(f"{self.endpoint}/system_stats")
        if self._system is None:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail=f"No local video backend responded at {self.endpoint}.",
                remediation=remediation, requires_large_download=True,
                metadata={"accelerator": accelerator, "endpoint": self.endpoint},
            )
        if not (accelerator["cuda"] or accelerator["mps"]):
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail=(
                    "A backend responded, but no CUDA or MPS accelerator was "
                    "detected. Video diffusion on CPU is not viable here."
                ),
                remediation=remediation, requires_large_download=True,
                metadata={"accelerator": accelerator, "endpoint": self.endpoint,
                          "backend": self._system},
            )
        # A reachable backend on real hardware still does not prove a *video*
        # workflow and checkpoint are installed, so this stays unavailable until
        # an operator opts in explicitly.
        if os.environ.get("FVF_LOCAL_VIDEO_WORKFLOW"):
            return Capability(
                available=True, name=self.name, kind=self.kind,
                detail="Configured local video workflow against a reachable backend.",
                metadata={"accelerator": accelerator, "endpoint": self.endpoint,
                          "workflow": os.environ["FVF_LOCAL_VIDEO_WORKFLOW"]},
            )
        return Capability(
            available=False, name=self.name, kind=self.kind,
            detail=(
                "A backend and accelerator were found, but no video workflow is "
                "configured. Set FVF_LOCAL_VIDEO_WORKFLOW to an exported workflow "
                "JSON to enable tier A."
            ),
            remediation=remediation, requires_large_download=True,
            metadata={"accelerator": accelerator, "endpoint": self.endpoint,
                      "backend": self._system},
        )

    def generate(self, project: Project, scene: Scene, output: Path) -> MediaResult:
        capability = self.probe()
        if not capability.available:
            raise ProviderUnavailable(
                f"local_video is not available: {capability.detail}\n{capability.remediation}"
            )
        # Deliberately not implemented: wiring a specific workflow graph would
        # hardcode one vendor's node schema into the pipeline. The contract is
        # here; the adapter belongs with whichever backend an operator runs.
        raise ProviderUnavailable(
            "A local video backend was detected but no workflow adapter is installed. "
            "Implement VideoProvider.generate against your backend, or keep using "
            "the ffmpeg_motion renderer."
        )
