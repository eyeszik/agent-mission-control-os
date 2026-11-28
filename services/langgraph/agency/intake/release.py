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


# Upper bound on approval runs per mission; reaching it is refused rather than reusing a closed run.
MAX_APPROVAL_RUNS_PER_MISSION = 1000


def _run_reusable_by(run: dict, principal: Principal, tenant_id: str, project_id: str) -> bool:
    """A run carries one requester and one open decision: reuse it only for that requester, in the same tenant
    and project, while it is open."""
    from services.langgraph.security.approval_authority import run_initiator

    same_scope = run.get("tenant_id") == tenant_id and run.get("project_id") == project_id
    return same_scope and run.get("status") == "needs_approval" and run_initiator(run) == principal.user_id


def _approval_run_for(principal: Principal, mission_id: str, tenant_id: str, project_id: str) -> str:
    """The mission's first run, or the first later slot that is free or still this requester's open run.

    A rejected run cannot take another decision, and ``initiated_by`` is the separation-of-duties anchor, so a
    request after a rejection, or by a different requester, gets a run of its own. The slot is deterministic,
    so concurrent identical requests converge on one run.
    """
    from services.langgraph.core.errors import AMCError
    from services.langgraph.persistence.runs import get_run_record

    for generation in range(MAX_APPROVAL_RUNS_PER_MISSION):
        run_id = approval_run_id(mission_id if generation == 0 else f"{mission_id}#{generation}")
        run = get_run_record(run_id)
        if run is None or _run_reusable_by(run, principal, tenant_id, project_id):
            return run_id
    raise AMCError("This mission has no approval run left for another request", code="APPROVAL_CONFLICT", status=409)


def _same_mission(approval: dict, mission_id: str) -> bool:
    from services.langgraph.persistence.runs import get_run_record

    run = get_run_record(approval["run_id"]) or {}
    same_scope = run.get("tenant_id") == approval.get("tenant_id") and run.get("project_id") == approval.get("project_id")
    return same_scope and (run.get("metadata") or {}).get("mission_id") == mission_id


def _is_unique_violation(exc: BaseException) -> bool:
    """A unique/primary-key violation from either driver (sqlite3.IntegrityError, psycopg UniqueViolation)."""
    sqlstate = getattr(exc, "sqlstate", None) or getattr(getattr(exc, "diag", None), "sqlstate", None)
    return sqlstate == "23505" or (type(exc).__name__ == "IntegrityError" and "UNIQUE" in str(exc).upper())


def _matching_pending(project_id: str, artifact_id: str, expected: tuple) -> Optional[dict]:
    """The pending approval with exactly this binding, wherever it was opened from."""
    from services.langgraph.persistence.approvals import list_approvals_for_subject_refs

    for existing in list_approvals_for_subject_refs(project_id, [artifact_id]):
        binding = (existing.get("tenant_id"), existing.get("project_id"), existing.get("subject_ref"),
                   existing.get("subject_version_ref"), existing.get("subject_hash"),
                   existing.get("subject_type"), existing.get("policy_version"))
        if existing.get("status") == "pending" and binding == expected:
            return existing
    return None


def _ensure_approval_run(run_id: str, tenant_id: str, project_id: str, run_pipeline: str, metadata: dict) -> None:
    """Create the approval run once. A concurrent creator winning the insert is the same run, not an error."""
    from services.langgraph.persistence.runs import create_run_record, get_run_record

    if get_run_record(run_id) is not None:
        return
    try:
        create_run_record(run_id, tenant_id, project_id, run_pipeline, "needs_approval", metadata)
    except Exception as exc:  # noqa: BLE001 - only a lost insert race is tolerated; anything else re-raises
        if not _is_unique_violation(exc) or get_run_record(run_id) is None:
            raise


