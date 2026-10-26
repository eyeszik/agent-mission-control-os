"""VNEXUS provider-neutral media fabric: adapters, capability discovery and the render-job contract.

Adapters implement one interface (identify / capabilities / estimate /
validate / submit / status / retrieve). Three families exist:

* LOCAL   real renderers on this host: SVG composition, Chromium raster and
          PDF, Pillow WebP, Chromium frames + FFmpeg motion. Each reports
          UNAVAILABLE with its blockers when a dependency is missing.
* HOSTED  declared, DISABLED, and with no network code at all. There are no
          credentials, no verified contracts and no authorization to spend;
          ``submit`` refuses. Enabling one means writing and verifying a real
          adapter, not flipping a switch.
* MOCK    deterministic stand-ins for lifecycle tests, enabled only by
          ``AMC_VNEXUS_MOCK_PROVIDERS=1`` outside production. Everything they
          produce is marked simulated and can never be claimed as generated.

An accepted request is never reported as a generated artifact: the job
lifecycle in ``fabric_service.py`` requires received bytes that re-hash and
pass QC before ``QC_PASSED``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from .genome import _Strict

FABRIC_VERSION = "amc-vnexus-media-fabric/v1"


class Capability(str, Enum):
    VECTOR_SVG = "VECTOR_SVG"
    RASTER_PNG = "RASTER_PNG"
    RASTER_WEBP = "RASTER_WEBP"
    DOCUMENT_PDF = "DOCUMENT_PDF"
    MOTION_MP4 = "MOTION_MP4"
    TEXT_TO_IMAGE = "TEXT_TO_IMAGE"
    TEXT_TO_VIDEO = "TEXT_TO_VIDEO"
    IMAGE_TO_VIDEO = "IMAGE_TO_VIDEO"
    VIDEO_TRANSFORM = "VIDEO_TRANSFORM"


MIME = {Capability.VECTOR_SVG: "image/svg+xml", Capability.RASTER_PNG: "image/png", Capability.RASTER_WEBP: "image/webp",
        Capability.DOCUMENT_PDF: "application/pdf", Capability.MOTION_MP4: "video/mp4", Capability.TEXT_TO_IMAGE: "image/png",
        Capability.TEXT_TO_VIDEO: "video/mp4", Capability.IMAGE_TO_VIDEO: "video/mp4", Capability.VIDEO_TRANSFORM: "video/mp4"}


class ProviderKind(str, Enum):
    LOCAL = "LOCAL"
    HOSTED = "HOSTED"
    MOCK = "MOCK"


class ProviderStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class ProviderIdentity(_Strict):
    provider_id: str
    kind: ProviderKind
    version: str
    description: str


class ProviderCapabilities(_Strict):
    provider_id: str
    capabilities: tuple[Capability, ...]
    status: ProviderStatus
    blockers: tuple[str, ...] = ()
    cost_per_job_minor: int = 0
    currency: str = "USD"
    timeout_s: int = 120
    rate_limit_per_minute: int = 30
    simulated: bool = False


class MediaRequest(_Strict):
    capability: Capability
    spec: dict[str, Any] = Field(default_factory=dict)
    width: Optional[int] = Field(default=None, gt=0, le=8192)
    height: Optional[int] = Field(default=None, gt=0, le=8192)
    label: str = Field(default="", max_length=120)


class CostEstimate(_Strict):
    amount_minor: int = Field(ge=0)
    currency: str = "USD"
    basis: str


class ValidationResult(_Strict):
    ok: bool
    errors: tuple[str, ...] = ()


class ProviderJob(_Strict):
    provider_job_ref: str
    state: str  # COMPLETED | FAILED (local providers finish within submit)
    detail: str = ""


class MediaArtifact(_Strict):
    data: bytes
    mime: str
    sha256: str
    simulated: bool = False
    renderer: str
    renderer_version: Optional[str] = None


class ProviderTransientError(RuntimeError):
    """Worth retrying: a timeout, a crashed renderer, a dropped connection."""


class ProviderPermanentError(RuntimeError):
    """Not worth retrying: bad input, a disabled provider, a refused request."""


class MediaProvider(ABC):
    """The adapter contract. Local adapters complete inside ``submit`` and keep the result for ``retrieve``."""

    provider_id: str = ""
    kind: ProviderKind = ProviderKind.LOCAL
    version: str = FABRIC_VERSION
    description: str = ""

    def __init__(self) -> None:
        self._results: dict[str, Path] = {}

    def identify(self) -> ProviderIdentity:
        return ProviderIdentity(provider_id=self.provider_id, kind=self.kind, version=self.version, description=self.description)

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    def estimate(self, request: MediaRequest) -> CostEstimate:
        caps = self.capabilities()
        return CostEstimate(amount_minor=caps.cost_per_job_minor, currency=caps.currency,
                            basis="local compute only; no charge" if caps.cost_per_job_minor == 0 else "declared per-job price")

    def validate(self, request: MediaRequest) -> ValidationResult:
        caps = self.capabilities()
        errors = []
        if caps.status is not ProviderStatus.AVAILABLE:
            errors.append(f"PROVIDER_{caps.status.value}: {', '.join(caps.blockers) or 'not available'}")
        if request.capability not in caps.capabilities:
            errors.append(f"CAPABILITY_UNSUPPORTED: {request.capability.value}")
        errors += self._validate_spec(request)
        return ValidationResult(ok=not errors, errors=tuple(errors))

    def _validate_spec(self, request: MediaRequest) -> list[str]:
        return []

    def submit(self, request: MediaRequest, *, job_key: str, work_dir: Path) -> ProviderJob:
        check = self.validate(request)
        if not check.ok:
            raise ProviderPermanentError("; ".join(check.errors))
        path = self._render(request, work_dir)
        self._results[job_key] = path
        return ProviderJob(provider_job_ref=job_key, state="COMPLETED", detail=str(path.name))

    def status(self, provider_job_ref: str) -> str:
        return "COMPLETED" if provider_job_ref in self._results else "UNKNOWN"

    def retrieve(self, provider_job_ref: str) -> MediaArtifact:
        path = self._results.get(provider_job_ref)
        if path is None or not path.is_file():
            raise ProviderTransientError(f"no result for {provider_job_ref}")
        data = path.read_bytes()
        caps = self.capabilities()
        return MediaArtifact(data=data, mime=MIME[self._capability_for(path)], sha256=hashlib.sha256(data).hexdigest(),
                             simulated=caps.simulated, renderer=self.provider_id, renderer_version=self.version)

    def _capability_for(self, path: Path) -> Capability:
        return {".svg": Capability.VECTOR_SVG, ".png": Capability.RASTER_PNG, ".webp": Capability.RASTER_WEBP,
                ".pdf": Capability.DOCUMENT_PDF, ".mp4": Capability.MOTION_MP4}[path.suffix]

    @abstractmethod
    def _render(self, request: MediaRequest, work_dir: Path) -> Path: ...


# --------------------------------------------------------------------------- helpers


def svg_problems(svg: str) -> list[str]:
    """Well-formed, self-contained, script-free SVG (reuses the execution fabric's safety verifier)."""
    from services.langgraph.agency.execution_fabric.verifiers import svg_safety

    problems = []
    try:
        root = ET.fromstring(svg)
        if not root.tag.endswith("svg"):
            problems.append("SVG_ROOT_MISSING")
    except ET.ParseError as exc:
        return [f"SVG_MALFORMED: {exc}"]
    safety = svg_safety(svg)
    if not safety.passed:
        problems.append(f"SVG_UNSAFE: {safety.detail}")
    return problems


def _browser_blockers() -> list[str]:
    from services.langgraph.agency.visual.browser import probe_browser

    return list(probe_browser().get("blockers", []))


# --------------------------------------------------------------------------- local adapters


class LocalSvg(MediaProvider):
    provider_id = "local.svg"
    description = "Self-contained SVG supplied by a deterministic composer (foundry compose, identity templates)"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_id=self.provider_id, capabilities=(Capability.VECTOR_SVG,), status=ProviderStatus.AVAILABLE,
                                    timeout_s=10)

    def _validate_spec(self, request: MediaRequest) -> list[str]:
        svg = request.spec.get("svg")
        return ["SPEC_MISSING: svg"] if not isinstance(svg, str) else svg_problems(svg)

    def _render(self, request: MediaRequest, work_dir: Path) -> Path:
        out = work_dir / "out.svg"
        out.write_text(request.spec["svg"])
        return out


