"""Governed intake: intent -> project -> memory/context -> execution -> verification -> approval.

See :mod:`.runner` for the end-to-end path and ``docs/intake-mission.md``.
"""

from .context import compile_context, project_fingerprint
from .contracts import (
    ArtifactVerification,
    CompiledIntent,
    ContextCapsule,
    Deliverable,
    ExecutionMode,
    MemoryUseReceipt,
    MissionContract,
    MissionOutcome,
    NonActionReceipt,
    PredicateState,
    ProjectResolutionReceipt,
    ReleaseVerdict,
    SideEffect,
)
from .intent import compile_intent
from .resolver import resolve_project
from .runner import (
    MissionNotReleasable,
    release_gate,
    request_release_approval,
    run_mission,
    verify_artifact,
)

__all__ = [
    "ArtifactVerification",
    "CompiledIntent",
    "ContextCapsule",
    "Deliverable",
    "ExecutionMode",
    "MemoryUseReceipt",
    "MissionContract",
    "MissionNotReleasable",
    "MissionOutcome",
    "NonActionReceipt",
    "PredicateState",
    "ProjectResolutionReceipt",
    "ReleaseVerdict",
    "SideEffect",
    "compile_context",
    "compile_intent",
    "project_fingerprint",
    "release_gate",
    "request_release_approval",
    "resolve_project",
    "run_mission",
    "verify_artifact",
]
