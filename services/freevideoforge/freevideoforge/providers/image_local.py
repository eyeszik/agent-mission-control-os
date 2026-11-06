"""Optional local image-generation backend (capability tier B).

Same contract as the video provider: detect honestly, never download, never
authenticate, and drop cleanly to the procedural renderer when absent.

Tier B would animate generated stills with the same Ken Burns and parallax
machinery the procedural renderer already uses - only the plate source changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..errors import ProviderUnavailable
from ..models import Project, Scene
from .base import Capability, MediaResult
from .video_local import DEFAULT_COMFY_URL, _detect_accelerator, _probe_http


class LocalImageProvider:
    name = "local_image"
    kind = "image"

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.endpoint = os.environ.get("FVF_COMFYUI_URL", DEFAULT_COMFY_URL)

    def probe(self) -> Capability:
        accelerator = _detect_accelerator()
        remediation = (
            "Tier B (local image generation + animation) needs a running local "
            f"image backend (e.g. ComfyUI on {self.endpoint}) with a checkpoint you "
            "have downloaded and licensed, plus FVF_LOCAL_IMAGE_WORKFLOW pointing at "
            "an exported workflow. FreeVideoForge downloads nothing on your behalf."
        )
        system = _probe_http(f"{self.endpoint}/system_stats")
        if system is None:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail=f"No local image backend responded at {self.endpoint}.",
                remediation=remediation, requires_large_download=True,
                metadata={"accelerator": accelerator, "endpoint": self.endpoint},
            )
        if not os.environ.get("FVF_LOCAL_IMAGE_WORKFLOW"):
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail=(
                    "A backend responded but no image workflow is configured "
                    "(FVF_LOCAL_IMAGE_WORKFLOW is unset)."
                ),
                remediation=remediation, requires_large_download=True,
                metadata={"accelerator": accelerator, "endpoint": self.endpoint,
                          "backend": system},
            )
        return Capability(
            available=True, name=self.name, kind=self.kind,
            detail="Configured local image workflow against a reachable backend.",
            metadata={"accelerator": accelerator, "endpoint": self.endpoint,
                      "workflow": os.environ["FVF_LOCAL_IMAGE_WORKFLOW"]},
        )

    def generate(self, project: Project, scene: Scene, output: Path) -> MediaResult:
        capability = self.probe()
        if not capability.available:
            raise ProviderUnavailable(
                f"local_image is not available: {capability.detail}\n{capability.remediation}"
            )
        raise ProviderUnavailable(
            "A local image backend was detected but no workflow adapter is installed. "
            "Implement ImageProvider.generate against your backend, or keep using the "
            "ffmpeg_motion renderer."
        )