class LocalChromiumRaster(MediaProvider):
    provider_id = "local.chromium_raster"
    description = "Exact-size PNG of an SVG rendered by local Chromium with all remote requests blocked"

    def capabilities(self) -> ProviderCapabilities:
        blockers = _browser_blockers()
        return ProviderCapabilities(provider_id=self.provider_id, capabilities=(Capability.RASTER_PNG,),
                                    status=ProviderStatus.UNAVAILABLE if blockers else ProviderStatus.AVAILABLE, blockers=tuple(blockers))

    def _validate_spec(self, request: MediaRequest) -> list[str]:
        svg = request.spec.get("svg")
        errors = ["SPEC_MISSING: svg"] if not isinstance(svg, str) else svg_problems(svg)
        if not (request.width and request.height):
            errors.append("SPEC_MISSING: width and height")
        return errors

    def _render(self, request: MediaRequest, work_dir: Path) -> Path:
        from services.langgraph.agency.visual.browser import rasterize_svg

        r = rasterize_svg(request.spec["svg"], width=request.width, height=request.height, out_dir=work_dir)
        if r["status"] != "PASSED":
            raise ProviderTransientError("raster failed: " + ", ".join(r["findings"]))
        return Path(r["capture"])


class LocalPillowWebp(LocalChromiumRaster):
    provider_id = "local.pillow_webp"
    description = "Chromium PNG re-encoded losslessly to WebP by Pillow"

    def capabilities(self) -> ProviderCapabilities:
        blockers = _browser_blockers()
        try:
            from PIL import features

            if not features.check("webp"):
                blockers.append("MISSING_DEPENDENCY:Pillow WebP encoder")
        except ImportError:
            blockers.append("MISSING_DEPENDENCY:Pillow")
        return ProviderCapabilities(provider_id=self.provider_id, capabilities=(Capability.RASTER_WEBP,),
                                    status=ProviderStatus.UNAVAILABLE if blockers else ProviderStatus.AVAILABLE, blockers=tuple(blockers))

    def _render(self, request: MediaRequest, work_dir: Path) -> Path:
        from PIL import Image

        png = super()._render(request, work_dir)
        out = work_dir / "out.webp"
        with Image.open(png) as im:
            im.save(out, format="WEBP", lossless=True)
        return out


