"""Project-scoped planning facts supplied by trusted server code, never prose.

Callers must resolve and verify the cited records before constructing this
snapshot. This contract carries that evidence; it cannot create upstream
artifacts, verify a source, accept a decision or authorize a release.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from services.langgraph.agency.compiled.backchain import EvidenceItem
from services.langgraph.agency.compiled.decisions import DecisionNode, DecisionStatus
from services.langgraph.agency.compiled.evidence import VolatileConstraint
from services.langgraph.agency.execution.canonical import canonical_hash


class PlanningInputs(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=100)
    evidence: tuple[EvidenceItem, ...] = Field(default=(), max_length=100)
    decisions: tuple[DecisionNode, ...] = Field(default=(), max_length=100)
    volatile_constraints: tuple[VolatileConstraint, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def _provenance(self) -> PlanningInputs:
        if any(not ref.strip() for ref in self.source_refs):
            raise ValueError("planning source references must be nonempty")
        refs = [item.ref for item in self.evidence]
        if any(not ref.strip() for ref in refs) or len(refs) != len(set(refs)):
            raise ValueError("evidence references must be nonempty and unique")
        keys = [item.key for item in self.volatile_constraints]
        if len(keys) != len(set(keys)):
            raise ValueError("volatile constraint keys must be unique")
        for decision in self.decisions:
            if decision.status is DecisionStatus.ACCEPTED and (
                not decision.owner.strip() or not decision.approved_by or not decision.approved_by.strip()
                or decision.approved_by == decision.owner
                or decision.selected_option not in decision.alternatives
                or (decision.required_approver and decision.approved_by != decision.required_approver)
            ):
                raise ValueError("accepted planning decisions need a valid selection and independent approver")
        return self

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


__all__ = ["PlanningInputs"]
