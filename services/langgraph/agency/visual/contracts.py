"""Contracts for the local visual production engine.

Everything here describes local, offline production. There is no hosted
image or video generation API anywhere in this package: a route whose local
tool, model, licence or hardware is missing is BLOCKED, never substituted.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

VISUAL_ENGINE_VERSION = "amc-visual-engine/v1"
_HASH = r"^[a-f0-9]{64}$"
_HEX = r"^#[0-9a-fA-F]{6}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Route(str, Enum):
    BLENDER_CYCLES = "R1_BLENDER_CYCLES"
    OFFLINE_DIFFUSION = "R2_OFFLINE_DIFFUSION"
    THREE_JS = "R3_THREE_JS"
    VECTOR = "R4_VECTOR"
    LOCAL_VIDEO = "R5_LOCAL_VIDEO"


class CapabilityStatus(str, Enum):
    VERIFIED_AVAILABLE = "VERIFIED_AVAILABLE"
    MISSING_DEPENDENCIES = "MISSING_DEPENDENCIES"
    BLOCKED_LOCAL_MODEL = "BLOCKED_LOCAL_MODEL"
    BLOCKED_ENVIRONMENT = "BLOCKED_ENVIRONMENT"
    DEGRADED = "DEGRADED"


class Capability(_Strict):
    route: Route
    status: CapabilityStatus
    version: Optional[str] = None
    detail: str = ""
    hardware: dict[str, Any] = Field(default_factory=dict)
    blockers: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status is CapabilityStatus.VERIFIED_AVAILABLE


class VisualIntent(_Strict):
    """What the image or video must do. Selection criteria from the spec."""

    category: Literal["product_still", "product_turntable", "brand_mark", "interactive_scene", "concept_image"]
    output: Literal["image", "video", "svg"] = "image"
    realism: Literal["photographic", "stylised", "exact_geometry"] = "photographic"
    exactness: Literal["exact", "approximate"] = "exact"
    interactivity: bool = False
    width: int = Field(default=1200, ge=64, le=8192)
    height: int = Field(default=1500, ge=64, le=8192)
    frames: int = Field(default=1, ge=1, le=600)
    fps: int = Field(default=24, ge=1, le=60)
    samples: int = Field(default=128, ge=1, le=4096)
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    palette: dict[str, str]
    source_assets: tuple["SourceAsset", ...] = ()
    subject: str = Field(default="", max_length=80)  # brand or product name; used by the vector mark

    @field_validator("palette")
    @classmethod
    def _palette(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        for role in ("primary", "secondary", "surface", "text"):
            if role not in value:
                raise ValueError(f"palette lacks role {role}")
        for role, hex_value in value.items():
            if not re.match(_HEX, hex_value):
                raise ValueError(f"palette[{role}] must be #rrggbb")
        return {k: v.lower() for k, v in sorted(value.items())}


class SourceAsset(_Strict):
    """An external input (texture, model, reference). Procedural scenes have none."""

    ref: str
    sha256: str = Field(pattern=_HASH)
    license: Optional[str] = None       # SPDX id or licence name; None = unknown
    rights_holder: Optional[str] = None


VisualIntent.model_rebuild()


class RouteDecision(_Strict):
    route: Optional[Route]
    status: Literal["SELECTED", "BLOCKED"]
    reasons: tuple[str, ...]
    considered: dict[str, str]  # route -> capability status, for the receipt


class RealismContract(_Strict):
    target_category: str
    reference_rights: Literal["procedural_owned", "licensed", "unknown"]
    scene_or_model: str
    lighting_model: str
    material_fidelity: str
    camera_model: str
    texture_resolution: str
    color_pipeline: str
    image_dimensions: tuple[int, int]
    realism_criteria: tuple[str, ...]
    allowed_variance: str
    review_requirements: tuple[str, ...]


class VisualGenome(_Strict):
    """Lineage of exactly what produced the pixels."""

    route: Route
    renderer: str
    renderer_version: str
    scene_spec_sha256: Optional[str] = Field(default=None, pattern=_HASH)
    geometry: str
    materials: tuple[str, ...]
    camera: dict[str, Any]
    lights: tuple[str, ...]
    model_weights: Optional[str] = None
    seed: int
    samples: Optional[int] = None
    source_assets: tuple[SourceAsset, ...] = ()
    hardware: dict[str, Any]
    color_management: dict[str, Any] = Field(default_factory=dict)


class QualityLevel(str, Enum):
    Q0_VALID_FILE = "Q0_VALID_FILE"
    Q1_DECODABLE = "Q1_DECODABLE"
    Q2_DIMENSIONS_FORMAT = "Q2_DIMENSIONS_FORMAT"
    Q3_NONBLANK = "Q3_NONBLANK"
    Q4_RIGHTS = "Q4_RIGHTS"
    Q5_VISUAL_CONSTRAINTS = "Q5_VISUAL_CONSTRAINTS"
    Q6_REALISM_BRAND = "Q6_REALISM_BRAND"
    Q7_APPROVAL = "Q7_APPROVAL"


class MediaVerification(_Strict):
    """Independent reopening of persisted bytes. Q5-Q7 are never machine-certified here."""

    artifact_id: Optional[str]
    version: Optional[int]
    content_hash: str = Field(pattern=_HASH)
    mime_type: str
    byte_size: int
    status: Literal["PASSED", "FAILED", "INCONCLUSIVE", "HUMAN_REQUIRED"]
    highest_passed: Optional[QualityLevel]
    checks: tuple[dict, ...]
    human_required: tuple[QualityLevel, ...]
    findings: tuple[str, ...]
    verifier: str
    verified_at: str


class RenderReceipt(_Strict):
    route: Route
    status: Literal["SUCCEEDED", "FAILED", "BLOCKED"]
    outputs: tuple[dict, ...] = ()  # {path, sha256, bytes}
    genome: Optional[VisualGenome] = None
    command: tuple[str, ...] = ()
    exit_code: Optional[int] = None
    wall_ms: Optional[int] = None
    logical_tick: Optional[int] = None
    observed_at: str
    reasons: tuple[str, ...] = ()
    network_isolated: Optional[bool] = None


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
    "VISUAL_ENGINE_VERSION",
    "VisualGenome",
    "VisualIntent",
]
