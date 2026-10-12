"""AuthorizationBroker: server-derived identity, scope, dependencies and approvals.

Nothing here is new authority. Identity and scope come from the
``Principal`` and the Project OS tenancy registry (via the VNEXUS
``authorize``, which already does tenant → access → read-only role). Approvals
are rows in the existing ``approvals`` table, decided only through
``POST /approvals/{id}/decide``, which enforces the approver role and
separation of duties. The broker adds three things:

* the subject hash of every action approval is the exact binding hash;
* financial (R4) and governance (R6) approvals carry a role policy in the
  anchor run's server-written metadata, which the decide route enforces;
* governance approvals can never be self-approved, even where the local-dev
  self-approval override is set (I14).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.security.auth import Principal

from .risk import RiskAssessment

SUBJECT_EXECUTION = "ACTION_EXECUTION"
SUBJECT_SPEND = "ACTION_SPEND"
SUBJECT_GOVERNANCE = "ACTION_GOVERNANCE"
APPROVAL_POLICY_VERSION = "amc-action-approval/v1"
RUN_PIPELINE = "governed_action"
FINANCE_APPROVER_ROLES = ("owner", "admin")
GOVERNANCE_APPROVER_ROLES = ("owner", "admin")
FREEZE_ROLES = frozenset({"owner", "admin", "operator", "approver", "reviewer"})
LIFT_ROLES = frozenset({"owner", "admin"})
AUTONOMY_RAISE_ROLES = frozenset({"owner", "admin"})


class ActionForbidden(PermissionError):
    pass


class DependencyInvalid(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApprovalCheck(_Strict):
    satisfied: bool
    rejected: bool = False
    expired: bool = False
    stale: bool = False
    pending: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    approvals: tuple[dict, ...] = ()


def authorize_scope(principal: Principal, project_id: str, *, write: bool) -> None:
    from services.langgraph.agency.vnexus.service import authorize
    from services.langgraph.persistence.projects import ProjectNotFoundError

    try:
        authorize(principal, project_id, write=write)
    except ProjectNotFoundError as exc:
        raise LookupError(f"project {project_id} not found") from exc
    except PermissionError as exc:
        raise ActionForbidden(str(exc)) from exc


def visible(principal: Principal, row: Optional[dict]) -> dict:
    """Return the row if this principal may see it; otherwise the same 'not found'
    as an absent id, so action ids cannot be probed across tenants (I01)."""
    if row is None or row["tenant_id"] != principal.tenant_id or not principal.can_access_project(row["project_id"]):
        raise LookupError("action not found")
    return row


def resolve_dependencies(project_id: str, refs: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """Server-side lookup of each dependency's current head hash. The client names
    artifacts; it never supplies their hashes."""
    from services.langgraph.persistence.agency_kernel import get_artifact

    out = []
    for ref in sorted(set(refs)):
        head = get_artifact(ref)
        if head is None or head.get("project_id") != project_id:
            raise DependencyInvalid(f"DEPENDENCY_NOT_FOUND: {ref}")
        if not head.get("content_hash"):
            raise DependencyInvalid(f"DEPENDENCY_UNHASHED: {ref}")
        out.append((ref, f"v{head['version']}:{head['content_hash']}"))
    return tuple(out)


def current_dependencies(project_id: str, pinned: Iterable[Iterable[str]]) -> tuple[tuple[str, str], ...]:
    try:
        return resolve_dependencies(project_id, [ref for ref, _ in pinned])
    except DependencyInvalid:
        return tuple((ref, "MISSING") for ref, _ in pinned)


def required_subjects(risk: RiskAssessment, *, needs_execution_approval: bool) -> list[str]:
    subjects = []
    if needs_execution_approval or risk.requires_approval:
        subjects.append(SUBJECT_EXECUTION)
    if risk.requires_financial_approval:
        subjects.append(SUBJECT_SPEND)
    if risk.requires_privileged_review:
        subjects.append(SUBJECT_GOVERNANCE)
    return subjects


def approval_run_id(action_id: str) -> str:
    return "action-" + canonical_hash({"action": action_id})[:24]


def open_anchor_run(principal: Principal, *, action_id: str, tenant_id: str, project_id: str, needs_approval: bool,
                    binding_hash: str) -> str:
    """One run per action anchors its approvals and proof receipts."""
    from services.langgraph.persistence.runs import create_run_record, get_run_record

    run_id = approval_run_id(action_id)
    if get_run_record(run_id) is None:
        create_run_record(run_id, tenant_id, project_id, RUN_PIPELINE, "needs_approval" if needs_approval else "running", {
            "initiated_by": principal.user_id, "action_id": action_id, "binding_hash": binding_hash,
            # Server-written: the decide route reads this to restrict who may decide each subject.
            "approval_policy": {
                SUBJECT_SPEND: {"roles": list(FINANCE_APPROVER_ROLES), "no_self_approval": True},
                SUBJECT_GOVERNANCE: {"roles": list(GOVERNANCE_APPROVER_ROLES), "no_self_approval": True},
            },
        })
    return run_id


def open_approvals(principal: Principal, *, run_id: str, action_id: str, tenant_id: str, project_id: str, subjects: list[str],
                   binding_hash: str, title: str) -> dict[str, str]:
    from services.langgraph.persistence.approvals import create_approval_request

    reasons = {
        SUBJECT_EXECUTION: f"Approve this exact action: {title}",
        SUBJECT_SPEND: f"Approve the spend for: {title}",
        SUBJECT_GOVERNANCE: f"Privileged review of a governance change: {title}",
    }
    out = {}
    for subject in subjects:
        approval = create_approval_request(
            run_id, tenant_id, project_id, reasons[subject], None, subject_type=subject, subject_ref=action_id,
            subject_version_ref=binding_hash[:16], subject_hash=binding_hash, authority_ref="human-review",
            policy_version=APPROVAL_POLICY_VERSION)
        out[subject] = approval["approval_id"]
    return out


def _action_approvals(row: dict) -> dict[str, dict]:
    """Latest approval per subject for this action, read from its anchor run."""
    from services.langgraph.persistence.approvals import get_approvals_for_run

    if not row.get("run_id"):
        return {}
    latest: dict[str, dict] = {}
    for a in get_approvals_for_run(row["run_id"]):  # newest first
        if a.get("subject_ref") == row["action_id"] and a.get("subject_type") not in latest:
            latest[a["subject_type"]] = a
    return latest


def check_approvals(row: dict, *, now: datetime) -> ApprovalCheck:
    """Evaluate every approval the action needs against its *current* binding."""
    from services.langgraph.security.approval_authority import self_approval_allowed

    subjects = list((row.get("binding") or {}).get("approval_subjects") or [])
    if not subjects:
        return ApprovalCheck(satisfied=False, reasons=("NO_APPROVAL_REQUIRED_BY_BINDING",))
    found = _action_approvals(row)
    reasons: list[str] = []
    pending: list[str] = []
    rejected = expired = stale = False
    summaries = []
    for subject in subjects:
        a = found.get(subject)
        if a is None:
            reasons.append(f"{subject}:APPROVAL_MISSING")
            continue
        summaries.append({"subject": subject, "approval_id": a["approval_id"], "status": a.get("status"),
                          "decision": a.get("decision"), "reviewer": a.get("reviewer"), "decided_at": a.get("decided_at"),
                          "subject_hash": a.get("subject_hash")})
        if (a.get("tenant_id"), a.get("project_id")) != (row["tenant_id"], row["project_id"]):
            reasons.append(f"{subject}:APPROVAL_SCOPE_MISMATCH")
        if a.get("subject_hash") != row["binding_hash"]:
            stale = True
            reasons.append(f"{subject}:SUBJECT_HASH_MISMATCH")
        status, decision = a.get("status"), a.get("decision")
        if status == "stale":
            stale = True
            reasons.append(f"{subject}:APPROVAL_STALE")
        elif status != "resolved":
            pending.append(subject)
        elif decision != "approve":
            rejected = True
            reasons.append(f"{subject}:APPROVAL_REJECTED")
        else:
            if _after(a.get("decided_at"), row["expires_at"]):
                expired = True
                reasons.append(f"{subject}:APPROVED_AFTER_EXPIRY")
            if a.get("reviewer") == row["actor_ref"] and (subject == SUBJECT_GOVERNANCE or not self_approval_allowed()):
                reasons.append(f"{subject}:SELF_APPROVAL")
    deciders = [s["reviewer"] for s in summaries if s.get("status") == "resolved" and s.get("decision") == "approve"]
    if len(deciders) != len(set(deciders)):
        # Each required approval is a separate human check: one person cannot
        # supply both the content and the financial (or governance) approval.
        reasons.append("SAME_REVIEWER_FOR_MULTIPLE_APPROVALS")
    if _past(now, row["expires_at"]):
        expired = True
        reasons.append("ACTION_EXPIRED")
    return ApprovalCheck(satisfied=not reasons and not pending, rejected=rejected, expired=expired, stale=stale,
                         pending=tuple(pending), reasons=tuple(reasons), approvals=tuple(summaries))


def _after(decided_at: Optional[str], expires_iso: str) -> bool:
    from datetime import timezone

    if not decided_at:
        return False
    moment = datetime.fromisoformat(str(decided_at).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return _past(moment, expires_iso)


def _past(now: datetime, expires_iso: str) -> bool:
    from services.langgraph.persistence.actions import iso

    return iso(now) > expires_iso


def stale_open_approvals(row: dict, reason: str) -> list[str]:
    """Mark every still-pending approval of this action stale (approval invalidation)."""
    from services.langgraph.persistence.approvals import mark_approval_stale

    staled = []
    for a in _action_approvals(row).values():
        if a.get("status") == "pending":
            mark_approval_stale(a["approval_id"], reason)
            staled.append(a["approval_id"])
    return sorted(staled)


def role(principal: Principal) -> str:
    return principal.role.strip().lower()


def require_role(principal: Principal, allowed: frozenset[str], what: str) -> None:
    if role(principal) not in allowed:
        raise ActionForbidden(f"{what} requires one of {sorted(allowed)}")


def summary(principal: Principal) -> dict[str, Any]:
    return {"user_id": principal.user_id, "tenant_id": principal.tenant_id, "role": principal.role}


__all__ = [
    "APPROVAL_POLICY_VERSION", "AUTONOMY_RAISE_ROLES", "ActionForbidden", "ApprovalCheck", "DependencyInvalid",
    "FINANCE_APPROVER_ROLES", "FREEZE_ROLES", "GOVERNANCE_APPROVER_ROLES", "LIFT_ROLES", "RUN_PIPELINE", "SUBJECT_EXECUTION",
    "SUBJECT_GOVERNANCE", "SUBJECT_SPEND", "approval_run_id", "authorize_scope", "check_approvals", "current_dependencies",
    "open_anchor_run", "open_approvals", "require_role", "required_subjects", "resolve_dependencies", "role",
    "stale_open_approvals", "summary", "visible",
]