class LocalChromiumPdf(MediaProvider):
    provider_id = "local.chromium_pdf"
    description = "Vector PDF printed by local Chromium from self-contained HTML or SVG"

    def capabilities(self) -> ProviderCapabilities:
        blockers = _browser_blockers()
        return ProviderCapabilities(provider_id=self.provider_id, capabilities=(Capability.DOCUMENT_PDF,),
                                    status=ProviderStatus.UNAVAILABLE if blockers else ProviderStatus.AVAILABLE, blockers=tuple(blockers))

    def _validate_spec(self, request: MediaRequest) -> list[str]:
        errors = []
        if not (isinstance(request.spec.get("html"), str) or isinstance(request.spec.get("svg"), str)):
            errors.append("SPEC_MISSING: html or svg")
        if isinstance(request.spec.get("svg"), str):
            errors += svg_problems(request.spec["svg"])
        if not (request.width and request.height):
            errors.append("SPEC_MISSING: width and height")
        return errors

    def _render(self, request: MediaRequest, work_dir: Path) -> Path:
        from services.langgraph.agency.visual.browser import render_pdf

        html = request.spec.get("html") or (f"<!doctype html><html><head><style>@page{{margin:0}}html,body{{margin:0}}</style></head>"
                                             f"<body>{request.spec['svg']}</body></html>")
        r = render_pdf(html, width_px=request.width, height_px=request.height, out_dir=work_dir)
        if r["status"] != "PASSED":
            raise ProviderTransientError("pdf failed: " + ", ".join(r["findings"]))
        return Path(r["capture"])


