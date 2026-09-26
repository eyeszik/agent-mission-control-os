"""Canonical intermediate representations and typed vocabularies.

Everything downstream — routing, production reasoning, every prompt compiler,
the evaluator and the repair loop — consumes these types. There is deliberately
one canonical shot representation (:class:`ShotIR`) and one canonical project
representation (:class:`ProjectIR`); compilers never rebuild project context on
their own.

The models are richer than any final prompt. Compression happens at the last
step (see :mod:`.compilers`), never by discarding canonical state.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Source authority and fact status (checklist section 10)
# --------------------------------------------------------------------------- #
class SourceAuthority(str, Enum):
    """Ordered highest -> lowest. ``rank`` gives the numeric precedence."""

    system_constraint = "SYSTEM_CONSTRAINT"
    user_explicit_fact = "USER_EXPLICIT_FACT"
    supplied_script = "SUPPLIED_SCRIPT"
    supplied_storyboard = "SUPPLIED_STORYBOARD"
    supplied_image = "SUPPLIED_IMAGE"
    supplied_brand = "SUPPLIED_BRAND"
    established_canon = "ESTABLISHED_CANON"
    verified_reference_fact = "VERIFIED_REFERENCE_FACT"
    reasonable_inference = "REASONABLE_INFERENCE"
    creative_default = "CREATIVE_DEFAULT"

    @property
    def rank(self) -> int:
        return _AUTHORITY_ORDER.index(self)


_AUTHORITY_ORDER: tuple[SourceAuthority, ...] = (
    SourceAuthority.system_constraint,
    SourceAuthority.user_explicit_fact,
    SourceAuthority.supplied_script,
    SourceAuthority.supplied_storyboard,
    SourceAuthority.supplied_image,
    SourceAuthority.supplied_brand,
    SourceAuthority.established_canon,
    SourceAuthority.verified_reference_fact,
    SourceAuthority.reasonable_inference,
    SourceAuthority.creative_default,
)


class FactStatus(str, Enum):
    defined = "DEFINED"
    inferred = "INFERRED"
    proposed = "PROPOSED"
    unknown_critical = "UNKNOWN_CRITICAL"


class Fact(BaseModel):
    key: str = Field(min_length=1)
    value: Any = None
    authority: SourceAuthority
    status: FactStatus
    source_id: str | None = None
    note: str | None = None

    model_config = {"extra": "forbid"}


class SourceRef(BaseModel):
    source_id: str = Field(min_length=1)
    authority: SourceAuthority
    kind: str = Field(min_length=1)
    summary: str | None = None

    model_config = {"extra": "forbid"}


class FactLedger(BaseModel):
    defined: list[Fact] = Field(default_factory=list)
    inferred: list[Fact] = Field(default_factory=list)
    proposed: list[Fact] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class Canon(BaseModel):
    immutable: list[str] = Field(default_factory=list)
    flexible: list[str] = Field(default_factory=list)
    character: list[str] = Field(default_factory=list)
    world: list[str] = Field(default_factory=list)
    location: list[str] = Field(default_factory=list)
    wardrobe: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    brand: list[str] = Field(default_factory=list)
    temporal: list[str] = Field(default_factory=list)
    motifs: list[str] = Field(default_factory=list)
    banned_substitutions: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Input taxonomy (checklist section 12)
# --------------------------------------------------------------------------- #
class InputMode(str, Enum):
    capability = "CAPABILITY"
    audit = "AUDIT"
    system_design = "SYSTEM_DESIGN"
    workflow = "WORKFLOW"
    development = "DEVELOPMENT"
    character = "CHARACTER"
    storyboard = "STORYBOARD"
    video_package = "VIDEO_PACKAGE"
    prompts_only = "PROMPTS_ONLY"
    revision = "REVISION"
    brand = "BRAND"
    automation = "AUTOMATION"


class InputForm(str, Enum):
    idea = "IDEA"
    script = "SCRIPT"
    treatment = "TREATMENT"
    dialogue = "DIALOGUE"
    image = "IMAGE"
    moodboard = "MOODBOARD"
    storyboard_panel = "STORYBOARD_PANEL"
    character = "CHARACTER"
    location = "LOCATION"
    brand = "BRAND"
    product = "PRODUCT"
    campaign = "CAMPAIGN"
    scene = "SCENE"
    reference = "REFERENCE"


# Modes that describe or design the system rather than produce creative assets.
NON_GENERATIVE_MODES: frozenset[InputMode] = frozenset(
    {
        InputMode.capability,
        InputMode.audit,
        InputMode.system_design,
        InputMode.workflow,
    }
)


# --------------------------------------------------------------------------- #
# Camera / cinematography vocabulary (checklist section 19)
# --------------------------------------------------------------------------- #
class ShotSize(str, Enum):
    ews = "EWS"
    ws = "WS"
    full = "FULL"
    mws = "MWS"
    ms = "MS"
    mcu = "MCU"
    cu = "CU"
    ecu = "ECU"
    insert = "INSERT"
    cutaway = "CUTAWAY"
    ots = "OTS"
    pov = "POV"
    two = "TWO"
    group = "GROUP"


class CameraAngle(str, Enum):
    eye = "EYE"
    low = "LOW"
    high = "HIGH"
    ground = "GROUND"
    overhead = "OVERHEAD"
    profile = "PROFILE"
    three_quarter = "3Q"
    ots = "OTS"
    pov = "POV"
    rear = "REAR"
    obstructed = "OBSTRUCTED"


class LensIntent(str, Enum):
    ultra_wide = "ULTRA_WIDE"        # 14-20
    wide = "WIDE"                    # 21-28
    immersive_wide = "IMMERSIVE_WIDE"  # 32-35
    natural = "NATURAL"              # 40-55
    compressed_portrait = "COMPRESSED_PORTRAIT"  # 65-85
    portrait = "PORTRAIT"            # 85-105
    telephoto = "TELEPHOTO"          # 135+
    macro = "MACRO"


LENS_RANGE: dict[LensIntent, str] = {
    LensIntent.ultra_wide: "14-20mm",
    LensIntent.wide: "21-28mm",
    LensIntent.immersive_wide: "32-35mm",
    LensIntent.natural: "40-55mm",
    LensIntent.compressed_portrait: "65-85mm",
    LensIntent.portrait: "85-105mm",
    LensIntent.telephoto: "135mm+",
    LensIntent.macro: "macro",
}


class FocusType(str, Enum):
    deep = "DEEP"
    shallow = "SHALLOW"
    selective = "SELECTIVE"
    rack = "RACK"
    fg_defocus = "FG_DEFOCUS"
    bg_defocus = "BG_DEFOCUS"


class CameraMove(str, Enum):
    static = "STATIC"
    pan = "PAN"
    tilt = "TILT"
    dolly = "DOLLY"
    truck = "TRUCK"
    pedestal = "PEDESTAL"
    arc = "ARC"
    orbit = "ORBIT"
    crane = "CRANE"
    jib = "JIB"
    follow = "FOLLOW"
    lead = "LEAD"
    gimbal = "GIMBAL"
    steadicam_like = "STEADICAM_LIKE"
    handheld = "HANDHELD"
    whip = "WHIP"
    roll = "ROLL"
    zoom = "ZOOM"
    rack_focus = "RACK_FOCUS"


class CameraState(BaseModel):
    """Camera behaviour for one shot. STATIC is the default; movement is never
    added automatically. Every non-static move must carry full motion fields."""

    move: CameraMove = CameraMove.static
    motivation: str | None = None
    start_position: str | None = None
    start_frame: str | None = None
    path: str | None = None
    direction: str | None = None
    speed_curve: str | None = None
    stabilization: str | None = None
    subject_relation: str | None = None
    focus_behavior: str | None = None
    end_position: str | None = None
    end_frame: str | None = None

    model_config = {"extra": "forbid"}

    @property
    def is_moving(self) -> bool:
        return self.move is not CameraMove.static

    def missing_move_fields(self) -> list[str]:
        if not self.is_moving:
            return []
        required = {
            "motivation": self.motivation,
            "start_position": self.start_position,
            "path": self.path,
            "speed_curve": self.speed_curve,
            "end_position": self.end_position,
            "focus_behavior": self.focus_behavior,
        }
        return sorted(name for name, value in required.items() if not value)


class AttentionVector(BaseModel):
    target: str = Field(min_length=1)
    entry_method: str | None = None
    hold_duration: str | None = None
    transfer_trigger: str | None = None
    next_target: str | None = None
    deliberate_counterpoint: bool = False

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Continuity (checklist section 13)
# --------------------------------------------------------------------------- #
class FinalFrameHandshake(BaseModel):
    subject_position: str | None = None
    gaze: str | None = None
    prop_state: str | None = None
    camera_orientation: str | None = None
    light_state: str | None = None
    motion_state: str | None = None

    model_config = {"extra": "forbid"}


class ContinuityState(BaseModel):
    inherits_from: str | None = None
    entry_requirements: FinalFrameHandshake = Field(default_factory=FinalFrameHandshake)
    active_packets: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class MemoryPacket(BaseModel):
    """Immutable / continuity-critical facts, reused across shots so the whole
    project bible is never restated in every prompt."""

    packet_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)  # character | location | wardrobe | prop | camera | brand
    locked: dict[str, Any] = Field(default_factory=dict)
    authority: SourceAuthority = SourceAuthority.established_canon

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Performance (checklist section 16)
# --------------------------------------------------------------------------- #
class PerformanceSpec(BaseModel):
    # Internal
    objective: str | None = None
    obstacle: str | None = None
    tactic: str | None = None
    subtext: str | None = None
    relationship: str | None = None
    # Visible
    gaze: str | None = None
    breathing: str | None = None
    posture: str | None = None
    hands: str | None = None
    tempo: str | None = None
    distance: str | None = None
    reaction_delay: str | None = None
    micro_expression: str | None = None
    # Observable beat sequence: NOTICE -> PROCESS -> DECIDE -> ACT -> REACT
    beat_sequence: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    def visible_fields(self) -> dict[str, str]:
        keys = (
            "gaze",
            "breathing",
            "posture",
            "hands",
            "tempo",
            "distance",
            "reaction_delay",
            "micro_expression",
        )
        return {k: getattr(self, k) for k in keys if getattr(self, k)}


# --------------------------------------------------------------------------- #
# Physics (checklist section 22)
# --------------------------------------------------------------------------- #
class PhysicsEvent(BaseModel):
    trigger: str
    primary_consequence: str
    secondary_response: str | None = None
    settle: str | None = None

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Shot IR (checklist section 9)
# --------------------------------------------------------------------------- #
class ShotIR(BaseModel):
    id: str = Field(min_length=1)
    purpose: str = ""
    duration: float | None = None
    character_state: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, Any] = Field(default_factory=dict)
    set: dict[str, Any] = Field(default_factory=dict)
    props: list[str] = Field(default_factory=list)
    start_frame: dict[str, Any] = Field(default_factory=dict)
    primary_action: str = ""
    secondary_action: str = ""
    performance: PerformanceSpec = Field(default_factory=PerformanceSpec)
    dialogue: str | None = None
    shot_size: ShotSize = ShotSize.ms
    angle: CameraAngle = CameraAngle.eye
    lens: LensIntent = LensIntent.natural
    camera: CameraState = Field(default_factory=CameraState)
    focus: FocusType = FocusType.deep
    light: dict[str, Any] = Field(default_factory=dict)
    color: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, Any] = Field(default_factory=dict)
    atmosphere: dict[str, Any] = Field(default_factory=dict)
    physics: list[PhysicsEvent] = Field(default_factory=list)
    continuity: ContinuityState = Field(default_factory=ContinuityState)
    final_frame: FinalFrameHandshake = Field(default_factory=FinalFrameHandshake)
    failure_risks: list[str] = Field(default_factory=list)
    attention: AttentionVector | None = None
    identity_refs: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Storyboard (checklist section 23)
# --------------------------------------------------------------------------- #
class StoryboardPanel(BaseModel):
    number: int = Field(ge=1)
    time: str = ""
    shot_id: str = ""
    shot_size: str = ""
    angle: str = ""
    lens: str = ""
    camera: str = ""
    composition: str = ""
    character_pose: str = ""
    expression: str = ""
    blocking: str = ""
    foreground: str = ""
    midground: str = ""
    background: str = ""
    light: str = ""
    action: str = ""
    dialogue: str = ""
    audio: str = ""
    transition: str = ""
    continuity: str = ""

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Story structures (checklist section 14)
# --------------------------------------------------------------------------- #
class Beat(BaseModel):
    id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    dramatic_change: str | None = None
    characters: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class Scene(BaseModel):
    id: str = Field(min_length=1)
    location_id: str | None = None
    beats: list[Beat] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class Relationship(BaseModel):
    a: str
    b: str
    nature: str

    model_config = {"extra": "forbid"}


class Story(BaseModel):
    logline: str | None = None
    scenes: list[Scene] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Character (checklist section 15)
# --------------------------------------------------------------------------- #
class Character(BaseModel):
    id: str = Field(min_length=1)
    name: str = ""
    speaking: bool = False
    recurring: bool = False
    identity_sensitive: bool = False
    immutable_identity: dict[str, Any] = Field(default_factory=dict)
    flexible_attributes: dict[str, Any] = Field(default_factory=dict)
    wardrobe: dict[str, Any] = Field(default_factory=dict)
    movement_signature: str | None = None
    backstory: str | None = None
    performance: PerformanceSpec = Field(default_factory=PerformanceSpec)

    model_config = {"extra": "forbid"}

    def needs_portrait(self) -> bool:
        return self.speaking or self.recurring or self.identity_sensitive


# --------------------------------------------------------------------------- #
# World / brand / model (checklist sections 17, 29, 30)
# --------------------------------------------------------------------------- #
class WorldModel(BaseModel):
    architecture: str | None = None
    major_forms: list[str] = Field(default_factory=list)
    story_props: list[str] = Field(default_factory=list)
    lived_in_evidence: list[str] = Field(default_factory=list)
    atmosphere: str | None = None
    lighting_interaction: str | None = None
    environmental_movement: str | None = None
    built_by: str | None = None
    used_by: str | None = None

    model_config = {"extra": "forbid"}


class BrandMotion(BaseModel):
    identity: str | None = None
    restraint: str | None = None
    holds: list[str] = Field(default_factory=list)
    amplitude: str | None = None
    timing: str | None = None
    allow_spring_bounce: bool = False

    model_config = {"extra": "forbid"}


class ModelProfile(BaseModel):
    """Describes a target generator. Unknown models fall back to
    :data:`.adapters.PORTABLE_PROFILE`; capabilities are never fabricated."""

    provider: str | None = None
    model: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    prompt_style: str | None = None   # "natural" | "json"
    max_duration: float | None = None
    reference_support: bool | None = None
    negative_support: bool | None = None
    camera_control: bool | None = None
    audio: bool | None = None
    seed: bool | None = None
    known_constraints: list[str] = Field(default_factory=list)
    legacy_prefix: str | None = None  # e.g. "/use-after-effects"; never emitted by default

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Project IR (checklist section 8)
# --------------------------------------------------------------------------- #
class ProjectIR(BaseModel):
    meta: dict[str, Any] = Field(default_factory=dict)
    sources: list[SourceRef] = Field(default_factory=list)
    facts: FactLedger = Field(default_factory=FactLedger)
    canon: Canon = Field(default_factory=Canon)
    story: Story = Field(default_factory=Story)
    characters: list[Character] = Field(default_factory=list)
    world: WorldModel = Field(default_factory=WorldModel)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    scene_graphs: list[dict[str, Any]] = Field(default_factory=list)
    storyboards: list[StoryboardPanel] = Field(default_factory=list)
    shots: list[ShotIR] = Field(default_factory=list)
    brand: BrandMotion | None = None
    motion: dict[str, Any] = Field(default_factory=dict)
    edit: dict[str, Any] = Field(default_factory=dict)
    audio: dict[str, Any] = Field(default_factory=dict)
    delivery: dict[str, Any] = Field(default_factory=dict)
    rights: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    packets: list[MemoryPacket] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Request / output (checklist sections 11, 25, 43)
# --------------------------------------------------------------------------- #
class PromptTarget(str, Enum):
    t2i = "T2I"
    t2v = "T2V"
    i2v = "I2V"
    storyboard = "STORYBOARD"
    motion = "MOTION"


class CinematicRequest(BaseModel):
    """Normalised entry into the capability. ``text`` is the raw ask; the router
    fills mode/form; the rest are optional structured inputs."""

    text: str = ""
    mode: InputMode | None = None
    form: InputForm | None = None
    target: PromptTarget | None = None
    project: ProjectIR | None = None
    source_image: str | None = None
    model_profile: ModelProfile | None = None
    system_constraints: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ClauseWeight(int, Enum):
    critical = 3
    important = 2
    optional = 1


class Clause(BaseModel):
    text: str
    weight: ClauseWeight = ClauseWeight.important
    dimension: str = "detail"

    model_config = {"extra": "forbid"}


class CompiledPrompt(BaseModel):
    target: PromptTarget
    shot_id: str | None = None
    prompt: str
    prompt_style: str = "natural"
    unsupported_requirements: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    dropped_optional: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
