"""Brand OS SOP views and the adoption request/status flow behind ``/brand-os``.

The flow reuses native pieces only: ``stage_sop_for_adoption`` (Project OS artifact +
``open_artifact_approval``), the approvals table read back by subject, and
``verify_sop_adoption`` (``artifact_release_verdict`` + purpose + principal scope).

Retry and partial-failure behaviour, all converging without duplicates:

* the same ``Idempotency-Key`` replays the first response (route layer);
* a new request while the SOP is PENDING or ADOPTED returns the persisted status and opens nothing;
* if the artifact was stored but the approval was not opened (a crash between the two),
  status reads STAGED_NO_APPROVAL and a repeat request reuses the unchanged artifact
  (``store`` returns ``reused_unchanged``) and opens the one missing approval.

Nothing here decides an approval or grants runtime authority.
"""

from __future__ import annotations

from typing import Optional

from services.langgraph.agency.sop.brand_os_contracts import AdoptionStatus, SopDetail, SopListItem, SopStepView
from services.langgraph.agency.sop.brand_os_source import (
    IndexEntry,
    MAPPING_FILE,
    _load,
    load_index,
    procedure_steps,
    step_ref,
    verified_draft_bytes,
)
from services.langgraph.agency.sop.source_approval import (
    ADOPTION_SUBJECT_TYPE,
    stage_sop_for_adoption,
    verify_sop_adoption,
)
from services.langgraph.security.auth import Principal


def _entry(sop_id: str) -> IndexEntry:
    try:
        return load_index().entry(sop_id)
    except StopIteration as exc:
        raise LookupError(f"unknown Brand OS SOP {sop_id}") from exc


def _list_item(entry: IndexEntry) -> SopListItem:
    source = entry.procedure_source
    count = len(procedure_steps(verified_draft_bytes(entry).decode("utf-8"))) if source else 0
    return SopListItem(sop_id=entry.sop_id, name=entry.name, department_id=entry.department_id,
                       department_name=entry.department_name, batch=entry.batch, procedure_status=entry.procedure_status,
                       origin=source.origin if source else None, draft_version=source.version if source else None,
                       source_sha256=source.sha256 if source else None, step_count=count)


def list_sops() -> list[SopListItem]:
    return [_list_item(e) for e in load_index().entries]


def sop_detail(sop_id: str) -> SopDetail:
    entry = _entry(sop_id)
    mapped = {s["step_ref"]: s for sop in _load(MAPPING_FILE)["sops"] for s in sop["steps"]}
    steps = procedure_steps(verified_draft_bytes(entry).decode("utf-8")) if entry.procedure_source else ()
    views = []
    for s in steps:
        ref = step_ref(sop_id, s.sequence)
        views.append(SopStepView(step_ref=ref, sequence=s.sequence, line=s.line, text=s.text,
                                 agm_disposition=mapped[ref]["disposition"], agm_task_ids=tuple(mapped[ref]["task_ids"])))
    return SopDetail(sop=_list_item(entry), steps=tuple(views))


def _covers(entry: IndexEntry) -> str:
    source = entry.procedure_source
    return (f"Adoption of {entry.sop_id} {entry.name} for this project only: the exact draft bytes "
            f"sha256={source.sha256} ({source.version}, newly written, not a recovered original). "
            "The step companion and AGM mapping are advisory and not covered. Adoption grants no runtime, "
            "publication, spending or messaging permission.")


def _latest_adoption_approval(project_id: str, artifact_id: str) -> Optional[dict]:
    from services.langgraph.persistence.approvals import list_approvals_for_subject_refs

    rows = [a for a in list_approvals_for_subject_refs(project_id, [artifact_id])
            if a.get("subject_type") == ADOPTION_SUBJECT_TYPE]
    return rows[0] if rows else None  # newest first


def _state(principal: Principal, project_id: str, head: dict, approval: Optional[dict]) -> tuple[str, tuple[str, ...]]:
    if approval is None:
        return "STAGED_NO_APPROVAL", ("submit the adoption request again to open the missing approval",)
    if approval.get("status") == "pending":
        return "PENDING", ()
    if approval.get("decision") == "reject":
        return "REJECTED", ()
    evidence = verify_sop_adoption(principal, tenant_id=principal.tenant_id, project_id=project_id,
                                   artifact_id=head["artifact_id"], version=int(head["version"]),
                                   content_hash=head["content_hash"], approval_id=approval["approval_id"])
    return ("ADOPTED", ()) if evidence.verified else ("STALE", evidence.reasons)


def adoption_status(principal: Principal, project_id: str, sop_id: str) -> AdoptionStatus:
    """The persisted adoption state, read back from the artifact head and the approvals table."""
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import project_artifact_id

    entry = _entry(sop_id)
    if entry.procedure_source is None:
        raise LookupError(f"{sop_id} has no newly written draft to adopt")
    base = {"project_id": project_id, "sop_id": sop_id, "name": entry.name, "draft_version": entry.procedure_source.version,
            "source_sha256": entry.procedure_source.sha256, "decision_covers": _covers(entry)}
    head = get_artifact(project_artifact_id(project_id, f"foundry-brand-os-{sop_id.lower()}"))
    if head is None:
        return AdoptionStatus(**base, state="NOT_STAGED")
    found = {"artifact_id": head["artifact_id"], "artifact_version": int(head["version"]), "artifact_hash": head["content_hash"]}
    if head["content_hash"] != entry.procedure_source.sha256:
        return AdoptionStatus(**base, **found, state="REVISION_CHANGED",
                              reasons=("the stored artifact is not the currently pinned draft revision",))
    approval = _latest_adoption_approval(project_id, head["artifact_id"])
    state, reasons = _state(principal, project_id, head, approval)
    approval_id = approval["approval_id"] if approval else None
    return AdoptionStatus(**base, **found, state=state, reasons=reasons, approval_id=approval_id,
                          decision_route=f"/approvals/{approval_id}/decide" if approval_id else None)


def request_adoption(principal: Principal, project_id: str, sop_id: str, adapter) -> AdoptionStatus:
    """Stage the exact pinned draft and open its adoption approval, unless one is already pending or adopted."""
    current = adoption_status(principal, project_id, sop_id)
    if current.state in ("PENDING", "ADOPTED"):
        return current
    stage_sop_for_adoption(principal, project_id=project_id, sop_id=sop_id, adapter=adapter)
    return adoption_status(principal, project_id, sop_id)


__all__ = ["adoption_status", "list_sops", "request_adoption", "sop_detail"]
