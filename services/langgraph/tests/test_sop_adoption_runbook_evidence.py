"""The SOP adoption runbook's evidence query (step 0.4), run verbatim against real persisted approvals.

History is produced through the API (request, reject, re-request, approve, other SOPs, a stored-revision change);
one adversarial row in another tenant is written directly. The query text is read from the runbook itself, so the
document and the database cannot drift apart. Runs on whichever backend the suite targets (SQLite or PostgreSQL).
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.sop import source_approval
from services.langgraph.persistence.approvals import create_approval_request, get_approval
from services.langgraph.persistence.database import table, transaction
from services.langgraph.persistence.projects import create_project_workspace, revise_project_artifact
from services.langgraph.tests._project_os_support import as_user, client

RUNBOOK = Path(__file__).resolve().parents[3] / "docs/amcos-v11/SOP_ADOPTION_RUNBOOK.md"
LEGACY_0_4 = ("SELECT approval_id FROM {t} WHERE project_id = ? AND subject_type = 'BRAND_OS_SOP_ADOPTION' "
              "ORDER BY created_at DESC LIMIT 5")


def _query_0_4() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    match = re.search(r"-- 0\.4 .*?\n(select .*?;)", text, re.S)
    assert match, "query 0.4 not found in the runbook"
    return match.group(1)


def _run_0_4(tenant: str, project: str, artifact_id: str) -> list[dict]:
    sql = _query_0_4().replace("amc.approvals", table("approvals")).rstrip(";")
    for placeholder in ("'‹TENANT›'", "'‹PROJECT›'", "'‹ARTIFACT_ID›'"):
        sql = sql.replace(placeholder, "?")
    with transaction() as db:
        return [dict(r) for r in db.execute(sql, [tenant, project, artifact_id]).fetchall()]


def _as(monkeypatch, p, user="alice", role="operator"):
    as_user(monkeypatch, user, role=role, tenant=p["tenant"], projects=p["id"])


def _request(monkeypatch, p, sop):
    _as(monkeypatch, p)
    response = client.post(f"/brand-os/projects/{p['id']}/sops/{sop}/adoption", headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 202, response.text
    return response.json()


def _decide(monkeypatch, p, approval_id, decision):
    _as(monkeypatch, p, user="bob", role="reviewer")
    response = client.post(f"/approvals/{approval_id}/decide", json={"decision": decision},
                           headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 200, response.text


@pytest.fixture()
def history(tmp_path, monkeypatch):
    """F01: approved, then its stored bytes changed and it was requested again (twice, so one request goes stale).
    F02: rejected. F03-F07: five newer requests. Plus one planted row for F01's artifact in another tenant."""
    p = {"tenant": "tenant-rb-" + uuid4().hex[:8], "id": "prj-rb-" + uuid4().hex[:8]}
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    create_project_workspace(tenant_id=p["tenant"], project_id=p["id"], actor="alice", display_name="rb", export_root=tmp_path)
    approved = _request(monkeypatch, p, "F01")
    _decide(monkeypatch, p, approved["approval_id"], "approve")
    later = []
    for edit in ("edited outside the pinned revision", "edited again"):
        head = _request(monkeypatch, p, "F01") if later else approved
        revise_project_artifact(project_id=p["id"], artifact_id=approved["artifact_id"], actor="alice",
                                adapter=LocalStorageAdapter(tmp_path), expected_version=head["artifact_version"],
                                content_text=edit)
        later.append(_request(monkeypatch, p, "F01"))
    rejected = _request(monkeypatch, p, "F02")
    _decide(monkeypatch, p, rejected["approval_id"], "reject")
    others = [_request(monkeypatch, p, f"F0{n}")["approval_id"] for n in range(3, 8)]
    run_id = get_approval(approved["approval_id"])["run_id"]
    foreign = create_approval_request(run_id, "tenant-foreign-" + uuid4().hex[:6], p["id"], "planted", None,
                                      subject_type=source_approval.ADOPTION_SUBJECT_TYPE,
                                      subject_ref=approved["artifact_id"], subject_version_ref="1",
                                      subject_hash=approved["artifact_hash"])
    return {**p, "approved": approved, "later": later, "rejected": rejected, "others": others,
            "foreign": foreign["approval_id"]}


def test_query_0_4_returns_the_complete_history_of_this_sop_only(history):
    rows = _run_0_4(history["tenant"], history["id"], history["approved"]["artifact_id"])
    ids = [r["approval_id"] for r in rows]
    assert ids[0] == history["approved"]["approval_id"] and rows[0]["decision"] == "approve"
    assert len(ids) == len(set(ids)) >= 2 and history["later"][-1]["approval_id"] in ids
    assert "stale" in {r["status"] for r in rows}, "a superseded request is kept, not hidden"
    assert {r["subject_ref"] for r in rows} == {history["approved"]["artifact_id"]}
    assert history["foreign"] not in ids, "another tenant's row is excluded"
    assert not set(history["others"]) & set(ids) and history["rejected"]["approval_id"] not in ids, "other SOPs excluded"
    assert [(r["created_at"], r["approval_id"]) for r in rows] == sorted((r["created_at"], r["approval_id"]) for r in rows)


def test_rejected_decisions_are_kept_for_their_own_sop(history):
    rows = _run_0_4(history["tenant"], history["id"], history["rejected"]["artifact_id"])
    assert [(r["approval_id"], r["decision"]) for r in rows] == [(history["rejected"]["approval_id"], "reject")]


def test_the_legacy_five_row_window_hid_the_relevant_decisions(history):
    with transaction() as db:
        legacy = [r["approval_id"] for r in db.execute(LEGACY_0_4.format(t=table("approvals")), [history["id"]]).fetchall()]
    assert len(legacy) == 5 and history["approved"]["approval_id"] not in legacy
    assert history["foreign"] in legacy, "the legacy query did not bind the tenant"


def test_an_approval_of_an_earlier_digest_does_not_cover_the_current_bytes(history, monkeypatch):
    rows = _run_0_4(history["tenant"], history["id"], history["approved"]["artifact_id"])
    _as(monkeypatch, history)
    current = client.get(f"/brand-os/projects/{history['id']}/sops/F01/adoption").json()
    approved = [r for r in rows if r["decision"] == "approve"]
    assert approved and all(r["subject_version_ref"] != str(current["artifact_version"]) for r in approved)
    assert current["state"] != "ADOPTED", "an approval of another revision is never adoption of this one"
