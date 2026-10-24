"""Shared helpers for the agency operating framework tests.

Separation of duties is enforced (``AMC_ALLOW_SELF_APPROVAL`` is removed): the
author works as an operator, a second person verifies, a third approves. All
evidence these helpers create is fictional and labelled ``synthetic:``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.app.main import app

TENANT = "tenant-events-test"
AUTHOR = "afw-author"
VERIFIER = "afw-verifier"
REVIEWER = "afw-reviewer"
FRESH = "2026-10-20T00:00:00+00:00"

client = TestClient(app)


_STATE = {"tenant": TENANT}


def as_user(monkeypatch, user: str, role: str = "operator", tenant: str | None = None, projects: str = "*") -> None:
    monkeypatch.setenv("AMC_LOCAL_USER_ID", user)
    monkeypatch.setenv("AMC_LOCAL_ROLE", role)
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", tenant or _STATE["tenant"])
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", projects)


def use_tenant(monkeypatch, tenant: str) -> None:
    """Run the helpers inside another tenant (for example a VNEXUS test world)."""
    _STATE["tenant"] = tenant
    monkeypatch.delenv("AMC_ALLOW_SELF_APPROVAL", raising=False)
    as_user(monkeypatch, AUTHOR)


def key() -> dict:
    return {"Idempotency-Key": str(uuid4())}


@pytest.fixture
def afw(monkeypatch, tmp_path):
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    monkeypatch.delenv("AMC_ALLOW_SELF_APPROVAL", raising=False)
    _STATE["tenant"] = TENANT
    as_user(monkeypatch, AUTHOR)
    return {"export_root": tmp_path}


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def create_project(project_id: str | None = None, name: str = "Fictional Co (test)") -> str:
    project_id = project_id or f"proj-afw-{uuid4().hex[:10]}"
    ok(client.post("/projects", json={"display_name": name, "project_id": project_id, "slug": project_id}, headers=key()), 201)
    return project_id


def instantiate(project_id: str, archetype: str = "OTHER", scope: str = "") -> dict:
    return ok(client.post("/agency-framework/plans", json={"project_id": project_id, "archetype": archetype,
                                                           "engagement_scope": scope}, headers=key()), 201)


def task(plan_id: str, task_id: str) -> dict:
    return ok(client.get(f"/agency-framework/plans/{plan_id}/tasks/{task_id}"))


def version(plan_id: str, task_id: str) -> int:
    return task(plan_id, task_id)["instance"]["version"]


def apply(plan_id: str, decisions: list[tuple[str, str, str]]) -> dict:
    body = {"decisions": [{"task_id": t, "applicability": a, "reason": r} for t, a, r in decisions]}
    return ok(client.post(f"/agency-framework/plans/{plan_id}/applicability", json=body, headers=key()))


def move(plan_id: str, task_id: str, target: str, reason: str = ""):
    return client.post(f"/agency-framework/plans/{plan_id}/tasks/{task_id}/transition",
                       json={"target": target, "expected_version": version(plan_id, task_id), "reason": reason},
                       headers=key())


def set_refs(plan_id: str, task_id: str, *, evidence=(), artifacts=(), decisions=()):
    return client.put(f"/agency-framework/plans/{plan_id}/tasks/{task_id}/refs",
                      json={"expected_version": version(plan_id, task_id), "evidence_refs": list(evidence),
                            "artifact_refs": list(artifacts), "decision_refs": list(decisions)}, headers=key())


def verify(monkeypatch, plan_id: str, task_id: str, *, user: str = VERIFIER, role: str = "reviewer"):
    as_user(monkeypatch, user, role)
    try:
        return client.post(f"/agency-framework/plans/{plan_id}/tasks/{task_id}/verify",
                           json={"expected_version": version(plan_id, task_id)}, headers=key())
    finally:
        as_user(monkeypatch, AUTHOR)


def decide(monkeypatch, approval_id: str, decision: str = "approve", *, user: str = REVIEWER, role: str = "reviewer"):
    as_user(monkeypatch, user, role)
    try:
        return client.post(f"/approvals/{approval_id}/decide", json={"decision": decision}, headers=key())
    finally:
        as_user(monkeypatch, AUTHOR)


def evidence(monkeypatch, project_id: str, text: str, *, domain: str = "market", uri: str | None = None,
             fetched_at: str = FRESH, promote: bool = True) -> str:
    """A fictional knowledge source, reviewed by an approver so it counts as reviewed evidence."""
    item = ok(client.post(f"/projects/{project_id}/knowledge", json={
        "domain": domain, "source_uri": uri or f"synthetic://fixture/{uuid4().hex[:8]}", "text": text,
        "license": "CC-BY-4.0", "fetched_at": fetched_at}), 201)["item"]
    if promote and item["status"] == "AWAITING_REVIEW":
        as_user(monkeypatch, VERIFIER, "reviewer")
        try:
            ok(client.post(f"/projects/{project_id}/knowledge/{item['item_id']}/review", json={"accept": True}))
        finally:
            as_user(monkeypatch, AUTHOR)
    return f"knowledge:{item['item_id']}"


def artifact(project_id: str, key_: str, artifact_type: str, text: str, depends_on=()) -> str:
    created = ok(client.post(f"/projects/{project_id}/artifacts", json={
        "artifact_key": key_, "artifact_type": artifact_type, "content_text": text,
        "depends_on": list(depends_on)}), 201)["artifact"]
    return f"artifact:{created['artifact_id']}@v{created['version']}"


def revise(project_id: str, ref: str, text: str) -> str:
    artifact_id, _, v = ref.removeprefix("artifact:").rpartition("@v")
    out = ok(client.post(f"/projects/{project_id}/artifacts/{artifact_id}/revisions",
                         json={"expected_version": int(v), "content_text": text}))
    return f"artifact:{artifact_id}@v{out['artifact']['version']}"


def decision(plan_id: str, question: str, alternatives: list[str], selected: str, evidence_refs=()) -> str:
    return ok(client.post(f"/agency-framework/plans/{plan_id}/decisions", json={
        "question": question, "alternatives": alternatives, "selected_option": selected,
        "evidence_refs": list(evidence_refs)}, headers=key()), 201)["decision_ref"]


def complete_task(monkeypatch, plan_id: str, task_id: str, *, evidence=(), artifacts=(), decisions=()) -> dict:
    """READY -> ACTIVE -> refs -> IN_REVIEW -> verified by a second person -> approved by a third."""
    ok(move(plan_id, task_id, "READY"))
    ok(move(plan_id, task_id, "ACTIVE"))
    ok(set_refs(plan_id, task_id, evidence=evidence, artifacts=artifacts, decisions=decisions))
    ok(move(plan_id, task_id, "IN_REVIEW"))
    ok(verify(monkeypatch, plan_id, task_id))
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/{task_id}/request-approval",
                               json={"expected_version": version(plan_id, task_id)}, headers=key()))
    ok(decide(monkeypatch, requested["approval_ref"]))
    return ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/{task_id}/settle",
                          json={"expected_version": version(plan_id, task_id)}, headers=key()))
