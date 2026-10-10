"""Typed contracts for the Generative Creative Foundry.

These extend, not replace, the existing IRs: a foundry mission still resolves
to Project OS artifacts (N4 rows), approvals still use the approvals table, and
design tokens still come from ``agency.design_tokens``. What is new is only
what AMC lacked: a renderer-independent ``CreativeGenome``, the grammar and
composition IRs a procedural renderer consumes, Experience/Motion/Scene IRs,
and a per-artifact proof with an explicit state machine.

Every model is strict, frozen and hashable through ``canonical_hash`` so the
same inputs always produce the same identity.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.langgraph.agency.execution.canonical import canonical_hash

FOUNDRY_VERSION = "amc-foundry/v1"
GENOME_SCHEMA = "amc-creative-genome/v1"
_HEX = r"^#[0-9a-f]{6}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


DeliverableType = Literal["genome", "logo_family", "poster", "design_tokens", "website_section", "variants",
                          "product_scene", "motion", "icon_family"]


class UserBrief(_Strict):
    """What a person types. Optional gaps become recorded assumptions; nothing here is authority."""

    organization: str = Field(min_length=1, max_length=80)
    offering: str = Field(default="", max_length=300)
    business_objective: str = Field(default="", max_length=500)
    target_audience: str = Field(default="", max_length=300)
    audience_needs: str = Field(default="", max_length=500)
    desired_action: str = Field(default="", max_length=120)
    deliverable_types: tuple[DeliverableType, ...] = ("genome", "logo_family", "poster", "design_tokens")
    visual_direction: dict[str, float] = Field(default_factory=dict)  # grammar_id -> weight
    brand_constraints: dict[str, Any] = Field(default_factory=dict)   # e.g. {"palette": {...}, "wordmark": "..."}
    reference_assets: tuple[str, ...] = ()                            # Project OS artifact ids only
    existing_project_id: Optional[str] = None                         # a hint; never authority
    budget: Optional[str] = None
    deadline: Optional[str] = None
    accessibility_requirements: tuple[str, ...] = ("WCAG 2.2 AA",)
    approved_external_resources: tuple[str, ...] = ()
    generation_intensity: Literal["conservative", "balanced", "exploratory"] = "balanced"
    render_quality: Literal["draft", "standard"] = "draft"
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)

    @field_validator("visual_direction")
    @classmethod
    def _weights(cls, value: dict[str, float]) -> dict[str, float]:
        for k, w in value.items():
            if not (0 < float(w) <= 1):
                raise ValueError(f"visual_direction[{k}] must be in (0, 1]")
        return value


class Assumption(_Strict):
    field: str
    value: Any
    reason: str


class Palette(_Strict):
    ink: str = Field(pattern=_HEX)
    paper: str = Field(pattern=_HEX)
    accent: str = Field(pattern=_HEX)
    accent_2: str = Field(pattern=_HEX)
    muted: str = Field(pattern=_HEX)

    def roles(self) -> dict[str, str]:
        return self.model_dump()


class CreativeGenome(_Strict):
    """A renderer-independent description of a brand's visual system."""

    schema_version: Literal["amc-creative-genome/v1"] = GENOME_SCHEMA
    project_ref: str
    brand_name: str
    brand_canon_hash: Optional[str]          # hash of the approved canon this genome was derived from, if any
    geometry_rules: dict[str, Any]
    color_rules: dict[str, Any]              # {"palette": Palette, "contrast": {...}, "usage": {...}}
    typography_rules: dict[str, Any]
    layout_rules: dict[str, Any]
    composition_rules: dict[str, Any]
    material_rules: dict[str, Any]
    motion_rules: dict[str, Any]
    imagery_rules: dict[str, Any]
    interaction_rules: dict[str, Any]
    novelty_constraints: dict[str, Any]
    accessibility_constraints: dict[str, Any]
    source_evidence_refs: tuple[str, ...]
    deterministic_seed: int
    grammar_weights: dict[str, float]
    invariants: tuple[str, ...]              # dotted paths mutation may never change
    assumptions: tuple[Assumption, ...] = ()

    @property
    def palette(self) -> Palette:
        return Palette(**self.color_rules["palette"])


class VisualGrammar(_Strict):
    grammar_id: str
    name: str
    composition_operators: tuple[str, ...]
    proportion: dict[str, float]             # margin, gutter, headline scale ...
    grid: dict[str, Any]
    typography: dict[str, Any]
    palette_logic: str
    texture_logic: str
    primitives: tuple[str, ...]
    motion: dict[str, Any]
    variation_axes: tuple[str, ...]
    anti_patterns: tuple[str, ...]
    lineage_note: str                         # historical influence, stated as influence, never as a licence to copy


class Primitive(_Strict):
    kind: Literal["rect", "circle", "ring", "triangle", "bar", "arc", "line", "dots", "pixel_block", "card", "fan"]
    x: float
    y: float
    w: float = 0
    h: float = 0
    r: float = 0
    rotation: float = 0
    fill: str                                 # palette role, never a literal colour
    opacity: float = Field(default=1.0, ge=0, le=1)
    stroke: Optional[str] = None
    stroke_width: float = 0
    corner: float = 0
    grammar: str


class TextBlock(_Strict):
    role: Literal["headline", "subhead", "body", "meta", "wordmark", "cta"]
    text: str = Field(max_length=200)
    x: float
    y: float
    size: float
    weight: int = 400
    family: Literal["display", "text", "mono"] = "display"
    anchor: Literal["start", "middle", "end"] = "start"
    fill: str = "ink"
    tracking: float = 0
    rotation: float = 0
    max_width: Optional[float] = None