class LocalMotion(MediaProvider):
    provider_id = "local.svg_motion"
    description = "SVG keyframes rendered frame by frame in local Chromium and encoded with FFmpeg (H.264)"

    def capabilities(self) -> ProviderCapabilities:
        blockers = _browser_blockers()
        if shutil.which("ffmpeg") is None:
            blockers.append("MISSING_DEPENDENCY:ffmpeg")
        return ProviderCapabilities(provider_id=self.provider_id, capabilities=(Capability.MOTION_MP4,), timeout_s=600,
                                    status=ProviderStatus.UNAVAILABLE if blockers else ProviderStatus.AVAILABLE, blockers=tuple(blockers))

    def _validate_spec(self, request: MediaRequest) -> list[str]:
        frames = request.spec.get("frames")
        errors = []
        if not isinstance(frames, list) or not 2 <= len(frames) <= 900:
            errors.append("SPEC_MISSING: frames (2..900 SVG strings)")
        elif any(svg_problems(f) for f in frames[:1] + frames[-1:]):
            errors.append("SVG_FRAME_INVALID")
        if not isinstance(request.spec.get("fps"), int) or not 1 <= request.spec["fps"] <= 60:
            errors.append("SPEC_MISSING: fps (1..60)")
        if not (request.width and request.height) or request.width % 2 or request.height % 2:
            errors.append("SPEC_INVALID: even width and height required for H.264")
        return errors

    def _render(self, request: MediaRequest, work_dir: Path) -> Path:
        from services.langgraph.agency.visual.browser import render_svg_frames
        from services.langgraph.agency.visual.renderers import encode_video

        fr = render_svg_frames(request.spec["frames"], width=request.width, height=request.height, out_dir=work_dir / "frames")
        if fr["status"] != "PASSED":
            raise ProviderTransientError("frames failed: " + ", ".join(fr["findings"]))
        receipt = encode_video([Path(f) for f in fr["files"]], work_dir / "out.mp4", fps=request.spec["fps"])
        if receipt.status != "SUCCEEDED":
            raise ProviderTransientError("encode failed: " + ", ".join(receipt.reasons))
        return Path(receipt.outputs[0]["path"])


# --------------------------------------------------------------------------- hosted adapters (disabled)


class DisabledHosted(MediaProvider):
    """A declared slot for a hosted generator. It has no client code and refuses every request."""

    kind = ProviderKind.HOSTED

    def __init__(self, provider_id: str, capabilities: tuple[Capability, ...], description: str) -> None:
        super().__init__()
        self.provider_id, self._caps, self.description = provider_id, capabilities, description

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_id=self.provider_id, capabilities=self._caps, status=ProviderStatus.DISABLED,
                                    blockers=("ADAPTER_NOT_IMPLEMENTED", "NO_CREDENTIALS", "PAID_CALLS_NOT_AUTHORIZED"))

    def estimate(self, request: MediaRequest) -> CostEstimate:
        return CostEstimate(amount_minor=0, basis="UNKNOWN: no verified price; a disabled provider is never quoted")

    def _render(self, request: MediaRequest, work_dir: Path) -> Path:
        raise ProviderPermanentError(f"{self.provider_id} is disabled")


# --------------------------------------------------------------------------- mock adapter (tests only)


def mock_enabled() -> bool:
    env = (os.environ.get("AMC_ENV") or "local").strip().lower()
    return os.environ.get("AMC_VNEXUS_MOCK_PROVIDERS") == "1" and env != "production"


