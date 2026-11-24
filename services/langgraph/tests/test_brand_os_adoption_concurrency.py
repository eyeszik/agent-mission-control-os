"""Concurrent Brand OS adoption requests open exactly one pending approval, enforced by the database.

Runs on whichever backend the suite is configured for (SQLite locally, PostgreSQL in the PG CI job), so the
partial unique index is exercised on both. Projects, tenants and users are disposable fixtures.
"""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest

from services.langgraph.agency.intake import release
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.sop import brand_os_service, source_approval
from services.langgraph.core.errors import AMCError
from services.langgraph.persistence.approvals import create_approval_request, list_approvals_for_subject_refs
from services.langgraph.persistence.projects import create_project_workspace
from services.langgraph.security.auth import Principal

THREADS = 6


@pytest.fixture()
def project(tmp_path, monkeypatch):
    tenant, pid = "tenant-bos-cc-" + uuid4().hex[:8], "prj-bos-cc-" + uuid4().hex[:8]
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    create_project_workspace(tenant_id=tenant, project_id=pid, actor="alice", display_name="bos cc", export_root=tmp_path)
    principal = Principal(user_id="alice", tenant_id=tenant, role="operator", allowed_project_ids=frozenset({pid}))
    return {"tenant": tenant, "id": pid, "principal": principal, "adapter": LocalStorageAdapter(tmp_path)}


def _pending(p, artifact_id):
    return [a for a in list_approvals_for_subject_refs(p["id"], [artifact_id])
            if a["subject_type"] == source_approval.ADOPTION_SUBJECT_TYPE and a["status"] == "pending"]


def _request(p, sop="F04"):
    return brand_os_service.request_adoption(p["principal"], p["id"], sop, p["adapter"])


def test_parallel_requests_with_different_keys_converge_on_one_pending_approval(project):
    barrier, results, errors = threading.Barrier(THREADS), [], []

    def worker():
        barrier.wait()
        try:
            results.append(_request(project))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below, never swallowed
            errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert errors == [], errors
    assert len(results) == THREADS and {r.state for r in results} == {"PENDING"}
    assert len({r.approval_id for r in results}) == 1, "every caller sees the same approval"
    assert len(_pending(project, results[0].artifact_id)) == 1


def test_a_request_that_loses_the_insert_race_returns_the_winners_approval(project, monkeypatch):
    first = _request(project, "F02")
    # Force the losing interleaving deterministically: the pre-insert read misses the winner's row.
    real = release._matching_pending
    calls = {"n": 0}

    def miss_once(*args, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*args, **kwargs)
    monkeypatch.setattr(release, "_matching_pending", miss_once)
    # Call the staging step directly: the service short-circuits on PENDING before it would reach the insert.
    again = source_approval.stage_sop_for_adoption(project["principal"], project_id=project["id"], sop_id="F02",
                                                   adapter=project["adapter"])
    assert calls["n"] == 2, "the insert was attempted, refused by the index, and resolved by a re-read"
    assert again["approval"]["approval_id"] == first.approval_id
    assert len(_pending(project, first.artifact_id)) == 1


def test_the_database_itself_refuses_a_second_pending_adoption_approval(project):
    status = _request(project, "F03")
    pending = _pending(project, status.artifact_id)[0]
    with pytest.raises(Exception) as caught:
        create_approval_request(pending["run_id"], project["tenant"], project["id"], "duplicate", None,
                                subject_type=source_approval.ADOPTION_SUBJECT_TYPE, subject_ref=status.artifact_id,
                                subject_version_ref=pending["subject_version_ref"], subject_hash=pending["subject_hash"],
                                policy_version=source_approval.ADOPTION_POLICY_VERSION)
    assert release._is_unique_violation(caught.value), repr(caught.value)
    assert len(_pending(project, status.artifact_id)) == 1


def test_a_racing_request_for_different_content_is_a_conflict_not_a_second_approval(project, monkeypatch):
    status = _request(project, "F05")
    monkeypatch.setattr(release, "_stale_superseded", lambda *a, **k: None)  # the racer never saw the winner
    with pytest.raises(AMCError) as caught:
        release.open_artifact_approval(
            project["principal"], tenant_id=project["tenant"], project_id=project["id"],
            mission_id=source_approval.source_mission_id(status.artifact_id, source_approval.ADOPTION_SUBJECT_TYPE),
            contract_hash="c" * 64, artifact_id=status.artifact_id, version=status.artifact_version or 1,
            content_hash="f" * 64, run_pipeline=source_approval.RUN_PIPELINE,
            policy_version=source_approval.ADOPTION_POLICY_VERSION, subject_type=source_approval.ADOPTION_SUBJECT_TYPE,
            reason="racer with other bytes")
    assert caught.value.status_code == 409
    assert [a["approval_id"] for a in _pending(project, status.artifact_id)] == [status.approval_id]


def test_other_approval_purposes_are_not_constrained(project):
    status = _request(project, "F06")
    pending = _pending(project, status.artifact_id)[0]
    for _ in range(2):
        create_approval_request(pending["run_id"], project["tenant"], project["id"], "unrelated purpose", None,
                                subject_type="MISSION_ARTIFACT", subject_ref=status.artifact_id,
                                subject_version_ref="1", subject_hash="a" * 64)
    others = [a for a in list_approvals_for_subject_refs(project["id"], [status.artifact_id])
              if a["subject_type"] == "MISSION_ARTIFACT" and a["status"] == "pending"]
    assert len(others) == 2, "the index is scoped to the Brand OS purposes only"