def _stale_superseded(project_id: str, artifact_id: str, version: int, content_hash: str) -> None:
    from services.langgraph.persistence.approvals import list_approvals_for_subject_refs, mark_approval_stale

    for existing in list_approvals_for_subject_refs(project_id, [artifact_id]):
        if existing.get("status") == "pending" and (existing.get("subject_hash") != content_hash
                or existing.get("subject_version_ref") != str(version)):
            mark_approval_stale(existing["approval_id"], "superseded: artifact version or content changed")


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
    stale, so an approval can never carry over to changed content. Where the
    database enforces one pending approval per subject (the Brand OS purposes),
    a request that loses a concurrent insert re-reads and returns the winner's
    approval when it binds the same content, and refuses (409) when it does not.
    """
    from services.langgraph.core.errors import AMCError
    from services.langgraph.persistence.approvals import create_approval_request
    from services.langgraph.persistence.projects import append_project_event

    _stale_superseded(project_id, artifact_id, version, content_hash)
    expected = (tenant_id, project_id, artifact_id, str(version), content_hash, subject_type, policy_version)
    existing = _matching_pending(project_id, artifact_id, expected)
    if existing is not None and _same_mission(existing, mission_id):
        return existing
    run_id = _approval_run_for(principal, mission_id, tenant_id, project_id)
    _ensure_approval_run(run_id, tenant_id, project_id, run_pipeline, {
        "initiated_by": principal.user_id, "mission_id": mission_id, "contract_hash": contract_hash,
        "artifact_id": artifact_id, "artifact_version": version, "artifact_hash": content_hash, **(metadata or {}),
    })
    try:
        approval = create_approval_request(
            run_id, tenant_id, project_id, reason, None, subject_type=subject_type, subject_ref=artifact_id,
            subject_version_ref=str(version), subject_hash=content_hash, authority_ref="human-review",
            policy_version=policy_version,
        )
    except Exception as exc:  # noqa: BLE001 - a lost race on the pending-uniqueness index is resolved by re-reading
        if not _is_unique_violation(exc):
            raise
        winner = _matching_pending(project_id, artifact_id, expected)
        if winner is None:
            raise AMCError("Another pending approval already exists for this subject with different content",
                           code="APPROVAL_CONFLICT", status=409) from exc
        return winner
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
    if not artifact_id or verified_version is None or not verified_hash or not tenant_id or not project_id:
        reasons.append("BINDING_INCOMPLETE")
    head = get_artifact(artifact_id) if artifact_id else None
    head_hash = head.get("content_hash") if head else None
    head_version = int(head["version"]) if head else None
    if artifact_id is not None and head is None:
        reasons.append("ARTIFACT_MISSING")
    elif head is not None and (head_version != verified_version or head_hash != verified_hash):
        reasons.append("VERIFICATION_STALE: the artifact changed after it was verified")
    if head is not None and project_id is not None and head.get("project_id") != project_id:
        reasons.append("CROSS_PROJECT_ARTIFACT")
    if head is not None and tenant_id is not None and head.get("tenant_id") != tenant_id:
        reasons.append("CROSS_TENANT_ARTIFACT")
    if head is not None and head.get("status") in {"invalidated", "review_required"}:
        reasons.append("ARTIFACT_INVALIDATED")
    if head is not None and head.get("subtype") == "ucpo.release_proof":
        from services.langgraph.agency.ucpo.brand_web import proof_freshness
        reasons.extend(proof_freshness(head, approval_id=approval_id))
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
        if approval.get("subject_ref") != artifact_id:
            reasons.append("SUBJECT_REF_MISMATCH")
        if head_version is None or approval.get("subject_version_ref") != str(head_version):
            reasons.append("SUBJECT_VERSION_MISMATCH")
        if head is not None and head.get("subtype") == "ucpo.release_proof":
            from services.langgraph.agency.ucpo.service import APPROVAL_POLICY
            if (approval.get("subject_type"), approval.get("policy_version")) != ("WEBSITE_RELEASE_PROOF", APPROVAL_POLICY):
                reasons.append("APPROVAL_PURPOSE_MISMATCH")
        run = get_run_record(approval["run_id"]) if approval.get("run_id") else None
        initiator = run_initiator(run) if run else None
        if status == "resolved" and decision == "approve":
            if not approval.get("reviewer"):
                reasons.append("REVIEWER_UNKNOWN")
            if not self_approval_allowed():
                if initiator is None:
                    reasons.append("INITIATOR_UNKNOWN")
                elif approval.get("reviewer") == initiator:
                    reasons.append("SEPARATION_OF_DUTIES")
    return ReleaseVerdict(allowed=not reasons, reasons=tuple(reasons), artifact_id=artifact_id,
                          artifact_version=head_version, artifact_hash=head_hash,
                          approval_id=(approval or {}).get("approval_id"))


__all__ = ["approval_run_id", "artifact_release_verdict", "open_artifact_approval"]
