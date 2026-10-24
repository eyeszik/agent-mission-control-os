"""Versioned, bounded render identity; attempt credentials never enter its hash."""
from __future__ import annotations

from enum import Enum
from math import gcd
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.langgraph.agency.execution.canonical import canonical_bytes, canonical_hash

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, Field(min_length=1, max_length=128, pattern=r".*\S.*")]
Color = Annotated[str, Field(pattern=r"^#[a-fA-F0-9]{6}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RenderEngineId(str, Enum):
    PAPER = "paper_js"
    SVG = "svg_js"
    ROUGH = "rough_js"
    P5 = "p5_js"
    PIXI = "pixi_js"
    THREE = "react_three_fiber"
    REMOTION = "remotion"
    MOTION_CANVAS = "motion_canvas"


class Dimensions(Strict):
    width: int = Field(default=960, ge=1, le=4096, strict=True)
    height: int = Field(default=540, ge=1, le=4096, strict=True)

    @model_validator(mode="after")
    def bounded(self):
        if self.width * self.height > 8_294_400:
            raise ValueError("pixel budget exceeds 8,294,400")
        return self


class FrameClock(Strict):
    fps_numerator: int = Field(default=30, ge=1, le=240000, strict=True)
    fps_denominator: int = Field(default=1, ge=1, le=1001, strict=True)
    total_frames: int = Field(default=1, ge=1, le=18000, strict=True)

    @model_validator(mode="after")
    def bounded(self):
        if gcd(self.fps_numerator, self.fps_denominator) != 1:
            raise ValueError("frame rate must be in lowest terms")
        fps = self.fps_numerator / self.fps_denominator
        if fps > 240 or self.total_frames / fps > 600:
            raise ValueError("frame rate or duration exceeds policy")
        return self


class Primitive(Strict):
    kind: Literal["rectangle", "ellipse", "line"]
    x: float = Field(ge=0, le=4096, allow_inf_nan=False)
    y: float = Field(ge=0, le=4096, allow_inf_nan=False)
    width: float = Field(gt=0, le=4096, allow_inf_nan=False)
    height: float = Field(gt=0, le=4096, allow_inf_nan=False)
    fill: Color = "#ece6da"
    stroke: Color = "#121212"
    stroke_width: float = Field(default=1, ge=0, le=32, allow_inf_nan=False)


class Scene(Strict):
    """Data only: no JS, TSX, URLs, HTML, scripts, fonts or arbitrary parameters."""
    background: Color = "#ffffff"
    primitives: tuple[Primitive, ...] = Field(min_length=1, max_length=200)


class RenderRequest(Strict):
    workflow_id: Name
    task_id: Name
    brief: str = Field(min_length=10, max_length=4000)
    engine: RenderEngineId = RenderEngineId.ROUGH
    scene_revision: int = Field(default=1, ge=1, strict=True)
    seed: int = Field(default=42, ge=1, le=2**31 - 1, strict=True)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    clock: FrameClock = Field(default_factory=FrameClock)
    output_format: Literal["svg", "png", "mp4", "webm"] = "svg"
    scene: Scene

    @model_validator(mode="after")
    def admission(self):
        if not self.brief.strip() or len(self.brief.strip()) < 10:
            raise ValueError("brief must contain at least 10 non-padding characters")
        if self.output_format in {"svg", "png"} and self.clock.total_frames != 1:
            raise ValueError("still output requires exactly one frame")
        if len(canonical_bytes(self.model_dump(mode="json"))) > 131072:
            raise ValueError("request exceeds serialized size budget")
        return self


class RenderSpecification(Strict):
    contract_version: Literal["amc-render/v1"] = "amc-render/v1"
    tenant_id: Name
    project_id: Name
    request: RenderRequest
    adapter_version: str | None
    package_lock_hash: Hash
    worker_source_hash: Hash
    runtime_version: str
    isolation_profile: Literal["typed-primitives/process-v1"] = "typed-primitives/process-v1"

    @property
    def spec_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class VerificationReport(Strict):
    status: Literal["PASSED", "FAILED", "INCONCLUSIVE"]
    content_hash: Hash
    byte_count: int = Field(ge=0)
    spec_hash: Hash
    checks: tuple[str, ...]
    findings: tuple[str, ...] = ()
    verifier: Literal["amc-render-svg/v1"] = "amc-render-svg/v1"
