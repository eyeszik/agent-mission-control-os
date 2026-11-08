"""Internal, planning-only adaptive contracts. No persistence or execution authority.

Grouping is deliberately independent of N1 types and N3 permissions. These
models are not API contracts; exposing them would require shared-schema parity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .planner import CompiledAgencyPlan

Key = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,119}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Refs = Annotated[tuple[Key, ...], Field(min_length=1, max_length=100)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RequirementRecord(_Strict):
    id: Key
    purpose: Text
    source_refs: Annotated[tuple[Text, ...], Field(min_length=1, max_length=50)]
    origin: Literal["EXPLICIT", "INFERRED"] = "EXPLICIT"
    rationale: Text | None = None
    confirmation_required: bool = False
    category_hint: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = "Requested work"

    @model_validator(mode="after")
    def inference_needs_reason(self) -> RequirementRecord:
        if self.origin == "INFERRED" and not self.rationale:
            raise ValueError("inferred requirements need a rationale")
        if not self.category_hint:
            raise ValueError("category_hint must not be blank")
        return self


class CategoryRecord(_Strict):
    id: Key
    label: Annotated[Text, Field(max_length=120)]
    requirement_ids: Refs
    parent_id: Key | None = None


class DeliverableInstance(_Strict):
    id: Key
    purpose: Text
    requirement_ids: Refs
    output_contract: Text
    acceptance_criteria: Annotated[tuple[Text, ...], Field(min_length=1, max_length=100)]
    category_ids: Annotated[tuple[Key, ...], Field(max_length=100)] = ()
    constraints: Annotated[tuple[Text, ...], Field(max_length=100)] = ()
    domains: Annotated[tuple[Text, ...], Field(max_length=50)] = ()
    # Names are requests, never proof of a registered, ready or permitted tool.
    capability_requirements: Annotated[tuple[Text, ...], Field(max_length=50)] = ()
    external_action: Text | None = None


class DependencyBinding(_Strict):
    upstream: Key
    downstream: Key
    mandatory: bool = True
    selected: bool = True

    @model_validator(mode="after")
    def mandatory_is_selected(self) -> DependencyBinding:
        if self.mandatory and not self.selected:
            raise ValueError("mandatory dependencies cannot be deselected")
        return self


class AdaptivePlanningRequest(_Strict):
    schema_version: Literal["amc-adaptive-planning/v1"] = "amc-adaptive-planning/v1"
    project_id: Key
    plan_id: Key
    revision: int = Field(default=1, ge=1)
    as_of: Annotated[str, StringConstraints(min_length=10, max_length=40)]
    requirements: Annotated[tuple[RequirementRecord, ...], Field(min_length=1, max_length=100)]
    deliverables: Annotated[tuple[DeliverableInstance, ...], Field(min_length=1, max_length=50)]
    categories: Annotated[tuple[CategoryRecord, ...], Field(max_length=100)] = ()
    dependencies: Annotated[tuple[DependencyBinding, ...], Field(max_length=500)] = ()
    ambiguities: Annotated[tuple[Text, ...], Field(max_length=100)] = ()

    @field_validator("as_of")
    @classmethod
    def timestamp_is_explicit(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class StructuralChange(_Strict):
    kind: Literal["ADDED", "REMOVED", "CHANGED"]
    entity: Literal["requirement", "category", "deliverable", "dependency"]
    id: Text
    previous_hash: str | None = None
    current_hash: str | None = None


class CostProjection(_Strict):
    classification: Literal["NOT PRICED"] = "NOT PRICED"
    total: None = None
    external_planner_fee: Literal["$0 EXT"] = "$0 EXT"
    basis: str = "Local planning makes no provider call; production, labor and compute costs are not measured."


class AdaptivePlanningResult(_Strict):
    schema_version: Literal["amc-adaptive-plan/v1"] = "amc-adaptive-plan/v1"
    project_id: Key
    plan_id: Key
    revision: int
    previous_revision_hash: str | None
    content_hash: str
    # Always a preview, even if the canonical planner reports schedulable cells.
    status: Literal["PREVIEW", "BLOCKED"]
    categories: tuple[CategoryRecord, ...]
    requirements: tuple[RequirementRecord, ...]
    deliverables: tuple[DeliverableInstance, ...]
    dependencies: tuple[DependencyBinding, ...]
    changes: tuple[StructuralChange, ...]
    lowering_blockers: tuple[str, ...]
    compiled_projection: CompiledAgencyPlan | None
    cost: CostProjection = CostProjection()
    execution_authorized: Literal[False] = False
    runtime_readiness: Literal["NOT_TESTED"] = "NOT_TESTED"
