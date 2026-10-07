"""Who may decide a human-in-the-loop approval.

Two independent checks, both server-side:

1. Role: only principals whose membership role is an approver role may approve
   or reject. ``AMC_APPROVER_ROLES`` (comma-separated) overrides the default set.
2. Separation of duties: the principal who initiated a run may not approve it.
   A run whose initiator was never recorded cannot prove separation, so it is
   refused as well (fail-closed by absence).

``AMC_ALLOW_SELF_APPROVAL`` exists only for single-user local development and
tests. It relaxes check 2 outside production; production configuration rejects
it (see ``app.config``).
"""

from __future__ import annotations

import os

from fastapi import HTTPException

from services.langgraph.core.constants import AMC_APPROVER_ROLES, ENV_LOCAL
from services.langgraph.security.auth import Principal

DEFAULT_APPROVER_ROLES = frozenset(AMC_APPROVER_ROLES)
_TRUTHY = {"1", "true", "yes", "on"}


def approver_roles() -> frozenset[str]:
    configured = os.environ.get("AMC_APPROVER_ROLES", "")
    roles = frozenset(role.strip().lower() for role in configured.split(",") if role.strip())
    return roles or DEFAULT_APPROVER_ROLES


def self_approval_allowed() -> bool:
    environment = (os.environ.get("AMC_ENV") or ENV_LOCAL).strip().lower()
    flag = (os.environ.get("AMC_ALLOW_SELF_APPROVAL") or "").strip().lower() in _TRUTHY
    return flag and environment != "production"


def run_initiator(run: dict) -> str | None:
    value = ((run.get("metadata") or {}).get("initiated_by") or "").strip()
    return value or None


def assert_may_decide(principal: Principal, initiator: str | None, decision: str, *, subject: str = "run") -> None:
    """Role check for any decision; separation of duties for approvals.

    ``initiator`` is whoever created the subject (a run, a content item). An
    unknown initiator cannot prove separation, so approval is refused.
    """
    if principal.role.strip().lower() not in approver_roles():
        raise HTTPException(status_code=403, detail="Deciding approvals requires an approver role")
    if decision != "approve" or self_approval_allowed():
        return
    if not initiator:
        raise HTTPException(
            status_code=403,
            detail=f"{subject.capitalize()} initiator is not recorded, so separation of duties cannot be verified",
        )
    if initiator == principal.user_id:
        raise HTTPException(status_code=403, detail=f"The principal who started a {subject} cannot approve it")


def assert_may_decide_approval(principal: Principal, run: dict, decision: str) -> None:
    assert_may_decide(principal, run_initiator(run), decision, subject="run")


__all__ = [
    "DEFAULT_APPROVER_ROLES",
    "approver_roles",
    "assert_may_decide",
    "assert_may_decide_approval",
    "run_initiator",
    "self_approval_allowed",
]
