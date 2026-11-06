"""Instruction data, never an alternative source of runtime authority."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.model_profiles import ModelProfile

TaskType = Literal["research", "architecture", "implementation", "validation", "delivery"]
Hash = str


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class InstructionSelection(Strict):
    task_type: TaskType = "implementation"
    max_sections: int = Field(default=16, ge=9, le=16)
    max_bytes: int = Field(default=32768, ge=256, le=32768)
    model_profile: ModelProfile | None = None


class InstructionSection(Strict):
    section_id: str
    text: str
    authority: Literal["RUNTIME_CONSTRAINT", "TASK_DATA", "ADVISORY"]
    requirement_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    mandatory: bool


class CapabilityComparison(Strict):
    namespace: Literal["N3", "ROLEOS"]
    required: tuple[str, ...]
    registered: tuple[str, ...]


class InstructionPackage(Strict):
    schema_version: Literal["amc.instruction-package/v1"] = "amc.instruction-package/v1"
    compiler_version: Literal["amc.instruction-compiler/v1"] = "amc.instruction-compiler/v1"
    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    work_order_id: str = Field(min_length=1)
    contract_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dependency_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    task_type: TaskType
    role_id: str
    specialist_role_id: str
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    guidance_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    adapter_id: str
    adapter_version: Literal["1"] = "1"
    model_profile_ref: str | None
    sections: tuple[InstructionSection, ...] = Field(min_length=9, max_length=16)
    comparisons: tuple[CapabilityComparison, ...]
    provenance: tuple[str, ...]
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class RejectedSection(Strict):
    section_id: str
    reason: str


class CompilationReport(Strict):
    package: InstructionPackage | None
    blockers: tuple[str, ...]
    rejected: tuple[RejectedSection, ...]
    bytes_used: int = Field(ge=0)
    sections_used: int = Field(ge=0)


class InstructionDiff(Strict):
    added: tuple[str, ...]
    removed: tuple[str, ...]
    modified: tuple[str, ...]
    affected_requirements: tuple[str, ...]
    affected_capabilities: tuple[str, ...]
    security_critical: tuple[str, ...]
    expected_evaluation: tuple[str, ...]
    approval: Literal[False] = False


class EvidenceRecord(Strict):
    id: str
    claim: str
    source: str
    status: Literal["VERIFIED", "REVIEWED", "UNVERIFIED"]
    limitations: str


class ValidationReport(Strict):
    result: Literal["PASS", "PARTIAL", "FAIL", "NOT_APPLICABLE"]
    checks: tuple[str, ...] = ()
    coverage: float | None = Field(default=None, ge=0, le=1)
    regressions: int | None = Field(default=None, ge=0)
    blockers: tuple[str, ...] = ()


class ExecutionReport(Strict):
    performed: tuple[str, ...] = ()
    proposed: tuple[str, ...] = ()
    pending_approval: tuple[str, ...] = ()
    checkpoint: str | None = None
    remaining_budget: int | None = Field(default=None, ge=0)


class InstructionDelivery(Strict):
    status: Literal["COMPLETE", "PARTIAL", "BLOCKED", "WAITING_APPROVAL"]
    operation: Literal["EXECUTE", "PROMPT", "AUDIT", "PATCH"]
    artifact: str
    changes: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    validation: ValidationReport
    execution: ExecutionReport
    human_review: str | None = None
    next_action: str | None = None
