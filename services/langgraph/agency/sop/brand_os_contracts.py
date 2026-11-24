"""API contracts for the Brand OS SOP adoption surface (``/brand-os``). Zod twin: ``packages/shared/src/schemas/brandOs.ts``.

Recorded fixture ``packages/shared/tests/fixtures/brand-os.json`` is regenerated with
``AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_brand_os_api.py``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AdoptionState = Literal["NOT_STAGED", "STAGED_NO_APPROVAL", "PENDING", "ADOPTED", "REJECTED", "STALE", "REVISION_CHANGED"]
ProcedureStatus = Literal["NEWLY_AUTHORED_DRAFT", "SOURCE_UNAVAILABLE"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SopListItem(_Contract):
    sop_id: str = Field(pattern=r"^F(0[1-9]|[1-5][0-9]|60)$")
    name: str
    department_id: str
    department_name: str
    batch: Literal["BATCH_1", "INDEX_ONLY"]
    procedure_status: ProcedureStatus
    origin: Optional[Literal["NEWLY_AUTHORED_SOP"]] = None
    draft_version: Optional[str] = None
    source_sha256: Optional[str] = None
    step_count: int = Field(ge=0)


class SopStepView(_Contract):
    step_ref: str
    sequence: int = Field(ge=1)
    line: int = Field(ge=1)
    text: str
    agm_disposition: str
    agm_task_ids: tuple[str, ...]


class SopDetail(_Contract):
    sop: SopListItem
    steps: tuple[SopStepView, ...]
    companion_scope: Literal["ADVISORY"] = "ADVISORY"
    original_authenticated: Literal[False] = False


class AdoptionStatus(_Contract):
    project_id: str
    sop_id: str
    name: str
    origin: Literal["NEWLY_AUTHORED_SOP"] = "NEWLY_AUTHORED_SOP"
    draft_version: str
    source_sha256: str
    state: AdoptionState
    decision_covers: str
    artifact_id: Optional[str] = None
    artifact_version: Optional[int] = None
    artifact_hash: Optional[str] = None
    approval_id: Optional[str] = None
    decision_route: Optional[str] = None
    reasons: tuple[str, ...] = ()
    grants_runtime_authority: Literal[False] = False
    external_effects: Literal["none"] = "none"


__all__ = ["AdoptionState", "AdoptionStatus", "SopDetail", "SopListItem", "SopStepView"]
