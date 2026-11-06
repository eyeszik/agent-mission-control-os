"""Declarative creative capability registry (``knowledge/creative-capabilities``).

The registry is data: ``registry.json`` lists every ``CreativeCapability``
with its disposition against existing repository owners (REUSE_EXISTING /
EXTEND_EXISTING / COMPOSE_EXISTING / ADD_NEW / DOCUMENTATION_ONLY / BLOCKED)
and the SHA-256 of each corpus workflow guide it was derived from. The
runtime never modifies it.

Loading is the immune system's first line. Each capability is checked for:
- guide integrity: a missing guide or hash mismatch degrades the capability
  (``CORPUS_INVALID``);
- guide injection: the repository scanner quarantines the source
  (``QUARANTINE_SOURCE``);
- dependency closure (``DEPENDENCY_VOID``) and conflict symmetry;
- duplicate ids (``CAPABILITY_DUPLICATE``): the whole registry is degraded.

Implementations are resolved lazily, so an unimportable binding degrades only
its capability.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.langgraph.agency.compiled.role_sources import scan_for_injection
from services.langgraph.agency.execution.canonical import canonical_hash

REGISTRY_ROOT = Path(__file__).resolve().parents[4] / "knowledge" / "creative-capabilities"
REGISTRY_SCHEMA = "amc-creative-capabilities/v1"

Disposition = Literal["REUSE_EXISTING", "EXTEND_EXISTING", "COMPOSE_EXISTING", "ADD_NEW", "DOCUMENTATION_ONLY", "BLOCKED"]
Status = Literal["implemented", "guidance_only", "provider_gap", "blocked"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GuideRef(_Strict):
    path: str = Field(pattern=r"^guides/[a-z0-9-]+\.md$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SourceProvenance(_Strict):
    guides: tuple[GuideRef, ...] = ()
    repository_owner: Optional[str] = None


class CreativeCapability(_Strict):
    id: str = Field(pattern=r"^cap\.[a-z0-9_.]+$")
    version: str
    disposition: Disposition
    status: Status
    stages: tuple[str, ...]
    artifact_types: tuple[str, ...]
    provides: tuple[str, ...]
    consumes: tuple[str, ...]
    required_dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    model_requirements: tuple[str, ...] = ()
    cost_class: Literal["zero", "model"]
    latency_class: Literal["ms", "s"]
    idempotency_class: Literal["RETRY_SAFE", "RETRY_SAFE_VERSIONED", "NON_RETRYABLE"]
    validators: tuple[str, ...] = ()
    implementation: Optional[str] = None
    source_provenance: SourceProvenance
    rationale: str = ""

    @property
    def executable(self) -> bool:
        return self.status == "implemented" and self.implementation is not None


class RegistryLoad(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["OK", "DEGRADED"]
    registry_hash: Optional[str]
    capabilities: dict[str, CreativeCapability]
    degraded: dict[str, str]
    quarantined: dict[str, str]
    errors: tuple[str, ...] = ()

    def usable(self, cap_id: str) -> bool:
        return cap_id in self.capabilities and cap_id not in self.degraded and cap_id not in self.quarantined

    def versions(self, cap_ids: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(f"{c}@{self.capabilities[c].version}" for c in cap_ids if c in self.capabilities))


class CapabilityDuplicate(ValueError):
    code = "CAPABILITY_DUPLICATE"


def _guide_checks(root: Path, cap: CreativeCapability) -> tuple[Optional[str], Optional[str]]:
    """(degrade_reason, quarantine_reason) for the capability's guides."""
    for ref in cap.source_provenance.guides:
        path = (root / ref.path).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            return f"CORPUS_INVALID: guide missing {ref.path}", None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != ref.sha256:
            return f"CORPUS_INVALID: guide hash mismatch {ref.path}", None
        flags = scan_for_injection(data.decode("utf-8", errors="replace"))
        if flags:
            return None, f"QUARANTINE_SOURCE: {ref.path} {list(flags)}"
    return None, None


