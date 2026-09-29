"""FreeVideoForge - local-first, zero-cost brief-to-video production pipeline.

FreeVideoForge turns a topic or creative brief into a finished video using only
software that runs on the local machine. It requires no paid API, no API key and
no network access at render time.

Public surface:

    from freevideoforge import generate, GenerateRequest

    result = generate(GenerateRequest(topic="Why the moon changes shape"))
    print(result.final_video)
"""

from .version import __version__
from .models import (
    Aspect,
    Asset,
    GenerateRequest,
    JobState,
    Manifest,
    Project,
    QualityReport,
    RunResult,
    Scene,
)

__all__ = [
    "__version__",
    "Aspect",
    "Asset",
    "GenerateRequest",
    "JobState",
    "Manifest",
    "Project",
    "QualityReport",
    "RunResult",
    "Scene",
    "generate",
]


def generate(request: "GenerateRequest", **kwargs):  # pragma: no cover - thin re-export
    """Run the full pipeline. See :mod:`freevideoforge.api`."""
    from .api import generate as _generate

    return _generate(request, **kwargs)
