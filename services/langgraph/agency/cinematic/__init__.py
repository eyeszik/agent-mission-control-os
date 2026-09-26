"""Cinematic generative compiler — a lazily-loaded domain capability.

This package integrates the UNIVERSAL_CINEMATIC_GENERATIVE_COMPILER as a
first-class, routed capability alongside the kernel and the prompt compiler.

Boundary (identical in spirit to ``prompt_compiler``'s generation firewall):
this capability compiles *validated prompts and production plans*. It never
invokes a media provider, writes a generated frame, publishes anything, or
performs any other external creative side effect. Its terminal output is a
portable, model-independent prompt package plus the canonical intermediate
representation it was compiled from.

The heavy modules (schemas, compilers, evaluator) are imported lazily through
``__getattr__`` so that merely importing ``agency`` — or routing an unrelated
mission — does not pull the full cinematic surface into memory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

CAPABILITY_ID = "cinematic-video-generation"
CAPABILITY_VERSION = "amc-cinematic/v5.0"
GENERATION_FIREWALL = "PROMPT_PACKAGE_READY"

# Name -> module attribute path for lazy resolution. Keeps import of this
# package cheap; the target module is only imported on first attribute access.
_LAZY: dict[str, tuple[str, str]] = {
    "route_request": (".router", "route_request"),
    "classify_mode": (".router", "classify_mode"),
    "classify_form": (".router", "classify_form"),
    "capability_manifest": (".router", "capability_manifest"),
    "RouteDecision": (".router", "RouteDecision"),
    "run_pipeline": (".pipeline", "run_pipeline"),
    "PipelineResult": (".pipeline", "PipelineResult"),
    "CinematicRequest": (".schemas", "CinematicRequest"),
    "ProjectIR": (".schemas", "ProjectIR"),
    "ShotIR": (".schemas", "ShotIR"),
    "ModelProfile": (".schemas", "ModelProfile"),
    "PORTABLE_PROFILE": (".adapters", "PORTABLE_PROFILE"),
}

if TYPE_CHECKING:  # pragma: no cover - import surface for type checkers only
    from .pipeline import PipelineResult, run_pipeline
    from .router import (
        RouteDecision,
        capability_manifest,
        classify_form,
        classify_mode,
        route_request,
    )
    from .schemas import CinematicRequest, ModelProfile, ProjectIR, ShotIR

__all__ = [
    "CAPABILITY_ID",
    "CAPABILITY_VERSION",
    "GENERATION_FIREWALL",
    "CinematicRequest",
    "ModelProfile",
    "PipelineResult",
    "ProjectIR",
    "RouteDecision",
    "ShotIR",
    "capability_manifest",
    "classify_form",
    "classify_mode",
    "route_request",
    "run_pipeline",
]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    module = import_module(module_name, __name__)
    return getattr(module, attr)


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *_LAZY.keys()])
