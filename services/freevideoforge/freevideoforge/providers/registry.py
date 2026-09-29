"""Provider registry and the capability resolver.

The resolver implements the AUTO ladder:

    verified local video backend  -> LOCAL_VIDEO
    else local image backend      -> IMAGE_MOTION
    else                          -> FFMPEG_MOTION

``FFMPEG_MOTION`` is mandatory, always registered, and depends on no AI
inference whatsoever. If the first two tiers are unavailable the pipeline
degrades to it silently and says so truthfully in the manifest.

Free mode is enforced here: a provider whose capability reports
``requires_payment`` is refused unless the caller explicitly opted in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from ..errors import PaidProviderRejected, ProviderUnavailable
from .base import Capability, Provider

#: Rendering tiers, best first.
TIER_LOCAL_VIDEO = "local_video"
TIER_IMAGE_MOTION = "image_motion"
TIER_FFMPEG_MOTION = "ffmpeg_motion"

TIER_ORDER = (TIER_LOCAL_VIDEO, TIER_IMAGE_MOTION, TIER_FFMPEG_MOTION)

#: Capability tier letters used in reporting.
TIER_LETTER = {
    TIER_LOCAL_VIDEO: "A",
    TIER_IMAGE_MOTION: "B",
    TIER_FFMPEG_MOTION: "C",
}


@dataclass
class Registration:
    name: str
    kind: str
    factory: Callable[[], Provider]
    #: Lower sorts first within a kind.
    priority: int = 100
    tier: Optional[str] = None


class ProviderRegistry:
    """Holds provider factories and resolves them against the live host."""

    def __init__(self, *, allow_paid: bool = False) -> None:
        self._registrations: list[Registration] = []
        self._instances: dict[str, Provider] = {}
        self._capabilities: dict[str, Capability] = {}
        self.allow_paid = allow_paid

    # -- registration ----------------------------------------------------
    def register(
        self,
        name: str,
        kind: str,
        factory: Callable[[], Provider],
        *,
        priority: int = 100,
        tier: Optional[str] = None,
    ) -> None:
        self._registrations = [r for r in self._registrations if r.name != name]
        self._registrations.append(
            Registration(name=name, kind=kind, factory=factory, priority=priority, tier=tier)
        )
        self._registrations.sort(key=lambda r: (r.kind, r.priority, r.name))

    def registrations(self, kind: str | None = None) -> list[Registration]:
        return [r for r in self._registrations if kind is None or r.kind == kind]

    # -- instantiation / probing ----------------------------------------
    def instance(self, name: str) -> Provider:
        if name not in self._instances:
            registration = next((r for r in self._registrations if r.name == name), None)
            if registration is None:
                raise ProviderUnavailable(f"No provider registered under {name!r}")
            self._instances[name] = registration.factory()
        return self._instances[name]

    def capability(self, name: str, *, refresh: bool = False) -> Capability:
        """Probe a provider, caching the result. A provider that raises during
        probe is reported unavailable rather than crashing discovery."""
        if refresh or name not in self._capabilities:
            registration = next((r for r in self._registrations if r.name == name), None)
            if registration is None:
                raise ProviderUnavailable(f"No provider registered under {name!r}")
            try:
                self._capabilities[name] = self.instance(name).probe()
            except Exception as exc:  # a broken optional provider must not break discovery
                self._capabilities[name] = Capability(
                    available=False,
                    name=name,
                    kind=registration.kind,
                    detail=f"probe raised {type(exc).__name__}: {exc}",
                    remediation="See the provider's own documentation.",
                )
        return self._capabilities[name]

    def discover(self, *, refresh: bool = False) -> dict[str, Capability]:
        return {
            registration.name: self.capability(registration.name, refresh=refresh)
            for registration in self._registrations
        }

    # -- selection -------------------------------------------------------
    def _allowed(self, capability: Capability) -> bool:
        if capability.requires_payment and not self.allow_paid:
            return False
        return capability.available

    def select(
        self,
        kind: str,
        *,
        requested: str = "auto",
        fallback: Optional[str] = None,
    ) -> Provider:
        """Pick a provider of ``kind``.

        An explicit request is honoured or fails loudly - it is never silently
        swapped for something else. ``auto`` walks the priority order and takes
        the first available, free provider.
        """
        candidates = self.registrations(kind)
        if not candidates:
            raise ProviderUnavailable(f"No providers registered for kind {kind!r}")

        if requested and requested not in {"auto", ""}:
            match = next((r for r in candidates if r.name == requested), None)
            if match is None:
                names = ", ".join(r.name for r in candidates) or "none"
                raise ProviderUnavailable(
                    f"Unknown {kind} provider {requested!r}. Available: {names}"
                )
            capability = self.capability(requested)
            if capability.requires_payment and not self.allow_paid:
                raise PaidProviderRejected(
                    f"Provider {requested!r} requires paid credentials and FreeVideoForge "
                    "runs in free mode. Re-run with --allow-paid only if you accept the "
                    "cost, or pick a free local provider."
                )
            if not capability.available:
                raise ProviderUnavailable(
                    f"Provider {requested!r} is not available here: {capability.detail}\n"
                    f"{capability.remediation}"
                )
            return self.instance(requested)

        for registration in candidates:
            if self._allowed(self.capability(registration.name)):
                return self.instance(registration.name)

        if fallback:
            capability = self.capability(fallback)
            if self._allowed(capability):
                return self.instance(fallback)
            raise ProviderUnavailable(
                f"Mandatory fallback {fallback!r} is unavailable: {capability.detail}\n"
                f"{capability.remediation}"
            )
        details = "; ".join(
            f"{name}: {cap.detail or 'unavailable'}"
            for name, cap in self.discover().items()
            if cap.kind == kind
        )
        raise ProviderUnavailable(f"No usable {kind} provider on this host. {details}")

    def resolve_visual_tier(self, requested: str = "auto") -> str:
        """Return the rendering tier that will actually be used."""
        if requested in {TIER_LOCAL_VIDEO, TIER_IMAGE_MOTION, TIER_FFMPEG_MOTION}:
            return requested
        if requested not in {"auto", "", None}:
            raise ProviderUnavailable(
                f"Unknown preset {requested!r}. Use auto, {TIER_LOCAL_VIDEO}, "
                f"{TIER_IMAGE_MOTION} or {TIER_FFMPEG_MOTION}."
            )
        for tier, kind in (
            (TIER_LOCAL_VIDEO, "video"),
            (TIER_IMAGE_MOTION, "image"),
        ):
            for registration in self.registrations(kind):
                if registration.tier == tier and self._allowed(
                    self.capability(registration.name)
                ):
                    return tier
        return TIER_FFMPEG_MOTION

    def summary(self) -> dict[str, Any]:
        """Discovery report used by `doctor`, the UI and the manifest."""
        capabilities = self.discover()
        active = [c.as_dict() for c in capabilities.values() if self._allowed(c)]
        unavailable = [c.as_dict() for c in capabilities.values() if not self._allowed(c)]
        return {
            "active": active,
            "unavailable": unavailable,
            "visual_tier": self.resolve_visual_tier(),
            "allow_paid": self.allow_paid,
        }


def build_default_registry(settings, *, allow_paid: bool = False) -> ProviderRegistry:
    """Register every built-in provider.

    Imports are local so an optional provider with a missing import can never
    stop the mandatory FFmpeg path from loading.
    """
    from .captions_script import ScriptDerivedCaptionProvider
    from .image_local import LocalImageProvider
    from .quality_structural import StructuralQualityProvider
    from .render_ffmpeg import FFmpegMotionRenderProvider
    from .script_ollama import OllamaScriptProvider
    from .script_template import TemplateScriptProvider
    from .speech_espeak import EspeakSpeechProvider
    from .speech_piper import PiperSpeechProvider
    from .speech_silence import SilenceSpeechProvider
    from .storyboard_planner import DeterministicStoryboardProvider
    from .video_local import LocalVideoProvider

    registry = ProviderRegistry(allow_paid=allow_paid)

    # Script: prefer a local LLM when one genuinely exists, else deterministic.
    registry.register("ollama", "script", lambda: OllamaScriptProvider(settings), priority=10)
    registry.register("template", "script", lambda: TemplateScriptProvider(), priority=90)

    registry.register(
        "deterministic", "storyboard", lambda: DeterministicStoryboardProvider(), priority=10
    )

    # Speech: real local TTS first, timed silence as the always-available floor.
    registry.register("piper", "speech", lambda: PiperSpeechProvider(settings), priority=10)
    registry.register("espeak", "speech", lambda: EspeakSpeechProvider(settings), priority=20)
    registry.register("silence", "speech", lambda: SilenceSpeechProvider(settings), priority=90)

    registry.register(
        "script_derived", "captions", lambda: ScriptDerivedCaptionProvider(), priority=10
    )

    # Optional local generative media. Both probe only; neither downloads.
    registry.register(
        "local_video", "video", lambda: LocalVideoProvider(settings),
        priority=10, tier=TIER_LOCAL_VIDEO,
    )
    registry.register(
        "local_image", "image", lambda: LocalImageProvider(settings),
        priority=10, tier=TIER_IMAGE_MOTION,
    )

    # Mandatory renderer. Always last, always free, never AI dependent.
    registry.register(
        "ffmpeg_motion", "render", lambda: FFmpegMotionRenderProvider(settings),
        priority=10, tier=TIER_FFMPEG_MOTION,
    )
    registry.register(
        "structural", "quality", lambda: StructuralQualityProvider(settings), priority=10
    )
    return registry
