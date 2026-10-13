"""Opt-in ACE v100 pure contracts and decisions; never executes external effects."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RiskTier(str, Enum):
    READ = "R0"
    LOCAL = "R1"
    CODE = "R2"
    EXTERNAL = "R3"
    CONSEQUENTIAL = "R4"
    IRREVERSIBLE = "R5"


class Mission(StrictModel):
    schema_version: Literal["ace.mission.v1"] = "ace.mission.v1"
    mission_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=10000)
    constraints: dict[str, Any] = Field(default_factory=dict)
    policy_version: str = Field(min_length=1)


class Task(StrictModel):
    schema_version: Literal["ace.task.v1"] = "ace.task.v1"
    task_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    dependencies: tuple[str, ...] = ()
    capability: str = Field(min_length=1)
    risk_tier: RiskTier = RiskTier.READ
    deadline: datetime | None = None

    @model_validator(mode="after")
    def validate_task(self) -> "Task":
        if self.task_id in self.dependencies or len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("self or duplicate dependencies")
        if self.deadline and (self.deadline.tzinfo is None or self.deadline.utcoffset() is None):
            raise ValueError("deadline must be timezone aware")
        return self


class Capability(StrictModel):
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    capabilities: frozenset[str] = Field(min_length=1)
    complexity_ceiling: int = Field(ge=1, le=5)
    available: bool = True
    priority: int = Field(ge=0)
    rate_limit_per_minute: int = Field(gt=0)
    cost_per_million_tokens: float = Field(ge=0, allow_inf_nan=False)


class EvidenceItem(StrictModel):
    claim_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    observed_at: datetime
    status: Literal["VERIFIED", "FLAGGED", "VOID", "SPECULATIVE"]
    metadata_digest: str = Field(pattern="^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def require_tz(self) -> "EvidenceItem":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("evidence observed_at must be timezone-aware")
        return self


class AuditRecord(StrictModel):
    sequence: int = Field(ge=1)
    previous_hash: str = Field(pattern="^[a-f0-9]{64}$")
    payload_digest: str = Field(pattern="^[a-f0-9]{64}$")
    record_hash: str = Field(pattern="^[a-f0-9]{64}$")
    signature: str = Field(pattern="^[a-f0-9]{64}$")


def canonical_hash(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    try:
        serialized = json.dumps(value, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("not canonical JSON") from exc
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def effect_operation_key(*, tenant_id: str, project_id: str, operation: str, payload: Any) -> str:
    if not all((tenant_id, project_id, operation)):
        raise ValueError("scope and operation required")
    return canonical_hash({"tenant": tenant_id, "project": project_id,
                           "operation": operation, "payload": payload})


def topological_order(tasks: tuple[Task, ...]) -> tuple[str, ...]:
    indexed = {task.task_id: task for task in tasks}
    if len(indexed) != len(tasks) or len({task.mission_id for task in tasks}) > 1:
        raise ValueError("duplicate task or mixed mission")
    children: dict[str, list[str]] = {key: [] for key in indexed}
    degree = {task.task_id: len(task.dependencies) for task in tasks}
    for task in tasks:
        for dependency in task.dependencies:
            if dependency not in indexed:
                raise ValueError("missing dependency")
            children[dependency].append(task.task_id)
    ready = sorted(key for key, count in degree.items() if count == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for child in children[current]:
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(ordered) != len(tasks):
        raise ValueError("cyclic DAG")
    return tuple(ordered)


def route_capability(*, required: str, complexity: int, providers: tuple[Capability, ...],
                     allowed_providers: frozenset[str],
                     disabled: frozenset[str] = frozenset()) -> tuple[Capability, ...]:
    if complexity not in range(1, 6) or not required or not allowed_providers:
        raise ValueError("invalid capability route")
    eligible = (provider for provider in providers
                if provider.available and provider.provider_id in allowed_providers
                and provider.provider_id not in disabled
                and required in provider.capabilities and provider.complexity_ceiling >= complexity)
    return tuple(sorted(eligible, key=lambda p: (p.priority, p.cost_per_million_tokens,
                                                 p.provider_id, p.model_id)))


def confidence_gate(*, evidence: tuple[EvidenceItem, ...],
                    mandatory_claim_ids: frozenset[str], quality: float,
                    min_quality: float = 0.85) -> Literal["ACCEPT", "QUARANTINE"]:
    if not 0 <= quality <= 1 or not 0 <= min_quality <= 1:
        raise ValueError("quality must be within [0,1]")
    statuses: dict[str, set[str]] = {}
    for item in evidence:
        statuses.setdefault(item.claim_id, set()).add(item.status)
    if quality < min_quality or any(statuses.get(cid) != {"VERIFIED"} for cid in mandatory_claim_ids):
        return "QUARANTINE"
    return "ACCEPT"


def seal_record(*, sequence: int, previous_hash: str, payload: Any,
                signing_key: bytes) -> AuditRecord:
    if sequence < 1 or len(previous_hash) != 64 or not signing_key:
        raise ValueError("invalid chain inputs")
    digest = canonical_hash(payload)
    record_hash = canonical_hash({"seq": sequence, "prev": previous_hash, "digest": digest})
    signature = hmac.new(signing_key, record_hash.encode(), hashlib.sha256).hexdigest()
    return AuditRecord(sequence=sequence, previous_hash=previous_hash,
                       payload_digest=digest, record_hash=record_hash, signature=signature)


def verify_chain(records: tuple[AuditRecord, ...], payloads: tuple[Any, ...], signing_key: bytes) -> bool:
    if len(records) != len(payloads) or not signing_key:
        return False
    previous = "0" * 64
    for index, (record, payload) in enumerate(zip(records, payloads), start=1):
        try:
            expected = seal_record(sequence=index, previous_hash=previous,
                                   payload=payload, signing_key=signing_key)
        except ValueError:
            return False
        if record != expected or not hmac.compare_digest(record.signature, expected.signature):
            return False
        previous = record.record_hash
    return True
