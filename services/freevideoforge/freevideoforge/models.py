"""Typed domain models.

Everything the pipeline passes between stages is one of these dataclasses. They
are plain stdlib dataclasses (no third-party validation library) so the package
stays installable with a single runtime dependency, and every model round-trips
through JSON so state is inspectable and resumable from another process.

The CREATIVE_COMPILER separation is enforced structurally:

* ``Scene.content``  - CONTENT_SPEC: what is communicated.
* ``Scene.visual``   - VISUAL_SPEC:  what is seen.
* ``Scene.motion``   - MOTION_SPEC:  how it moves.
* ``Project.render`` - RENDER_SPEC:  how it is encoded.

No stage packs all four concerns into a single opaque prompt string.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .errors import ConfigError

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class Aspect(str, enum.Enum):
    """Supported output aspect ratios."""

    VERTICAL = "9:16"
    SQUARE = "1:1"
    LANDSCAPE = "16:9"
    CLASSIC = "4:5"

    @property
    def ratio(self) -> float:
        w, h = (int(part) for part in self.value.split(":"))
        return w / h

    def resolution(self, height: int) -> tuple[int, int]:
        """Return an even-dimension (width, height) pair for the given height."""
        width = int(round(height * self.ratio))
        return (width - width % 2, height - height % 2)

    @classmethod
    def parse(cls, raw: str | "Aspect") -> "Aspect":
        if isinstance(raw, cls):
            return raw
        text = str(raw).strip().replace("x", ":").replace("/", ":")
        for member in cls:
            if member.value == text:
                return member
        raise ConfigError(
            f"Unsupported aspect {raw!r}. Supported: {', '.join(m.value for m in cls)}"
        )


class JobState(str, enum.Enum):
    """Job finite state machine.

    ``TERMINAL_STATES`` never resume; every other state resumes from the last
    valid artifact recorded in the run store.
    """

    CREATED = "CREATED"
    PLANNING = "PLANNING"
    SCRIPT_READY = "SCRIPT_READY"
    STORYBOARD_READY = "STORYBOARD_READY"
    MEDIA_GENERATING = "MEDIA_GENERATING"
    MEDIA_READY = "MEDIA_READY"
    AUDIO_GENERATING = "AUDIO_GENERATING"
    AUDIO_READY = "AUDIO_READY"
    COMPOSING = "COMPOSING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Linear happy-path order. Index position is used to decide what a resumed run
#: may skip.
STATE_ORDER: tuple[JobState, ...] = (
    JobState.CREATED,
    JobState.PLANNING,
    JobState.SCRIPT_READY,
    JobState.STORYBOARD_READY,
    JobState.MEDIA_GENERATING,
    JobState.MEDIA_READY,
    JobState.AUDIO_GENERATING,
    JobState.AUDIO_READY,
    JobState.COMPOSING,
    JobState.VALIDATING,
    JobState.COMPLETED,
)

TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.CANCELLED})
RESUMABLE_STATES = frozenset(set(JobState) - TERMINAL_STATES)


def state_index(state: JobState) -> int:
    try:
        return STATE_ORDER.index(state)
    except ValueError:
        # FAILED / CANCELLED are off the linear path.
        return -1


# --------------------------------------------------------------------------
# Creative specification models
# --------------------------------------------------------------------------


@dataclass
class ContentSpec:
    """CONTENT_SPEC - what this scene communicates."""

    narrative_function: str = "body"
    voiceover: str = ""
    text_overlay: str = ""
    kicker: str = ""
    key_point: str = ""


@dataclass
class VisualSpec:
    """VISUAL_SPEC - what is seen. Renderer-agnostic."""

    visual_subject: str = ""
    environment: str = ""
    composition: str = "centered"
    shot_size: str = "medium"
    lighting: str = "soft key"
    palette: list[str] = field(default_factory=list)
    motif: str = "rings"
    continuity: str = ""
    media_prompt: str = ""
    negative_constraints: list[str] = field(default_factory=list)


@dataclass
class MotionSpec:
    """MOTION_SPEC - how the scene moves."""

    camera: str = "slow push in"
    motion: str = "push_in"
    zoom_start: float = 1.0
    zoom_end: float = 1.08
    pan_x: float = 0.0
    pan_y: float = 0.0
    parallax: float = 0.35
    transition: str = "fade"
    transition_seconds: float = 0.4


@dataclass
class RenderSpec:
    """RENDER_SPEC - how the result is encoded."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 20
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    audio_sample_rate: int = 44100
    audio_bitrate: str = "160k"
    burn_captions: bool = True

    def validate(self) -> None:
        if self.width % 2 or self.height % 2:
            raise ConfigError("Encoded dimensions must be even for yuv420p H.264")
        if not (1 <= self.fps <= 120):
            raise ConfigError(f"fps out of range: {self.fps}")
        if not (0 <= self.crf <= 51):
            raise ConfigError(f"crf out of range: {self.crf}")


