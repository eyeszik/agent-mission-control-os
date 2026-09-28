"""Canonical semantic hashing for compiled-agency objects.

Every structural hash here goes through the N4 registry's
``content_fingerprint`` (sorted keys, compact separators) so there is one
canonical serialization in the codebase. Callers pass only semantically
meaningful fields: no wall-clock timestamps, no random ids.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

from services.langgraph.agency.kernel.registry import content_fingerprint


def _canonical(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(v) for v in value), key=lambda v: content_fingerprint(v))
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="json"))
    return value


def semantic_hash(payload: Any, *, exclude: Iterable[str] = ()) -> str:
    """Hash ``payload`` canonically, dropping top-level ``exclude`` keys."""
    canonical = _canonical(payload)
    if isinstance(canonical, dict):
        skip = set(exclude)
        canonical = {k: v for k, v in canonical.items() if k not in skip}
    return content_fingerprint(canonical)


def closure_hash(pairs: Iterable[tuple[str, str]]) -> str:
    """Order-independent hash over ``(ref, hash)`` pairs."""
    return content_fingerprint(sorted([list(p) for p in pairs]))
