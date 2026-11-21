"""Brand OS SOP adoption through the API (``/brand-os``) with distinct requester and reviewer.

The SOP bytes are the committed, newly written drafts; projects and users are disposable fixtures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.sop import source_approval
from services.langgraph.agency.sop.brand_os_contracts import AdoptionStatus, SopDetail, SopListItem
from services.langgraph.persistence.approvals import list_approvals_for_subject_refs
from services.langgraph.persistence.projects import create_project_workspace, revise_project_artifact
from services.langgraph.tests._project_os_support import as_user, client

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages/shared/tests/fixtures/brand-os.json"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    tenant, pid = "tenant-bos-api-" + uuid4().hex[:8], "prj-bos-api-" + uuid4().hex[:8]
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    create_project_workspace(tenant_id=tenant, project_id=pid, actor="alice", display_name="bos fixture", export_root=tmp_path)
    return {"tenant": tenant, "id": pid, "tmp": tmp_path}


def _as(monkeypatch, p, user="alice", role="operator", projects=None):
    as_user(monkeypatch, user, role=role, tenant=p["tenant"], projects=projects or p["id"])


def _url(p, sop="F01"):
    return f"/brand-os/projects/{p['id']}/sops/{sop}/adoption"


def _post(p, sop="F01", key=None):
    return client.post(_url(p, sop), headers={"Idempotency-Key": key or str(uuid4())})


def _get(p, sop="F01"):
    return client.get(_url(p, sop))


def _decide(monkeypatch, p, approval_id, decision="approve", user="bob"):
    _as(monkeypatch, p, user=user, role="reviewer")
    return client.post(f"/approvals/{approval_id}/decide", json={"decision": decision}, headers={"Idempotency-Key": str(uuid4())})


def _adoption_approvals(p, artifact_id):
    return [a for a in list_approvals_for_subject_refs(p["id"], [artifact_id])
            if a["subject_type"] == source_approval.ADOPTION_SUBJECT_TYPE]


def test_index_and_detail_expose_identity_provenance_and_the_63_step_inventory(project, monkeypatch):
    _as(monkeypatch, project)
    items = [SopListItem.model_validate(x) for x in client.get("/brand-os/sops").json()]
    assert [i.sop_id for i in items] == [f"F{n:02d}" for n in range(1, 61)]
    drafts = [i for i in items if i.procedure_status == "NEWLY_AUTHORED_DRAFT"]
    assert [i.sop_id for i in drafts] == [f"F0{n}" for n in range(1, 9)]
    assert all(i.origin == "NEWLY_AUTHORED_SOP" and i.source_sha256 for i in drafts)
    assert sum(i.step_count for i in items) == 63 and {i.step_count for i in items[8:]} == {0}
    detail = SopDetail.model_validate(client.get("/brand-os/sops/F04").json())
    assert [s.sequence for s in detail.steps] == list(range(1, 8)) and detail.original_authenticated is False
    assert client.get("/brand-os/sops/F61").status_code == 422
    assert SopDetail.model_validate(client.get("/brand-os/sops/F09").json()).steps == ()


def test_request_is_pending_after_refresh_and_duplicates_open_nothing_new(project, monkeypatch):
    _as(monkeypatch, project)
    assert _get(project).json()["state"] == "NOT_STAGED"
    first = _post(project, key="same-key")
    assert first.status_code == 202, first.text
    status = AdoptionStatus.model_validate(first.json())
    assert status.state == "PENDING" and status.approval_id and status.decision_route == f"/approvals/{status.approval_id}/decide"
    assert status.artifact_hash == status.source_sha256 and "not a recovered original" in status.decision_covers
    assert _post(project, key="same-key").json() == first.json(), "same key replays the first response"
    assert _post(project).json()["approval_id"] == status.approval_id, "a new key still opens nothing new"
    assert AdoptionStatus.model_validate(_get(project).json()) == status, "refresh reads the persisted state"
    assert len(_adoption_approvals(project, status.artifact_id)) == 1


def test_an_independent_reviewer_adopts_exactly_this_revision_in_this_project_only(project, monkeypatch, tmp_path):
    _as(monkeypatch, project)
    status = _post(project, "F03").json()
    _as(monkeypatch, project, user="bob", role="reviewer")
    assert status["approval_id"] in {a["approval_id"] for a in client.get("/approvals").json()}, "reviewer finds it in the queue"
    assert _decide(monkeypatch, project, status["approval_id"]).status_code == 200
    _as(monkeypatch, project)
    adopted = _get(project, "F03").json()
    assert adopted["state"] == "ADOPTED" and adopted["grants_runtime_authority"] is False
    assert _post(project, "F03").json()["approval_id"] == status["approval_id"], "an adopted SOP is not re-requested"
    other = {"tenant": project["tenant"], "id": "prj-bos-other-" + uuid4().hex[:8]}
    create_project_workspace(tenant_id=other["tenant"], project_id=other["id"], actor="alice", display_name="other",
                             export_root=tmp_path)
    _as(monkeypatch, other)
    assert _get(other, "F03").json()["state"] == "NOT_STAGED"


def test_rejection_is_persisted_and_a_new_request_opens_a_new_decision(project, monkeypatch):
    _as(monkeypatch, project)
    first = _post(project, "F05").json()
    assert _decide(monkeypatch, project, first["approval_id"], "reject").status_code == 200
    _as(monkeypatch, project)
    assert _get(project, "F05").json()["state"] == "REJECTED"
    again = _post(project, "F05").json()
    assert again["state"] == "PENDING" and again["approval_id"] != first["approval_id"]


def test_the_requester_cannot_decide_their_own_adoption(project, monkeypatch):
    _as(monkeypatch, project)
    status = _post(project, "F02").json()
    assert _decide(monkeypatch, project, status["approval_id"], user="alice").status_code == 403
    _as(monkeypatch, project)
    assert _get(project, "F02").json()["state"] == "PENDING"


def test_roles_tenants_projects_and_unknown_sops_are_refused(project, monkeypatch):
    _as(monkeypatch, project, role="viewer")
    assert _post(project).status_code == 403
    _as(monkeypatch, project, projects="prj-elsewhere")
    assert _post(project).status_code == 403 and _get(project).status_code == 403
    as_user(monkeypatch, "mallory", role="admin", tenant="tenant-other", projects="*")
    assert _get(project).status_code in (403, 404)
    _as(monkeypatch, project)
    assert _post(project, "F09").status_code == 404, "F09 has no draft to adopt"
    assert client.post(_url(project), headers={}).status_code == 422, "Idempotency-Key is required"


def test_changed_draft_bytes_and_a_changed_stored_revision_are_never_adopted(project, monkeypatch):
    import services.langgraph.agency.sop.brand_os_source as bos

    _as(monkeypatch, project)
    original = bos.draft_bytes
    monkeypatch.setattr(bos, "draft_bytes", lambda entry: b"tampered")
    assert _post(project, "F06").status_code == 422
    monkeypatch.setattr(bos, "draft_bytes", original)
    status = _post(project, "F06").json()
    assert _decide(monkeypatch, project, status["approval_id"]).status_code == 200
    revise_project_artifact(project_id=project["id"], artifact_id=status["artifact_id"], actor="alice",
                            adapter=LocalStorageAdapter(project["tmp"]), expected_version=status["artifact_version"],
                            content_text="edited outside the pinned revision")
    _as(monkeypatch, project)
    assert _get(project, "F06").json()["state"] == "REVISION_CHANGED"


def test_a_crash_after_storing_but_before_the_approval_converges_on_retry(project, monkeypatch):
    _as(monkeypatch, project)

    def broken(*args, **kwargs):
        raise RuntimeError("simulated failure between store and approval")

    monkeypatch.setattr(source_approval, "_open", broken)
    with pytest.raises(RuntimeError):
        _post(project, "F07")
    monkeypatch.undo()
    _as(monkeypatch, project)
    stuck = _get(project, "F07").json()
    assert stuck["state"] == "STAGED_NO_APPROVAL" and stuck["approval_id"] is None
    recovered = _post(project, "F07").json()
    assert recovered["state"] == "PENDING" and recovered["artifact_id"] == stuck["artifact_id"]
    assert len(_adoption_approvals(project, stuck["artifact_id"])) == 1


def test_the_typescript_fixture_matches_the_api_contracts():
    sample = {
        "sops": [x.model_dump(mode="json") for x in __import__(
            "services.langgraph.agency.sop.brand_os_service", fromlist=["list_sops"]).list_sops()[:9]],
        "detail": __import__("services.langgraph.agency.sop.brand_os_service", fromlist=["sop_detail"]).sop_detail("F04")
        .model_dump(mode="json"),
        "status": AdoptionStatus(project_id="prj_1", sop_id="F01", name="Founder DNA Interview", draft_version="0.1-draft",
                                 source_sha256="0" * 64, state="PENDING", decision_covers="fixture",
                                 approval_id="a1", decision_route="/approvals/a1/decide").model_dump(mode="json"),
    }
    text = json.dumps(sample, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1":
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text
