"""Incident freeze, autonomy dial, the LIVE-enablement gate and the policy simulator.

* Freeze (I19): a system freeze (``AMC_ACTIONS_FREEZE``), a tenant freeze or a
  project freeze blocks every *new dispatch*. Proposals, approvals and
  reconciliation of work already in flight continue, because reconciliation
  only reads. Freezing reduces authority, so any operator role may do it;
  lifting restores authority, so it needs an owner/admin who is not the person
  who froze it.
* Autonomy (per project): an upper bound on what may run without a person.
  It never grants anything. Raising it needs owner/admin; lowering it is open
  to anyone who may write.
* LIVE (I20): ``live_enablement()`` is the single gate. This change contains no
  code path that returns ENABLED.
* Policy simulator: read-only impact of a proposed budget ceiling.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from services.langgraph.persistence import actions as db
from services.langgraph.security.auth import Principal

from .broker import AUTONOMY_RAISE_ROLES, FREEZE_ROLES, LIFT_ROLES, ActionForbidden, authorize_scope, require_role, role
from .vocabulary import DEFAULT_AUTONOMY, AutonomyLevel

_TRUTHY = {"1", "true", "yes", "on", "all"}


def system_frozen() -> bool:
    return (os.environ.get("AMC_ACTIONS_FREEZE") or "").strip().lower() in _TRUTHY


def freeze_reasons(tenant_id: str, project_id: str) -> list[str]:
    reasons = []
    if system_frozen():
        reasons.append("SYSTEM_FROZEN: AMC_ACTIONS_FREEZE is set")
    for f in db.active_freezes(tenant_id):
        if f["scope_kind"] == "TENANT" or (f["scope_kind"] == "PROJECT" and f["scope_ref"] == project_id):
            reasons.append(f"{f['scope_kind']}_FROZEN:{f['freeze_id']}")
    return reasons


def freeze(principal: Principal, *, scope_kind: str, scope_ref: Optional[str], reason: str) -> dict:
    require_role(principal, FREEZE_ROLES, "an incident freeze")
    if scope_kind == "PROJECT":
        if not scope_ref:
            raise ValueError("a project freeze names the project")
        authorize_scope(principal, scope_ref, write=False)
    elif scope_kind == "TENANT":
        scope_ref = principal.tenant_id
    else:
        raise ValueError("scope_kind must be TENANT or PROJECT")
    if not reason.strip():
        raise ValueError("a freeze needs a reason")
    return db.create_freeze(tenant_id=principal.tenant_id, scope_kind=scope_kind, scope_ref=scope_ref, reason=reason.strip(),
                            actor=principal.user_id)


def lift(principal: Principal, freeze_id: str, *, reason: str) -> dict:
    current = db.get_freeze(freeze_id)
    if current is None or current["tenant_id"] != principal.tenant_id:
        raise LookupError("freeze not found")
    require_role(principal, LIFT_ROLES, "lifting a freeze")
    if current["frozen_by"] == principal.user_id:
        raise ActionForbidden("the person who froze dispatch cannot lift the freeze (separation of duties)")
    if not reason.strip():
        raise ValueError("lifting a freeze needs a reason")
    return db.lift_freeze(freeze_id, actor=principal.user_id, reason=reason.strip())


def autonomy(project_id: str) -> AutonomyLevel:
    row = db.get_autonomy(project_id)
    return AutonomyLevel(row["autonomy"]) if row else DEFAULT_AUTONOMY


def set_autonomy(principal: Principal, project_id: str, level: AutonomyLevel) -> dict:
    authorize_scope(principal, project_id, write=True)
    current = autonomy(project_id)
    if level.rank > current.rank and role(principal) not in AUTONOMY_RAISE_ROLES:
        raise ActionForbidden(f"raising autonomy requires one of {sorted(AUTONOMY_RAISE_ROLES)}")
    return db.set_autonomy(tenant_id=principal.tenant_id, project_id=project_id, autonomy=level.value, actor=principal.user_id)


def live_enablement() -> dict[str, Any]:
    reasons = [
        "no catalogue entry has a reviewed live provider binding",
        "this deployment contains no code path that dispatches in Environment.LIVE",
    ]
    if (os.environ.get("AMC_ACTIONS_LIVE") or "").strip():
        reasons.append("AMC_ACTIONS_LIVE is set and deliberately ignored")
    return {"status": "DISABLED", "reasons": reasons}


def simulate_budget_policy(principal: Principal, *, scope_kind: str, scope_ref: str, currency: str, ceiling_minor: int,
                           now: Optional[datetime] = None) -> dict[str, Any]:
    """What would a new ceiling block? Reads only; changes nothing."""
    moment = now or datetime.now(timezone.utc)
    currency = currency.upper()
    active = [r for r in db.list_reservations(principal.tenant_id, statuses=("RESERVED", "COMMITTED")) if r["currency"] == currency]

    def in_scope(r: dict) -> bool:
        if scope_kind == "PROJECT":
            return r["project_id"] == scope_ref
        if scope_kind == "CLIENT":
            return r.get("client_id") == scope_ref
        if scope_kind == "TENANT_DAY":
            return r["created_at"] >= db.iso(moment.replace(hour=0, minute=0, second=0, microsecond=0))
        if scope_kind == "TENANT_MONTH":
            return r["created_at"] >= db.iso(moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        return True

    used = sum(int(r["committed_minor"] if r["status"] == "COMMITTED" and r["committed_minor"] is not None else r["amount_minor"])
               for r in active if in_scope(r)) if scope_kind != "ACTION" else 0
    waiting = [a for a in db.list_requests(principal.tenant_id, states=("AWAITING_APPROVAL", "AUTHORIZED"))
               if a["binding"].get("currency") == currency and int(a["binding"].get("cost_minor") or 0) > 0]

    def would_block(a: dict) -> bool:
        cost = int(a["binding"]["cost_minor"])
        if scope_kind == "ACTION":
            return cost > ceiling_minor
        if scope_kind == "PROJECT" and a["project_id"] != scope_ref:
            return False
        if scope_kind == "CLIENT" and a.get("client_id") != scope_ref:
            return False
        return used + cost > ceiling_minor

    blocked = [{"action_id": a["action_id"], "cost_minor": int(a["binding"]["cost_minor"])} for a in waiting if would_block(a)]
    return {"simulation": True, "label": "SIMULATION: nothing was changed", "scope_kind": scope_kind, "scope_ref": scope_ref,
            "currency": currency, "proposed_ceiling_minor": ceiling_minor, "current_usage_minor": used,
            "headroom_minor": max(ceiling_minor - used, 0), "would_block": blocked,
            "existing_over_ceiling": used > ceiling_minor}


__all__ = ["autonomy", "freeze", "freeze_reasons", "lift", "live_enablement", "set_autonomy", "simulate_budget_policy",
           "system_frozen"]