@dataclass
class Scene:
    """One storyboard beat."""

    id: str
    index: int
    duration: float
    content: ContentSpec = field(default_factory=ContentSpec)
    visual: VisualSpec = field(default_factory=VisualSpec)
    motion: MotionSpec = field(default_factory=MotionSpec)
    seed: int = 0
    #: Populated during rendering.
    clip_path: Optional[str] = None
    audio_path: Optional[str] = None
    audio_duration: Optional[float] = None
    state: str = "PENDING"
    attempts: int = 0
    error: Optional[str] = None
    input_hash: Optional[str] = None

    def validate(self) -> None:
        if self.duration <= 0:
            raise ConfigError(f"Scene {self.id} has non-positive duration {self.duration}")


@dataclass
class Asset:
    """A produced file plus its provenance."""

    kind: str
    path: str
    sha256: str
    bytes: int
    provider: str
    scene_id: Optional[str] = None
    duration: Optional[float] = None
    created_at: float = field(default_factory=time.time)


@dataclass
class Project:
    """The compiled brief: everything needed to render, before any media exists."""

    run_id: str
    topic: str
    brief: str = ""
    intent: str = "educate"
    audience: str = "curious general audience"
    format: str = "short-form explainer"
    duration: float = 30.0
    aspect: Aspect = Aspect.VERTICAL
    style_system: str = "editorial"
    narration_strategy: str = "single narrator, second person, plain language"
    language: str = "en"
    seed: int = 0
    scenes: list[Scene] = field(default_factory=list)
    render: RenderSpec = field(default_factory=RenderSpec)
    providers: dict[str, str] = field(default_factory=dict)

    @property
    def total_scene_duration(self) -> float:
        return round(sum(scene.duration for scene in self.scenes), 3)

    def validate(self) -> None:
        if not self.topic.strip():
            raise ConfigError("Project topic must not be empty")
        if not self.scenes:
            raise ConfigError("Project has no scenes")
        self.render.validate()
        for scene in self.scenes:
            scene.validate()


@dataclass
class QualityCheck:
    """One QC result.

    ``status`` is deliberately one of PASS / FAIL / NOT_APPLICABLE /
    NOT_VERIFIED. A check with no reliable evaluator reports NOT_VERIFIED and is
    never silently upgraded to PASS.
    """

    id: str
    category: str  # "structural" | "creative"
    status: str
    detail: str = ""
    expected: Any = None
    observed: Any = None

    @property
    def mandatory(self) -> bool:
        return self.category == "structural"


@dataclass
class QualityReport:
    run_id: str
    checks: list[QualityCheck] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    @property
    def structural_failures(self) -> list[QualityCheck]:
        return [c for c in self.checks if c.mandatory and c.status == "FAIL"]

    @property
    def passed(self) -> bool:
        return not self.structural_failures

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return counts


@dataclass
class Manifest:
    """Full provenance record for one run."""

    run_id: str
    version: str
    created_at: float
    completed_at: Optional[float]
    config_hash: str
    project: dict[str, Any]
    providers: dict[str, Any]
    assets: list[dict[str, Any]]
    outputs: dict[str, str]
    environment: dict[str, Any]
    zero_paid_api_spend: bool = True
    credentials_used: list[str] = field(default_factory=list)


