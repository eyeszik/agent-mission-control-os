"""Each approval request gets a run that can still take a decision and names its own requester.

``open_artifact_approval`` anchored every request for a mission on one deterministic run. After a rejection
that run is ``rejected``, so a later request could never be decided (409), and a later request by someone
else was checked against the first requester, so that person could approve their own request.
These tests drive the real ``/approvals/{id}/decide`` route.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from services.langgraph.agency.intake.release import approval_run_id, open_artifact_approval
from services.langgraph.persistence.projects import create_project_workspace
from services.langgraph.persistence.runs import get_run_record
from services.langgraph.security.auth import Principal
from services.langgraph.tests.test_brand_os_api import _as, _decide, _get, _post


@pytest.fixture()
def project(tmp_path, monkeypatch):
    tenant, pid = "tenant-apr-" + uuid4().hex[:8], "prj-apr-" + uuid4().hex[:8]
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    create_project_workspace(tenant_id=tenant, project_id=pid, actor="alice", display_name="per-request fixture",
                             export_root=tmp_path)
    return {"tenant": tenant, "id": pid, "tmp": tmp_path}


def _open(p, user: str, mission: str, version: int, digest: str, *, project_id: str | None = None) -> dict:
    pid = project_id or p["id"]
    principal = Principal(user_id=user, tenant_id=p["tenant"], role="operator", allowed_project_ids=frozenset({pid}))
    return open_artifact_approval(principal, tenant_id=p["tenant"], project_id=pid, mission_id=mission,
                                  contract_hash="c" * 64, artifact_id=f"art-{mission}", version=version,
                                  content_hash=digest, run_pipeline="test_per_request", policy_version="test/v1",
                                  subject_type="TEST_SUBJECT", reason="per-request run test")


def test_an_sop_re_request_after_rejection_can_be_decided(project, monkeypatch):
    _as(monkeypatch, project)
    first = _post(project, "F05").json()
    assert _decide(monkeypatch, project, first["approval_id"], "reject").status_code == 200
    _as(monkeypatch, project)
    again = _post(project, "F05").json()
    assert again["state"] == "PENDING" and again["approval_id"] != first["approval_id"]
    decided = _decide(monkeypatch, project, again["approval_id"], "approve")
    assert decided.status_code == 200, decided.json()
    _as(monkeypatch, project)
    assert _get(project, "F05").json()["state"] == "ADOPTED"


def test_a_later_request_is_checked_against_its_own_requester(project, monkeypatch):
    mission = "m-" + uuid4().hex[:10]
    first = _open(project, "alice", mission, 1, "a" * 64)
    assert first["run_id"] == approval_run_id(mission), "the first request keeps the deterministic run"
    assert _decide(monkeypatch, project, first["approval_id"], "approve", user="bob").status_code == 200
    second = _open(project, "bob", mission, 2, "b" * 64)
    assert second["run_id"] != first["run_id"]
    assert get_run_record(second["run_id"])["metadata"]["initiated_by"] == "bob"
    assert _decide(monkeypatch, project, second["approval_id"], "approve", user="bob").status_code == 403
    assert _decide(monkeypatch, project, second["approval_id"], "approve", user="alice").status_code == 200


def test_the_same_requester_keeps_an_open_run_and_a_repeated_request_is_idempotent(project, monkeypatch):
    mission = "m-" + uuid4().hex[:10]
    first = _open(project, "alice", mission, 1, "a" * 64)
    assert _open(project, "alice", mission, 1, "a" * 64)["approval_id"] == first["approval_id"]
    assert _open(project, "carol", mission, 1, "a" * 64)["approval_id"] == first["approval_id"], (
        "an identical request already pending in this mission is returned, not duplicated")
    newer = _open(project, "alice", mission, 2, "b" * 64)
    assert newer["run_id"] == first["run_id"], "alice's run is still open, so it is reused as before"


def test_a_run_from_another_project_is_never_reused(project, monkeypatch):
    mission, other = "m-" + uuid4().hex[:10], "prj-other-" + uuid4().hex[:8]
    create_project_workspace(tenant_id=project["tenant"], project_id=other, actor="alice", display_name="other",
                             export_root=project["tmp"])
    elsewhere = _open(project, "alice", mission, 1, "a" * 64, project_id=other)
    here = _open(project, "alice", mission, 1, "a" * 64)
    assert here["run_id"] != elsewhere["run_id"]
    run = get_run_record(here["run_id"])
    assert (run["tenant_id"], run["project_id"]) == (project["tenant"], project["id"])
    assert _decide(monkeypatch, project, here["approval_id"], "approve", user="bob").status_code == 200
