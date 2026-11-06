"""Approval binding and the release gate, shared by every producer of artifacts.

Both are thin over existing primitives: the ``approvals`` table, a run record
with ``needs_approval`` and ``initiated_by`` (so ``/approvals/{id}/decide``
enforces the approver role and separation of duties), and the Project OS
artifact head. Used by the intake mission runner and the visual engine.
"""

from __future__ import annotations

from typing import Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.project_os.vocabulary import ActivityType
from services.langgraph.security.auth import Principal

from .contracts import ReleaseVerdict


def approval_run_id(mission_id: str) -> str:
    return "mission-" + canonical_hash({"mission": mission_id})[:24]


def open_artifact_approval(
    principal: Principal,
    *,
    tenant_id: str,
    project_id: str,
    mission_id: str,
    contract_hash: str,
    artifact_id: str,
    version: int,
    content_hash: str,
    run_pipeline: str,
    policy_version: str,
    subject_type: str,
    reason: str,
    metadata: Optional[dict] = None,
) -> dict:
    """Open (or reuse) a pending approval bound to the exact content hash.

    Pending approvals for the same artifact with a different hash are marked
    stale, so an approval can never carry over to changed content.
    """
    from services.langgraph.persistence.approvals import (
        create_approval_request,
        get_approvals_for_run,
        list_approvals_for_subject_refs,
        mark_approval_stale,
    )
    from services.langgraph.persistence.projects import append_project_event
    from services.langgraph.persistence.runs import create_run_record, get_run_record

    for existing in list_approvals_for_subject_refs(project_id, [artifact_id]):
        if existing.get("status") == "pending" and existing.get("subject_hash") != content_hash:
            mark_approval_stale(existing["approval_id"], "superseded: artifact content changed")
    run_id = approval_run_id(mission_id)
    if get_run_record(run_id) is None:
        create_run_record(run_id, tenant_id, project_id, run_pipeline, "needs_approval", {
            "initiated_by": principal.user_id, "mission_id": mission_id, "contract_hash": contract_hash,
            "artifact_id": artifact_id, "artifact_version": version, "artifact_hash": content_hash, **(metadata or {}),
        })
    for existing in get_approvals_for_run(run_id):
        if existing.get("status") == "pending" and existing.get("subject_hash") == content_hash:
            return existing
    approval = create_approval_request(
        run_id, tenant_id, project_id, reason, None, subject_type=subject_type, subject_ref=artifact_id,
        subject_version_ref=str(version), subject_hash=content_hash, authority_ref="human-review",
        policy_version=policy_version,
    )
    append_project_event(tenant_id=tenant_id, project_id=project_id, event_type=ActivityType.APPROVAL_REQUIRED,
                         actor=principal.user_id, subject_ref=f"{artifact_id}:v{version}",
                         payload={"mission_id": mission_id, "approval_id": approval["approval_id"], "subject_hash": content_hash})
    return approval


def artifact_release_verdict(
    *,
    simulated: bool,
    verification_passed: bool,
    artifact_id: Optional[str],
    verified_version: Optional[int],
    verified_hash: Optional[str],
    approval_id: Optional[str],
    tenant_id: Optional[str],
    project_id: Optional[str],
) -> ReleaseVerdict:
    """Fail closed unless a human approved this exact, still-current, verified artifact.

    It never performs a release or any external effect.
    """
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.approvals import get_approval
    from services.langgraph.persistence.runs import get_run_record
    from services.langgraph.security.approval_authority import run_initiator, self_approval_allowed

    reasons: list[str] = []
    if simulated:
        reasons.append("SIMULATION_NOT_RELEASABLE")
    if not verification_passed:
        reasons.append("VERIFICATION_NOT_PASSED")
    head = get_artifact(artifact_id) if artifact_id else None
    head_hash = head.get("content_hash") if head else None
    head_version = int(head["version"]) if head else None
    if artifact_id is not None and head is None:
        reasons.append("ARTIFACT_MISSING")
    elif head is not None and (head_version != verified_version or head_hash != verified_hash):
        reasons.append("VERIFICATION_STALE: the artifact changed after it was verified")
    if head is not None and project_id is not None and head.get("project_id") != project_id:
        reasons.append("CROSS_PROJECT_ARTIFACT")
    approval = get_approval(approval_id) if approval_id else None
    if approval is None:
        reasons.append("NO_APPROVAL")
    else:
        if tenant_id and (approval.get("tenant_id"), approval.get("project_id")) != (tenant_id, project_id):
            reasons.append("APPROVAL_SCOPE_MISMATCH")
        status, decision = approval.get("status"), approval.get("decision")
        if status == "stale":
            reasons.append("APPROVAL_STALE")
        elif status != "resolved":
            reasons.append("APPROVAL_PENDING")
        elif decision != "approve":
            reasons.append("APPROVAL_REJECTED")
        if approval.get("subject_hash") != head_hash:
            reasons.append("SUBJECT_HASH_MISMATCH")
        run = get_run_record(approval["run_id"]) if approval.get("run_id") else None
        initiator = run_initiator(run) if run else None
        if status == "resolved" and decision == "approve" and not self_approval_allowed():
            if initiator is None:
                reasons.append("INITIATOR_UNKNOWN")
            elif approval.get("reviewer") == initiator:
                reasons.append("SEPARATION_OF_DUTIES")
    return ReleaseVerdict(allowed=not reasons, reasons=tuple(reasons), artifact_id=artifact_id,
                          artifact_version=head_version, artifact_hash=head_hash,
                          approval_id=(approval or {}).get("approval_id"))


__all__ = ["approval_run_id", "artifact_release_verdict", "open_artifact_approval"]