@dataclass
class GenerateRequest:
    """The public request object for a generation run.

    This is the stable contract used by the CLI, the local web UI and any
    external automation system. Adding optional fields is backwards compatible;
    nothing here is vendor specific.
    """

    topic: str
    brief: str = ""
    duration: float = 30.0
    aspect: str = "9:16"
    preset: str = "auto"
    style: str = "auto"
    scenes: Optional[int] = None
    fps: int = 30
    height: Optional[int] = None
    voice: str = "auto"
    music: str = "ambient"
    seed: Optional[int] = None
    language: str = "en"
    burn_captions: bool = True
    output_dir: Optional[str] = None
    run_id: Optional[str] = None
    allow_paid: bool = False
    script_provider: str = "auto"
    speech_provider: str = "auto"
    quality_preset: str = "balanced"

    def validate(self) -> None:
        if not self.topic or not self.topic.strip():
            raise ConfigError("topic is required and must not be empty")
        if not (3.0 <= float(self.duration) <= 600.0):
            raise ConfigError(
                f"duration must be between 3 and 600 seconds, got {self.duration}"
            )
        Aspect.parse(self.aspect)
        if not (1 <= int(self.fps) <= 120):
            raise ConfigError(f"fps must be between 1 and 120, got {self.fps}")
        if self.scenes is not None and not (1 <= int(self.scenes) <= 60):
            raise ConfigError(f"scenes must be between 1 and 60, got {self.scenes}")
        if self.quality_preset not in {"draft", "balanced", "high"}:
            raise ConfigError(
                f"quality_preset must be draft|balanced|high, got {self.quality_preset!r}"
            )
        if self.music not in {"none", "ambient"}:
            raise ConfigError(f"music must be none|ambient, got {self.music!r}")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerateRequest":
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(payload) - known
        if unknown:
            raise ConfigError(f"Unknown request fields: {', '.join(sorted(unknown))}")
        return cls(**payload)


@dataclass
class RunResult:
    """What a completed (or failed) run hands back to its caller."""

    run_id: str
    state: JobState
    output_dir: str
    final_video: Optional[str] = None
    thumbnail: Optional[str] = None
    script: Optional[str] = None
    storyboard: Optional[str] = None
    captions: Optional[str] = None
    manifest: Optional[str] = None
    quality_report: Optional[str] = None
    duration: Optional[float] = None
    providers: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.state is JobState.COMPLETED


# --------------------------------------------------------------------------
# JSON helpers
# --------------------------------------------------------------------------


def to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/enums/Paths into JSON-safe values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: to_jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def dump_json(value: Any, path: Path) -> Path:
    """Write ``value`` as pretty, deterministic JSON and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(value), indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = 48) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (slug[:max_length].rstrip("-")) or "untitled"


def scene_from_dict(payload: dict[str, Any]) -> Scene:
    """Rebuild a Scene from its JSON form (used when resuming a run)."""
    data = dict(payload)
    content = ContentSpec(**data.pop("content", {}) or {})
    visual = VisualSpec(**data.pop("visual", {}) or {})
    motion = MotionSpec(**data.pop("motion", {}) or {})
    known = {f.name for f in dataclasses.fields(Scene)}
    data = {k: v for k, v in data.items() if k in known}
    data.pop("content", None)
    data.pop("visual", None)
    data.pop("motion", None)
    return Scene(content=content, visual=visual, motion=motion, **data)


def project_from_dict(payload: dict[str, Any]) -> Project:
    """Rebuild a Project from its JSON form (used when resuming a run)."""
    data = dict(payload)
    scenes = [scene_from_dict(s) for s in data.pop("scenes", [])]
    render = RenderSpec(**(data.pop("render", {}) or {}))
    data["aspect"] = Aspect.parse(data.get("aspect", Aspect.VERTICAL.value))
    known = {f.name for f in dataclasses.fields(Project)}
    data = {k: v for k, v in data.items() if k in known and k not in {"scenes", "render"}}
    return Project(scenes=scenes, render=render, **data)


def iter_scene_words(scenes: Iterable[Scene]) -> int:
    return sum(len(scene.content.voiceover.split()) for scene in scenes)
