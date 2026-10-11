"""Clients and offboarding, the lifecycle DAG, the attention queue and evidence-based analytics.

Every number here is a count of real rows, with the table it came from and
when it was read. Nothing is estimated, and a metric with no source rows is
``NOT_MEASURED``, never zero-filled or invented.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from services.langgraph.agency.actions import broker
from services.langgraph.agency.actions.fsm import TERMINAL, ActionState
from services.langgraph.agency.actions.vocabulary import RiskClass
from services.langgraph.persistence import actions as adb
from services.langgraph.security.auth import Principal

CLIENT_ADMIN_ROLES = frozenset({"owner", "admin"})
OPEN_ACTION_STATES = tuple(s.value for s in ActionState if s not in TERMINAL and s is not ActionState.FAILED)


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    if not slug:
        raise ValueError("display_name needs at least one letter or digit")
    return slug


# --------------------------------------------------------------------------- clients


def _writer(principal: Principal) -> None:
    from services.langgraph.agency.vnexus.service import READ_ONLY_ROLES

    if broker.role(principal) in READ_ONLY_ROLES:
        raise broker.ActionForbidden(f"role {principal.role!r} is read-only")


def create_client(principal: Principal, *, display_name: str, notes: str = "") -> dict:
    _writer(principal)
    name = display_name.strip()
    if not 1 <= len(name) <= 120:
        raise ValueError("display_name must be 1 to 120 characters")
    return adb.create_client(tenant_id=principal.tenant_id, display_name=name, slug=_slug(name), notes=notes.strip()[:2000],
                             actor=principal.user_id)


def get_client(principal: Principal, client_id: str) -> dict:
    row = adb.get_client(client_id)
    if row is None or row["tenant_id"] != principal.tenant_id:
        raise LookupError("client not found")
    return row


def client_projects(principal: Principal, client_id: str) -> list[dict]:
    from services.langgraph.persistence.projects import get_project_workspace

    get_client(principal, client_id)
    out = []
    for pid in adb.projects_for_client(client_id):
        if not principal.can_access_project(pid):
            continue
        ws = get_project_workspace(pid)
        if ws is not None:
            out.append({"project_id": pid, "display_name": ws.display_name, "lifecycle_state": ws.lifecycle_state.value})
    return out


def list_clients(principal: Principal) -> list[dict]:
    return [{**c, "projects": client_projects(principal, c["client_id"])} for c in adb.list_clients(principal.tenant_id)]


def link_project(principal: Principal, client_id: str, project_id: str) -> dict:
    client = get_client(principal, client_id)
    if client["status"] != "ACTIVE":
        raise adb.ActionConflict(f"client is {client['status']}; new projects cannot be linked")
    broker.authorize_scope(principal, project_id, write=True)
    return adb.link_project(tenant_id=principal.tenant_id, client_id=client_id, project_id=project_id, actor=principal.user_id)


def offboarding_report(principal: Principal, client_id: str) -> dict:
    """What stands between this client and archival, and what retention means here."""
    from services.langgraph.persistence.approvals import list_pending_approvals
    from services.langgraph.persistence.projects import list_project_artifacts

    client = get_client(principal, client_id)
    project_ids = [p["project_id"] for p in client_projects(principal, client_id)]
    open_actions = [a for a in adb.list_requests(principal.tenant_id, project_ids=project_ids, states=OPEN_ACTION_STATES)]
    pending = [a for a in list_pending_approvals(principal.tenant_id) if a["project_id"] in set(project_ids)]
    artifacts = sum(len(list_project_artifacts(pid, limit=1000)) for pid in project_ids)
    blockers = []
    if open_actions:
        blockers.append(f"{len(open_actions)} open action(s) must finish or be cancelled")
    if pending:
        blockers.append(f"{len(pending)} pending approval(s) must be decided")
    return {
        "client": client, "projects": project_ids, "open_actions": [a["action_id"] for a in open_actions],
        "pending_approvals": [a["approval_id"] for a in pending], "artifacts_retained": artifacts,
        "can_archive": client["status"] == "OFFBOARDING" and not blockers, "blockers": blockers,
        "retention": {"policy": "artifacts, approvals and evidence are retained; archival only stops new work",
                      "deletion": "NOT_IMPLEMENTED: deleting client data is an R5 action and no deletion path exists"},
    }


def start_offboarding(principal: Principal, client_id: str) -> dict:
    broker.require_role(principal, CLIENT_ADMIN_ROLES, "offboarding a client")
    get_client(principal, client_id)
    return adb.set_client_status(client_id, "OFFBOARDING", expected="ACTIVE")


def archive_client(principal: Principal, client_id: str) -> dict:
    broker.require_role(principal, CLIENT_ADMIN_ROLES, "archiving a client")
    report = offboarding_report(principal, client_id)
    if not report["can_archive"]:
        raise adb.ActionConflict("cannot archive yet: " + ("; ".join(report["blockers"]) or "start offboarding first"))
    return adb.set_client_status(client_id, "ARCHIVED", expected="OFFBOARDING")


# --------------------------------------------------------------------------- lifecycle DAG


def _measured_rows(project_id: str) -> list[str]:
    """MEASURED results only (the VNEXUS table refuses anything else)."""
    from services.langgraph.persistence.database import normalize_record, table, transaction

    with transaction() as db:
        return [normalize_record(r)["measurement_id"] for r in db.execute(
            f"SELECT measurement_id FROM {table('vnexus_measurements')} WHERE project_id = ? ORDER BY observed_at", (project_id,)).fetchall()]

STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("INTAKE", ()),
    ("DISCOVERY", ("INTAKE",)),
    ("STRATEGY", ("DISCOVERY",)),
    ("IDENTITY", ("STRATEGY",)),
    ("PRODUCTION", ("IDENTITY",)),
    ("REVIEW", ("PRODUCTION",)),
    ("DELIVERY", ("REVIEW",)),
    ("DISTRIBUTION", ("DELIVERY",)),
    ("MEASUREMENT", ("DISTRIBUTION",)),
    ("MAINTENANCE", ("DELIVERY",)),
)


def lifecycle(principal: Principal, project_id: str) -> dict:
    """Stage status from evidence only. A stage is DONE when its evidence exists,
    BLOCKED_DEPENDENCY while an upstream stage is not done, and otherwise
    NOT_STARTED / IN_PROGRESS. Distribution and measurement say plainly when
    they are gated or unmeasured."""
    from services.langgraph.persistence.approvals import list_approvals_for_subject_refs
    from services.langgraph.persistence.projects import list_project_artifacts, list_project_events

    broker.authorize_scope(principal, project_id, write=False)
    artifacts = list_project_artifacts(project_id, limit=1000)
    types = {a.artifact_type for a in artifacts}
    events = list_project_events(project_id, limit=1000)
    approvals = list_approvals_for_subject_refs(project_id, [a.artifact_id for a in artifacts])
    actions = adb.list_requests(principal.tenant_id, project_ids=[project_id], limit=500)
    stale = [a.artifact_id for a in artifacts if a.status.upper() in {"STALE", "INVALIDATED"}]

    def ev(kind: str) -> list[dict]:
        return [{"sequence": e.sequence, "subject_ref": e.subject_ref} for e in events if e.event_type.value == kind]

    evidence: dict[str, tuple[str, list[str]]] = {}
    client_id = adb.client_for_project(project_id)
    evidence["INTAKE"] = ("DONE" if client_id else "IN_PROGRESS",
                          [f"client:{client_id}"] if client_id else ["project exists; link it to a client to complete intake"])
    research = [t for t in types if t in {"research_brief", "market_analysis"}]
    reads = [a["action_id"] for a in actions if a["effective_class"] == RiskClass.R0.value and a["state"] == "COMPLETED"]
    evidence["DISCOVERY"] = ("DONE" if research or reads else "NOT_STARTED", [*research, *reads])
    strategy = sorted(types & {"positioning_statement", "brand_platform"})
    evidence["STRATEGY"] = ("DONE" if len(strategy) == 2 else ("IN_PROGRESS" if strategy else "NOT_STARTED"), strategy)
    identity = sorted(types & {"brand_core", "identity_guidelines", "brand_guidelines_doc"})
    evidence["IDENTITY"] = ("DONE" if "brand_core" in types else "NOT_STARTED", identity)
    produced = [a.artifact_id for a in artifacts if a.artifact_type in {"media_asset", "design_token_set", "copy_variant",
                                                                        "campaign_package", "design_system_spec"}]
    evidence["PRODUCTION"] = ("DONE" if produced else "NOT_STARTED", produced[:20])
    decided = [a["approval_id"] for a in approvals if a.get("status") == "resolved" and a.get("decision") == "approve"]
    waiting = [a["approval_id"] for a in approvals if a.get("status") == "pending"]
    evidence["REVIEW"] = ("DONE" if decided else ("IN_PROGRESS" if waiting else "NOT_STARTED"), decided or waiting)
    manifests = [e for e in events if e.event_type.value == "VERIFIED" and (e.payload or {}).get("delivery_manifest_hash")]
    evidence["DELIVERY"] = ("DONE" if manifests else "NOT_STARTED",
                            [f"manifest:{(e.payload or {})['delivery_manifest_hash'][:16]}" for e in manifests])
    sim = [a["action_id"] for a in actions if a["effective_class"] in {"R2", "R3"} and a["state"] == "COMPLETED"]
    evidence["DISTRIBUTION"] = ("LIVE_GATED", [f"sandbox:{a}" for a in sim] or ["live distribution is disabled"])
    evidence["MEASUREMENT"] = ("NOT_MEASURED", ["no measured results are recorded for this project"])
    measured = _measured_rows(project_id)
    if measured:
        evidence["MEASUREMENT"] = ("DONE", measured[:20])
    attention_items = stale + [a["action_id"] for a in actions if a["state"] in {"UNKNOWN", "NEEDS_HUMAN"}]
    evidence["MAINTENANCE"] = ("ATTENTION" if attention_items else "READY", attention_items[:20])

    done = {"DONE"}
    nodes = []
    for stage, deps in STAGES:
        status, refs = evidence[stage]
        unmet = [d for d in deps if evidence[d][0] not in done]
        if unmet and status in {"NOT_STARTED", "IN_PROGRESS"}:
            status = "BLOCKED_DEPENDENCY"
        nodes.append({"stage": stage, "depends_on": list(deps), "status": status, "evidence": refs, "unmet": unmet})
    return {"project_id": project_id, "stages": nodes, "stale_artifacts": stale,
            "edges": [{"from": d, "to": s} for s, deps in STAGES for d in deps], "computed_at": adb.now_iso()}


# --------------------------------------------------------------------------- attention queue


def attention(principal: Principal, *, now: Optional[datetime] = None) -> list[dict]:
    """Decisions a person must make, in a deterministic order:
    (category, risk class desc, expiry asc). No scores are invented."""
    from services.langgraph.agency.actions import evidence as views
    from services.langgraph.persistence.approvals import list_pending_approvals

    moment = _now(now)
    items: list[dict] = []
    order = {"RECOVERY": 0, "APPROVAL": 1, "EXPIRING": 2, "BLOCKED": 3}
    for a in list_pending_approvals(principal.tenant_id):
        if not principal.can_access_project(a["project_id"]):
            continue
        action = adb.get_request(a["subject_ref"]) if str(a.get("subject_type", "")).startswith("ACTION_") else None
        risk = action["effective_class"] if action else "R1"
        items.append({"category": "APPROVAL", "kind": a.get("subject_type"), "ref": a["approval_id"], "project_id": a["project_id"],
                      "title": a.get("reason"), "risk": risk, "expires_at": action["expires_at"] if action else None,
                      "subject_ref": a.get("subject_ref"), "created_at": a.get("created_at")})
    for r in views.recovery_workbench(principal):
        if r["state"] in {"UNKNOWN", "NEEDS_HUMAN"}:
            items.append({"category": "RECOVERY", "kind": r["state"], "ref": r["action_id"], "project_id": r["project_id"],
                          "title": r["next_step"], "risk": None, "expires_at": None, "subject_ref": r["action_id"],
                          "created_at": r["updated_at"]})
    for e in views.expiring(principal, within_hours=24, now=moment):
        items.append({"category": "EXPIRING", "kind": e["state"], "ref": e["action_id"], "project_id": e["project_id"],
                      "title": f"{e['capability_id']} expires", "risk": None, "expires_at": e["expires_at"],
                      "subject_ref": e["action_id"], "created_at": None})
    items.sort(key=lambda i: (order[i["category"]], -int((i["risk"] or "R0")[1]), i["expires_at"] or "9999", i["ref"]))
    return items


# --------------------------------------------------------------------------- overview analytics


def analytics(principal: Principal, *, project_id: Optional[str] = None) -> dict:
    """Counts of real rows only, each with its source. No conversion rates,
    impressions or revenue exist here, so none are shown."""
    from services.langgraph.persistence.approvals import list_pending_approvals

    if project_id is not None:
        broker.authorize_scope(principal, project_id, write=False)
    as_of = adb.now_iso()
    actions = [a for a in adb.list_requests(principal.tenant_id, project_ids=[project_id] if project_id else None, limit=500)
               if principal.can_access_project(a["project_id"])]
    by_state: dict[str, int] = {}
    for a in actions:
        by_state[a["state"]] = by_state.get(a["state"], 0) + 1
    pending = [a for a in list_pending_approvals(principal.tenant_id)
               if principal.can_access_project(a["project_id"]) and (project_id is None or a["project_id"] == project_id)]
    completed = by_state.get("COMPLETED", 0)
    metrics = [
        {"metric": "actions_by_state", "value": by_state, "source": "action_requests", "definition": "count of actions per state"},
        {"metric": "approvals_pending", "value": len(pending), "source": "approvals", "definition": "approvals with status pending"},
        {"metric": "actions_completed_and_checked", "value": completed, "source": "action_requests",
         "definition": "actions whose provider state was read back and matched (all SANDBOX here)"},
        {"metric": "audience_reach", "value": None, "status": "NOT_MEASURED", "source": None,
         "definition": "no live distribution exists, so there is nothing to measure"},
    ]
    return {"as_of": as_of, "scope": project_id or "tenant", "metrics": metrics,
            "note": "Counts of stored records. No figure here is estimated, forecast or simulated."}


__all__ = ["STAGES", "analytics", "archive_client", "attention", "client_projects", "create_client", "get_client",
           "lifecycle", "link_project", "list_clients", "offboarding_report", "start_offboarding"]
