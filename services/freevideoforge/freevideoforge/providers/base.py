"""Provider protocols.

Every pipeline stage talks to one of these interfaces. No stage may reach into
a vendor-specific response structure: a provider always returns one of the
plain dataclasses defined here or in :mod:`freevideoforge.models`. That is what
makes a backend (ComfyUI, a diffusion model, a cloud vendor, a future local
runtime) a replaceable implementation detail rather than an architectural
invariant.

A provider declares itself through :meth:`Provider.probe`, which must be cheap,
side-effect free, and must never download anything or use a credential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from ..models import Project, QualityReport, Scene


@dataclass
class Capability:
    """The answer to 'can this provider run here, right now?'"""

    available: bool
    name: str
    kind: str
    detail: str = ""
    #: Human-readable instructions for enabling an unavailable provider.
    remediation: str = ""
    #: True when the provider would require paid credentials or paid quota.
    requires_payment: bool = False
    #: True when enabling it needs a model download large enough to require
    #: explicit human approval.
    requires_large_download: bool = False
    version: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "available": self.available,
            "detail": self.detail,
            "remediation": self.remediation,
            "requires_payment": self.requires_payment,
            "requires_large_download": self.requires_large_download,
            "version": self.version,
            "metadata": self.metadata,
        }


@dataclass
class MediaResult:
    """A produced media file plus honest provenance.

    ``technique`` must describe what actually happened - "procedural_ffmpeg",
    "image_motion", "diffusion_video". Procedural or image-motion output is
    never labelled as diffusion video.
    """

    path: Path
    provider: str
    technique: str
    duration: float
    seed: Optional[int] = None
    model: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpeechResult:
    path: Path
    provider: str
    duration: float
    voice: str
    engine: str
    #: False when the provider produced timed silence instead of real speech.
    is_speech: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaptionResult:
    srt_path: Path
    cues: list[dict[str, Any]]
    provider: str
    #: "script_derived" or "forced_alignment"
    technique: str = "script_derived"


@runtime_checkable
class Provider(Protocol):
    """Base contract shared by every provider."""

    name: str
    kind: str

    def probe(self) -> Capability:
        """Report whether this provider can run here. Must not download or
        authenticate."""
        ...


@runtime_checkable
class ScriptProvider(Provider, Protocol):
    def generate(self, project: Project) -> dict[str, Any]:
        """Return a script document: ``{"title", "hook", "beats": [...], ...}``."""
        ...


@runtime_checkable
class StoryboardProvider(Provider, Protocol):
    def plan(self, project: Project, script: dict[str, Any]) -> list[Scene]:
        """Turn a script into fully specified scenes."""
        ...


@runtime_checkable
class ImageProvider(Provider, Protocol):
    def generate(self, project: Project, scene: Scene, output: Path) -> MediaResult:
        """Produce a still image for one scene."""
        ...


@runtime_checkable
class VideoProvider(Provider, Protocol):
    def generate(self, project: Project, scene: Scene, output: Path) -> MediaResult:
        """Produce a moving clip for one scene."""
        ...


@runtime_checkable
class SpeechProvider(Provider, Protocol):
    def synthesize(
        self, text: str, output: Path, *, voice: str = "auto", language: str = "en"
    ) -> SpeechResult:
        """Produce a WAV file for ``text``."""
        ...


@runtime_checkable
class CaptionProvider(Provider, Protocol):
    def generate(self, project: Project, output: Path) -> CaptionResult:
        """Produce caption cues and an SRT file."""
        ...


@runtime_checkable
class RenderProvider(Provider, Protocol):
    def compose(
        self,
        project: Project,
        *,
        clips: list[Path],
        audio: Optional[Path],
        output: Path,
    ) -> MediaResult:
        """Stitch scene clips and audio into the final video."""
        ...


@runtime_checkable
class QualityProvider(Provider, Protocol):
    def validate(self, project: Project, outputs: dict[str, Path]) -> QualityReport:
        """Run quality gates against the produced outputs."""
        ...
