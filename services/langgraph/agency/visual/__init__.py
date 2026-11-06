"""Local visual production engine: Blender Cycles, local video, offline diffusion. No hosted APIs.

See ``docs/local-visual-engine.md``.
"""

from .capabilities import probe_all
from .contracts import (
    Capability,
    CapabilityStatus,
    MediaVerification,
    QualityLevel,
    RealismContract,
    RenderReceipt,
    Route,
    RouteDecision,
    SourceAsset,
    VisualGenome,
    VisualIntent,
)
from .router import route
from .verify import verify_media

__all__ = [
    "Capability",
    "CapabilityStatus",
    "MediaVerification",
    "QualityLevel",
    "RealismContract",
    "RenderReceipt",
    "Route",
    "RouteDecision",
    "SourceAsset",
    "VisualGenome",
    "VisualIntent",
    "probe_all",
    "route",
    "verify_media",
]