def load_registry(root: Path | None = None) -> RegistryLoad:
    root = Path(root or REGISTRY_ROOT)
    try:
        raw = json.loads((root / "registry.json").read_text(encoding="utf-8"))
        if raw.get("schema_version") != REGISTRY_SCHEMA:
            raise ValueError("unsupported registry schema_version")
        items = [CreativeCapability.model_validate(c) for c in raw.get("capabilities", [])]
    except (OSError, ValueError, ValidationError) as exc:
        return RegistryLoad(status="DEGRADED", registry_hash=None, capabilities={}, degraded={}, quarantined={},
                            errors=(f"CORPUS_INVALID: registry unreadable: {type(exc).__name__}",))
    ids = [c.id for c in items]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        return RegistryLoad(status="DEGRADED", registry_hash=None, capabilities={}, degraded={}, quarantined={},
                            errors=tuple(f"CAPABILITY_DUPLICATE: {d}" for d in duplicates))
    caps = {c.id: c for c in items}
    degraded: dict[str, str] = {}
    quarantined: dict[str, str] = {}
    errors: list[str] = []
    for cap in items:
        degrade, quarantine = _guide_checks(root, cap)
        if quarantine:
            quarantined[cap.id] = quarantine
        elif degrade:
            degraded[cap.id] = degrade
        missing = [d for d in cap.required_dependencies if d not in caps]
        if missing:
            degraded[cap.id] = f"DEPENDENCY_VOID: {missing}"
        for other in cap.conflicts:
            if other not in caps or cap.id not in caps[other].conflicts:
                errors.append(f"conflict {cap.id}/{other} is not symmetric")
    # A capability whose required dependency is unusable is unusable too.
    changed = True
    while changed:
        changed = False
        for cap in items:
            if cap.id in degraded or cap.id in quarantined:
                continue
            bad = [d for d in cap.required_dependencies if d in degraded or d in quarantined]
            if bad:
                degraded[cap.id] = f"DEPENDENCY_VOID: {bad}"
                changed = True
    return RegistryLoad(
        status="DEGRADED" if errors or degraded or quarantined else "OK",
        registry_hash=canonical_hash(raw),
        capabilities=caps,
        degraded=dict(sorted(degraded.items())),
        quarantined=dict(sorted(quarantined.items())),
        errors=tuple(sorted(errors)),
    )


@lru_cache(maxsize=4)
def default_registry() -> RegistryLoad:
    return load_registry(REGISTRY_ROOT)


def with_capability(registry: RegistryLoad, cap: CreativeCapability) -> RegistryLoad:
    """Registering the identical definition is a no-op (never double-executes);
    a different definition under an existing id is rejected."""
    existing = registry.capabilities.get(cap.id)
    if existing is not None:
        if existing == cap:
            return registry
        raise CapabilityDuplicate(f"capability {cap.id} is already registered with a different definition")
    caps = {**registry.capabilities, cap.id: cap}
    return registry.model_copy(update={"capabilities": dict(sorted(caps.items()))})


def resolve_implementation(cap: CreativeCapability) -> Any:
    """Import the bound callable. Raises LookupError (DEPENDENCY_VOID) if absent."""
    if not cap.implementation:
        raise LookupError(f"DEPENDENCY_VOID: {cap.id} has no implementation binding")
    module, _, attr = cap.implementation.partition(":")
    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as exc:
        raise LookupError(f"DEPENDENCY_VOID: {cap.implementation}") from exc


def capabilities_for(registry: RegistryLoad, artifact_type: str, stage: str) -> list[CreativeCapability]:
    return sorted(
        (c for c in registry.capabilities.values() if artifact_type in c.artifact_types and stage in c.stages),
        key=lambda c: c.id,
    )


def disposition_table(registry: RegistryLoad) -> list[dict[str, Any]]:
    return [
        {"id": c.id, "disposition": c.disposition, "status": c.status, "owner": c.source_provenance.repository_owner,
         "guides": [g.path for g in c.source_provenance.guides], "rationale": c.rationale}
        for c in sorted(registry.capabilities.values(), key=lambda c: c.id)
    ]


__all__ = [
    "CapabilityDuplicate",
    "CreativeCapability",
    "REGISTRY_ROOT",
    "RegistryLoad",
    "capabilities_for",
    "default_registry",
    "disposition_table",
    "load_registry",
    "resolve_implementation",
    "with_capability",
]
