"""Vocabulary and API contracts for project-scoped agency task instances.

Zod twins: packages/shared/src/schemas/agencyFramework.ts. Enum parity and the
recorded fixture are checked by services/langgraph/tests/test_agency_framework_contracts.py.

Status is deliberately split, never inferred from one another:
``performed`` (a task reached IN_REVIEW with refs), ``verified`` (a different
person had the server re-check every ref), ``approved`` (an approval bound to
the exact proof hash was decided through /approvals/{id}/decide and settled),
``release-eligible`` and ``externally executed`` (never set by this module).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "amc-agency-framework/v1"
PIPELINE = "agency_framework"
POLICY_VERSION = "amc-agency-framework-policy/v1"


class TaskState(str, Enum):
    BACKLOG = "BACKLOG"
    READY = "READY"
    ACTIVE = "ACTIVE"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Applicability(str, Enum):
    UNASSESSED = "UNASSESSED"
    REQUIRED = "REQUIRED"
    CONDITIONAL = "CONDITIONAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class GateStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    PASSED = "PASSED"
    STALE = "STALE"


class EvidenceOrigin(str, Enum):
    CUSTOMER_SOURCED = "CUSTOMER_SOURCED"
    PUBLIC_SOURCE = "PUBLIC_SOURCE"
    INTERNAL_RECORD = "INTERNAL_RECORD"
    INFERENCE = "INFERENCE"
    SYNTHETIC = "SYNTHETIC"


class Archetype(str, Enum):
    B2C_PHYSICAL_PRODUCT = "B2C_PHYSICAL_PRODUCT"
    B2B_PROFESSIONAL_SERVICES = "B2B_PROFESSIONAL_SERVICES"
    SAAS_SUBSCRIPTION = "SAAS_SUBSCRIPTION"
    OTHER = "OTHER"


# Readiness labels for reporting; this module can reach at most APPROVAL_READY
# for a plan and APPROVED for a task. RELEASED and PRODUCTION_ACTIVE are owned by
# delivery and production activation and are never computed here.
READINESS_LEVELS = ("SPECIFIED", "IMPLEMENTED", "TESTED", "VERIFIED", "APPROVAL_READY", "RELEASE_ELIGIBLE",
                    "RELEASED", "PRODUCTION_ACTIVE")

# Transitions a person may request directly. VERIFIED, APPROVED and INVALIDATED
# are reachable only through verify / settle / revalidation on the server.
MANUAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    TaskState.BACKLOG.value: (TaskState.READY.value, TaskState.BLOCKED.value),
    TaskState.READY.value: (TaskState.ACTIVE.value, TaskState.BACKLOG.value, TaskState.BLOCKED.value),
    TaskState.ACTIVE.value: (TaskState.IN_REVIEW.value, TaskState.READY.value, TaskState.BLOCKED.value),
    TaskState.IN_REVIEW.value: (TaskState.ACTIVE.value, TaskState.BLOCKED.value),
    TaskState.VERIFIED.value: (TaskState.ACTIVE.value, TaskState.BLOCKED.value),
    TaskState.INVALIDATED.value: (TaskState.ACTIVE.value,),
    TaskState.BLOCKED.value: (),  # leave BLOCKED with "unblock", which restores the prior state
    TaskState.APPROVED.value: (),
    TaskState.NOT_APPLICABLE.value: (),
}

# What a task must carry, by output class, before it can enter review.
REQUIRED_REF_KINDS: dict[str, tuple[str, ...]] = {
    "evidence": ("evidence",),
    "decision": ("decision",),
    "artifact": ("artifact",),
    "approval_or_plan": ("artifact",),
    "measurement": ("evidence",),
}

_EVIDENCE_REF = re.compile(r"^(knowledge|evidence):[A-Za-z0-9._:-]{1,160}$")
_DECISION_REF = re.compile(r"^(decision|genome):[A-Za-z0-9._:-]{1,160}$")
_ARTIFACT_REF = re.compile(r"^artifact:[A-Za-z0-9._-]{1,200}@v[1-9][0-9]{0,6}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstantiatePlan(_Strict):
    project_id: str = Field(min_length=1, max_length=120)
    archetype: Archetype = Archetype.OTHER
    engagement_scope: str = Field(default="", max_length=2000)


class ApplicabilityItem(_Strict):
    task_id: str = Field(pattern=r"^AGM-\d{2}-\d{3}$")
    applicability: Applicability
    reason: str = Field(min_length=3, max_length=500)


class ApplicabilityRequest(_Strict):
    decisions: list[ApplicabilityItem] = Field(min_length=1, max_length=295)


class TransitionRequest(_Strict):
    target: TaskState
    expected_version: int = Field(ge=0)
    reason: str = Field(default="", max_length=500)


class RefsRequest(_Strict):
    expected_version: int = Field(ge=0)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    artifact_refs: list[str] = Field(default_factory=list, max_length=50)
    decision_refs: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("evidence_refs")
    @classmethod
    def _evidence(cls, v: list[str]) -> list[str]:
        return _check(v, _EVIDENCE_REF, "evidence ref (knowledge:<id> | evidence:<id>)")

    @field_validator("artifact_refs")
    @classmethod
    def _artifacts(cls, v: list[str]) -> list[str]:
        return _check(v, _ARTIFACT_REF, "artifact ref (artifact:<artifact_id>@v<version>)")

    @field_validator("decision_refs")
    @classmethod
    def _decisions(cls, v: list[str]) -> list[str]:
        return _check(v, _DECISION_REF, "decision ref (decision:<id> | genome:<approved VNEXUS version id>)")


class VersionedRequest(_Strict):
    expected_version: int = Field(ge=0)


class DecisionRecordRequest(_Strict):
    question: str = Field(min_length=3, max_length=500)
    alternatives: list[str] = Field(min_length=2, max_length=10)
    selected_option: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("evidence_refs")
    @classmethod
    def _evidence(cls, v: list[str]) -> list[str]:
        return _check(v, _EVIDENCE_REF, "evidence ref (knowledge:<id> | evidence:<id>)")


class MeasurementRequest(_Strict):
    metric_input: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: float
    unit: str = Field(min_length=1, max_length=40)
    window: str = Field(min_length=1, max_length=80)
    source_ref: str = Field(min_length=3, max_length=300)
    claim: str = Field(default="", max_length=500)


class GateApprovalRequest(_Strict):
    stage_gate: str = Field(pattern=r"^0[1-5]_[A-Z]+$")


def _check(values: list[str], pattern: re.Pattern[str], label: str) -> list[str]:
    for value in values:
        if not pattern.match(value):
            raise ValueError(f"invalid {label}: {value!r}")
    if len(set(values)) != len(values):
        raise ValueError("refs must be unique")
    return values


def parse_artifact_ref(ref: str) -> tuple[str, int]:
    body = ref.removeprefix("artifact:")
    artifact_id, _, version = body.rpartition("@v")
    return artifact_id, int(version)


def ref_kind(ref: str) -> str:
    return ref.split(":", 1)[0]


class FrameworkError(Exception):
    """A deterministic, client-visible refusal."""

    def __init__(self, code: str, message: str, status: int = 409, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


__all__ = [
    "MANUAL_TRANSITIONS",
    "PIPELINE",
    "POLICY_VERSION",
    "READINESS_LEVELS",
    "REQUIRED_REF_KINDS",
    "SCHEMA_VERSION",
    "Applicability",
    "ApplicabilityItem",
    "ApplicabilityRequest",
    "Archetype",
    "EvidenceOrigin",
    "FrameworkError",
    "GateApprovalRequest",
    "GateStatus",
    "InstantiatePlan",
    "RefsRequest",
    "TaskState",
    "TransitionRequest",
    "VersionedRequest",
    "parse_artifact_ref",
    "ref_kind",
]