class MockProvider(MediaProvider):
    """Deterministic simulated output for lifecycle tests. ``spec.mock`` selects a failure mode."""

    provider_id = "mock.simulated"
    kind = ProviderKind.MOCK
    description = "SIMULATED output for testing the job lifecycle; never a generated asset"
    attempts: dict[str, int] = {}

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_id=self.provider_id, capabilities=tuple(Capability),
                                    status=ProviderStatus.AVAILABLE if mock_enabled() else ProviderStatus.DISABLED,
                                    blockers=() if mock_enabled() else ("MOCK_PROVIDERS_DISABLED",),
                                    cost_per_job_minor=int(os.environ.get("AMC_VNEXUS_MOCK_COST_MINOR") or "0"), simulated=True,
                                    rate_limit_per_minute=int(os.environ.get("AMC_VNEXUS_MOCK_RATE_LIMIT") or "30"))

    def _render(self, request: MediaRequest, work_dir: Path) -> Path:
        mode = request.spec.get("mock", "ok")
        seen = MockProvider.attempts.get(request.spec.get("mock_key", ""), 0) + 1
        MockProvider.attempts[request.spec.get("mock_key", "")] = seen
        if mode == "transient" or (mode == "transient_once" and seen == 1):
            raise ProviderTransientError("simulated transient failure")
        if mode == "permanent":
            raise ProviderPermanentError("simulated permanent failure")
        out = work_dir / "out.svg"
        w, h = request.width or 64, request.height or 64
        out.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><title>SIMULATED</title>'
                       f'<rect width="{w}" height="{h}" fill="#888888"/></svg>')
        return out

    def retrieve(self, provider_job_ref: str) -> MediaArtifact:
        art = super().retrieve(provider_job_ref)
        mode_file = self._results[provider_job_ref].parent / "mode"
        if mode_file.is_file() and mode_file.read_text() == "corrupt":
            # The reported hash stays that of the original bytes, so read-back verification must catch it.
            return art.model_copy(update={"data": art.data + b"<!-- corrupted in transit -->"})
        return art

    def submit(self, request: MediaRequest, *, job_key: str, work_dir: Path) -> ProviderJob:
        job = super().submit(request, job_key=job_key, work_dir=work_dir)
        (work_dir / "mode").write_text(str(request.spec.get("mock", "ok")))
        return job


# --------------------------------------------------------------------------- registry


def _build_registry() -> dict[str, MediaProvider]:
    providers: list[MediaProvider] = [LocalSvg(), LocalChromiumRaster(), LocalPillowWebp(), LocalChromiumPdf(), LocalMotion(),
                                      DisabledHosted("hosted.text_to_image", (Capability.TEXT_TO_IMAGE,),
                                                     "Hosted text-to-image slot (no adapter installed)"),
                                      DisabledHosted("hosted.text_to_video", (Capability.TEXT_TO_VIDEO,),
                                                     "Hosted text-to-video slot (no adapter installed)"),
                                      DisabledHosted("hosted.image_to_video", (Capability.IMAGE_TO_VIDEO, Capability.VIDEO_TRANSFORM),
                                                     "Hosted image-to-video / video transform slot (no adapter installed)"),
                                      MockProvider()]
    return {p.provider_id: p for p in providers}


REGISTRY: dict[str, MediaProvider] = _build_registry()


def get_provider(provider_id: str) -> MediaProvider:
    if provider_id not in REGISTRY:
        raise LookupError(f"unknown provider {provider_id}")
    return REGISTRY[provider_id]


def discover() -> list[dict[str, Any]]:
    """Every provider with its live capability status (local probes run now)."""
    out = []
    for p in REGISTRY.values():
        caps = p.capabilities()
        out.append({**p.identify().model_dump(mode="json"), **caps.model_dump(mode="json")})
    return out


def select_provider(capability: Capability, *, allow_mock: bool = False) -> Optional[MediaProvider]:
    """The first AVAILABLE provider for a capability: local before hosted; mock only when asked for."""
    order = sorted(REGISTRY.values(), key=lambda p: {ProviderKind.LOCAL: 0, ProviderKind.HOSTED: 1, ProviderKind.MOCK: 2}[p.kind])
    for p in order:
        if p.kind is ProviderKind.MOCK and not allow_mock:
            continue
        caps = p.capabilities()
        if capability in caps.capabilities and caps.status is ProviderStatus.AVAILABLE:
            return p
    return None


def work_dir(prefix: str = "amc-vnexus-job-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def can_claim_generated(state: str, artifact: dict[str, Any]) -> bool:
    """Mirrors apps/web/lib/design/brand-genome.ts canClaimGenerated, plus the simulated flag."""
    sha = artifact.get("sha256") or ""
    return state == "QC_PASSED" and not artifact.get("simulated", True) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)


__all__ = ["Capability", "CostEstimate", "FABRIC_VERSION", "MIME", "MediaArtifact", "MediaProvider", "MediaRequest",
           "ProviderCapabilities", "ProviderIdentity", "ProviderJob", "ProviderKind", "ProviderPermanentError", "ProviderStatus",
           "ProviderTransientError", "REGISTRY", "ValidationResult", "can_claim_generated", "discover", "get_provider",
           "mock_enabled", "select_provider", "svg_problems", "work_dir"]