class CompositionIR(_Strict):
    kind: Literal["poster", "mark", "lockup", "icon", "frame"]
    width: int
    height: int
    background: str = "paper"
    primitives: tuple[Primitive, ...]
    text: tuple[TextBlock, ...] = ()
    genome_hash: str
    grammar_weights: dict[str, float]
    seed: int
    title: str


class Keyframe(_Strict):
    t: float = Field(ge=0, le=1)
    props: dict[str, float]                  # opacity, scale, tx, ty, rotate, reveal
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out", "spring"] = "ease_out"


class MotionLayer(_Strict):
    layer_id: str
    target: Literal["mark", "wordmark", "tagline", "rule", "background"]
    keyframes: tuple[Keyframe, ...]


class MotionIR(_Strict):
    template: Literal["logo_reveal", "kinetic_typography", "product_rotation", "brand_intro", "social_motion", "ui_demo"]
    width: int
    height: int
    fps: int = Field(ge=1, le=60)
    duration_s: float = Field(gt=0, le=30)
    layers: tuple[MotionLayer, ...]
    reduced_motion: Literal["static_final_frame", "crossfade"] = "static_final_frame"
    audio_refs: tuple[str, ...] = ()
    genome_hash: str

    @property
    def frame_count(self) -> int:
        return int(round(self.fps * self.duration_s))


class ComponentContract(_Strict):
    component_id: str
    role: str
    props: tuple[str, ...]
    states: tuple[str, ...]
    keyboard: str
    validation: str
    focus: str
    loading: str
    error: str
    responsive: str
    tokens: tuple[str, ...]


class ExperienceIR(_Strict):
    jobs_to_be_done: tuple[str, ...]
    user_flow: tuple[str, ...]
    information_architecture: tuple[str, ...]
    components: tuple[ComponentContract, ...]
    state_matrix: dict[str, tuple[str, ...]]
    copy_text: dict[str, str]
    genome_hash: str


class MaterialIR(_Strict):
    material_id: str
    base_color_role: str
    roughness: float = Field(ge=0, le=1)
    metallic: float = Field(ge=0, le=1)
    texture_ref: Optional[str] = None        # a local file produced by this mission (e.g. the poster PNG)


class SceneIR(_Strict):
    scene: Literal["package_on_plinth", "product_on_plinth", "device_screen", "apparel_placement", "editorial_objects"]
    width: int
    height: int
    samples: int
    seed: int
    camera: dict[str, float]
    materials: tuple[MaterialIR, ...]
    palette: dict[str, str]
    genome_hash: str
    synthetic_disclosure: str = "Synthetic 3D render. Not a photograph of a manufactured product."


class CapabilityManifest(_Strict):
    capability_id: str
    implementation: str
    installed_version: Optional[str]
    status: Literal["AVAILABLE", "MISSING", "BLOCKED", "DISABLED"]
    media_types: tuple[str, ...]
    input_schema: str
    output_schema: str
    deterministic: Literal["yes", "no", "declared_nondeterministic"]
    offline_supported: bool
    required_binaries: tuple[str, ...]
    resource_limits: dict[str, Any]
    license_status: str
    trust_boundary: str
    supported_validators: tuple[str, ...]
    blockers: tuple[str, ...] = ()


class RenderJob(_Strict):
    job_id: str
    deliverable: DeliverableType
    route: str
    rejected_routes: tuple[str, ...]
    ir_hash: str
    resource_envelope: dict[str, Any]


class RenderManifest(_Strict):
    job: RenderJob
    renderer_id: str
    renderer_version: Optional[str]
    outputs: tuple[dict, ...]                # {path, sha256, bytes, mime}
    elapsed_ms: int
    outcome: Literal["SUCCEEDED", "FAILED", "BLOCKED"]
    reasons: tuple[str, ...] = ()


class ProofState(str, Enum):
    SPECIFIED = "SPECIFIED"
    COMPILED = "COMPILED"
    EXECUTED = "EXECUTED"
    OUTPUT_OBSERVED = "OUTPUT_OBSERVED"
    VERIFIED = "VERIFIED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    RELEASE_ELIGIBLE = "RELEASE_ELIGIBLE"


class ArtifactProof(_Strict):
    project_ref: str
    artifact_ref: Optional[str]
    version_ref: Optional[int]
    source_hash: str                          # the genome / input the artifact was compiled from
    compiled_ir_hash: Optional[str]
    renderer_id: Optional[str]
    renderer_version: Optional[str]
    output_sha256: Optional[str]
    mime_type: Optional[str]
    observed_dimensions: Optional[str]
    file_size: Optional[int]
    dependency_hashes: tuple[str, ...] = ()
    license_refs: tuple[str, ...] = ()
    validation_results: tuple[dict, ...] = ()
    approval_ref: Optional[str] = None
    state: ProofState
    blocked_at: Optional[str] = None


__all__ = [
    "ArtifactProof", "Assumption", "CapabilityManifest", "ComponentContract", "CompositionIR", "CreativeGenome",
    "DeliverableType", "ExperienceIR", "FOUNDRY_VERSION", "GENOME_SCHEMA", "Keyframe", "MaterialIR", "MotionIR",
    "MotionLayer", "Palette", "Primitive", "ProofState", "RenderJob", "RenderManifest", "SceneIR", "TextBlock",
    "UserBrief", "VisualGrammar",
]
