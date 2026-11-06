"""Shared fixtures for the ACE v12 suites: one tenant, two projects, named people with
distinct roles, and helpers that drive the real routes (including the existing
``/approvals/{id}/decide``)."""

from __future__ import annotations

from uuid import uuid4

from services.langgraph.persistence import actions as adb
from services.langgraph.tests._project_os_support import as_user, client, headers

# People (all fictional). alice requests, bob reviews, fran approves money
# (an admin), olivia owns the tenant, otto is a second owner, victor only views.
REQUESTER, REVIEWER, FINANCE, OWNER, OWNER2, VIEWER = "alice", "bob", "fran", "olivia", "otto", "victor"
ROLES = {REQUESTER: "editor", REVIEWER: "reviewer", FINANCE: "admin", OWNER: "owner", OWNER2: "owner", VIEWER: "viewer"}


def make_world(monkeypatch, tmp_path, *, autonomy: str = "REQUEST_APPROVAL", budget: bool = True) -> dict:
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.delenv("AMC_ACTIONS_FREEZE", raising=False)
    tenant = f"tenant-ace-{uuid4().hex[:8]}"
    project, other = f"prj-ace-{uuid4().hex[:8]}", f"prj-ace-{uuid4().hex[:8]}"
    as_user(monkeypatch, OWNER, role="owner", tenant=tenant)
    for pid in (project, other):
        r = client.post("/projects", json={"display_name": f"ACE {pid}", "project_id": pid, "slug": pid}, headers=headers())
        assert r.status_code == 201, r.text
    for pid in (project, other):
        r = client.put(f"/actions/projects/{pid}/autonomy", json={"autonomy": autonomy})
        assert r.status_code == 200, r.text
    if budget:
        adb.set_budget_policy(tenant_id=tenant, scope_kind="ACTION", scope_ref="*", currency="USD", ceiling_minor=50_000, actor="test")
        adb.set_budget_policy(tenant_id=tenant, scope_kind="TENANT_DAY", scope_ref=tenant, currency="USD", ceiling_minor=100_000,
                              actor="test")
    w = {"tenant": tenant, "project": project, "other": other, "mp": monkeypatch}
    act_as(w, REQUESTER)
    return w


def act_as(w: dict, user: str, *, tenant: str | None = None, projects: str = "*") -> None:
    as_user(w["mp"], user, role=ROLES[user], tenant=tenant or w["tenant"], projects=projects)


def propose(w: dict, capability: str, args: dict, *, env: str = "SANDBOX", key: str | None = None, project: str | None = None,
            expect: int | None = 201, **extra) -> dict:
    body = {"capability_id": capability, "project_id": project or w["project"], "environment": env, "args": args, **extra}
    r = client.post("/actions", json=body, headers={"Idempotency-Key": key or f"k-{uuid4().hex}"})
    if expect is not None:
        assert r.status_code == expect, r.text
    return r.json()


def decide(w: dict, approval_id: str, user: str, decision: str = "approve") -> int:
    act_as(w, user)
    r = client.post(f"/approvals/{approval_id}/decide", json={"decision": decision}, headers=headers())
    return r.status_code


def approvals_of(action: dict) -> dict[str, str]:
    from services.langgraph.persistence.approvals import get_approvals_for_run

    out = {}
    for a in get_approvals_for_run(action["run_id"]):
        if a["subject_ref"] == action["action_id"] and a["subject_type"] not in out:
            out[a["subject_type"]] = a["approval_id"]
    return out


def approve_all(w: dict, action: dict) -> None:
    ids = approvals_of(action)
    for subject, approval_id in ids.items():
        user = {"ACTION_EXECUTION": REVIEWER, "ACTION_SPEND": FINANCE, "ACTION_GOVERNANCE": OWNER2}[subject]
        assert decide(w, approval_id, user) == 200, (subject, approval_id)
    act_as(w, REQUESTER)


def dispatch(action_id: str):
    return client.post(f"/actions/{action_id}/dispatch")


CMS = {"site": "acme-site", "path": "/launch/spring", "title": "Spring launch", "body": "Hello (fictional copy)."}
SPEND = {"campaign": "spring-launch", "amount_minor": 12_500, "currency": "USD"}
EMAIL = {"to": ["client@example.com"], "subject": "Your draft is ready", "body": "Fictional message."}
