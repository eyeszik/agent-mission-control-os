"""ACE v7.1 brand-production planning primitives.

Pure, deterministic, side-effect-free foundation. The existing creative runtime,
prompt compiler, approvals, recorder and provider-gap rules remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "amc-brand-production/v1"
STATES = ("DRAFT", "REVIEW", "APPROVED", "SUPERSEDED")
CAPABILITY_ORDER = ("brand_guide", "identity", "web", "image", "video", "print", "merchandise")
GAPS = tuple(f"G{i}" for i in range(1, 21))


def canonical_bytes(value: Any) -> bytes:
    """Stable local manifest serialization; not a replacement for AMC-CANON-1."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class BrandProfile:
    brand_id: str
    name: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.brand_id.strip() or not self.name.strip():
            raise ValueError("brand_id and exact brand name are required")
        allowed = {"USER_SUPPLIED", "IMPORTED", "INFERRED", "DEFAULTED", "UNRESOLVED"}
        if any(p not in allowed for p in self.provenance.values()):
            raise ValueError("unknown provenance category")


@dataclass(frozen=True)
class StyleGuide:
    brand_id: str
    version: str
    status: str
    rules: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.status not in STATES or not self.brand_id or not self.version:
            raise ValueError("invalid guide identity or state")

    @property
    def content_hash(self) -> str:
        return digest({"brand_id": self.brand_id, "version": self.version, "rules": self.rules})


@dataclass(frozen=True)
class Project:
    project_id: str
    brand_id: str
    guide_version: str
    project_type: str
    deliverables: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all((self.project_id, self.brand_id, self.guide_version, self.project_type)):
            raise ValueError("project identity and guide pin are required")


def route(project: Project, guide: StyleGuide, available: Sequence[str] = ()) -> dict[str, Any]:
    """Plan only. No provider execution, persistence or approvals."""
    if project.brand_id != guide.brand_id or project.guide_version != guide.version:
        raise ValueError("cross-brand or unpinned guide reference")
    if guide.status not in ("APPROVED", "DRAFT", "REVIEW"):
        raise ValueError("superseded guide cannot be selected for new planning")
    requested = set(project.deliverables)
    unknown = requested.difference(CAPABILITY_ORDER)
    if unknown:
        raise ValueError(f"unsupported deliverables: {sorted(unknown)}")
    active = requested | {"brand_guide"}
    providers = set(available)
    nodes = []
    for capability in CAPABILITY_ORDER:
        if capability not in active:
            continue
        blocked = capability in {"image", "video"} and capability not in providers
        nodes.append({
            "task_id": f"{project.project_id}:{capability}",
            "capability": capability,
            "status": "BLOCKED" if blocked else "READY",
            "reason": "provider_gap" if blocked else ("shared_dependency" if capability == "brand_guide" else "requested"),
            "dependencies": [] if capability == "brand_guide" else [f"{project.project_id}:brand_guide"],
            "idempotency_class": "RETRY_SAFE",
            "execution_enabled": False,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project.project_id,
        "brand_id": project.brand_id,
        "style_guide_version": guide.version,
        "style_guide_hash": guide.content_hash,
        "guide_approval": guide.status,
        "nodes": nodes,
        "skipped": [cap for cap in CAPABILITY_ORDER if cap not in active],
        "terminal": "PLAN_READY",
        "provider_execution": "DISABLED",
    }


def compile_page_prompt(project: Project, guide: StyleGuide, page_id: str, objective: str) -> dict[str, Any]:
    if project.brand_id != guide.brand_id or project.guide_version != guide.version:
        raise ValueError("project/guide boundary mismatch")
    if not page_id.strip() or not objective.strip():
        raise ValueError("page ID and objective required")
    context = {"brand_id": project.brand_id, "guide_version": guide.version, "guide_hash": guide.content_hash,
               "page_id": page_id, "objective": objective, "rules": dict(guide.rules)}
    return {"state": "PROMPT_PACKAGE_READY", "project_id": project.project_id,
            "page_id": page_id, "context": context, "prompt_hash": digest(context),
            "generation_executed": False}


def weighted_coverage(requirements: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Critical failures override a passing weighted score."""
    if not requirements:
        return {"score": 0.0, "status": "HUMAN_APPROVAL_REQUIRED"}
    total = 0.0
    earned = 0.0
    critical = False
    for req in requirements:
        weight = float(req["weight"])
        if weight <= 0 or weight == float("inf") or weight != weight:
            raise ValueError("weights must be finite positive values")
        total += weight
        verified = req.get("status") == "VERIFIED"
        earned += weight if verified else 0.0
        critical |= bool(req.get("critical")) and not verified
    score = earned / total
    return {"score": round(score, 6), "status": "HUMAN_APPROVAL_REQUIRED" if critical or score < 0.8 else "PROCEED",
            "critical_blocker": critical}
