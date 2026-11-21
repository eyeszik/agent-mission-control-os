"""WO-03: Brand OS source approval evidence comes only from the native approvals route.

Synthetic fixture bytes stand in for a source document; nothing here is a Brand OS procedure.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.langgraph.agency.intake.release import open_artifact_approval
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.sop.source_approval import (
    POLICY_VERSION,
    SUBJECT_TYPE,
    SourceApprovalEvidence,
    open_source_approval,
    verify_source_approval,
)
from services.langgraph.persistence.projects import create_project_artifact, create_project_workspace, revise_project_artifact
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user, client, headers

SYNTHETIC = "synthetic fixture: not a Brand OS source"


@pytest.fixture()
def source(tmp_path):
    tenant, project = "tenant-bos-" + uuid4().hex[:8], "prj-bos-" + uuid4().hex[:8]
    adapter = LocalStorageAdapter(tmp_path)
    create_project_workspace(tenant_id=tenant, project_id=project, actor="alice", display_name="source fixture",
                             export_root=tmp_path)
    alice = Principal("alice", tenant, "admin", frozenset({project}))
    item = create_project_artifact(tenant_id=tenant, project_id=project, actor="alice", artifact_key="brand-os-f01-source",
                                   artifact_type="product_spec", adapter=adapter, content_text=SYNTHETIC)
    return {"tenant": tenant, "project": project, "adapter": adapter, "alice": alice, "item": item}


def _open(s) -> dict:
    item = s["item"]
    return open_source_approval(s["alice"], tenant_id=s["tenant"], project_id=s["project"], artifact_id=item.artifact_id,
                                version=item.version, content_hash=item.content_hash, sop_id="F01")


def _decide(monkeypatch, s, approval_id: str, decision: str = "approve", user: str = "bob"):
    as_user(monkeypatch, user, role="reviewer", tenant=s["tenant"], projects=s["project"])
    return client.post(f"/approvals/{approval_id}/decide", json={"decision": decision}, headers=headers())


def _verify(s, approval_id, *, principal=None, item=None, content_hash=None) -> SourceApprovalEvidence:
    item = item or s["item"]
    return verify_source_approval(principal or s["alice"], tenant_id=s["tenant"], project_id=s["project"],
                                  artifact_id=item.artifact_id, version=item.version,
                                  content_hash=content_hash or item.content_hash, approval_id=approval_id)


def test_content_hash_is_the_sha256_of_the_source_bytes(source):
    assert source["item"].content_hash == hashlib.sha256(SYNTHETIC.encode("utf-8")).hexdigest()


def test_a_separate_reviewer_approving_the_exact_bytes_verifies(source, monkeypatch):
    approval = _open(source)
    assert (approval["subject_type"], approval["policy_version"]) == (SUBJECT_TYPE, POLICY_VERSION)
    assert _decide(monkeypatch, source, approval["approval_id"]).status_code == 200
    evidence = _verify(source, approval["approval_id"])
    assert evidence.verified and evidence.reasons == ()
    assert evidence.artifact_hash == source["item"].content_hash
    assert evidence.grants_runtime_authority is False and evidence.external_effects == "none"


def test_pending_rejected_and_unknown_approvals_do_not_verify(source, monkeypatch):
    pending = _open(source)
    assert "APPROVAL_PENDING" in _verify(source, pending["approval_id"]).reasons
    assert _decide(monkeypatch, source, pending["approval_id"], "reject").status_code == 200
    assert "APPROVAL_REJECTED" in _verify(source, pending["approval_id"]).reasons
    assert "NO_APPROVAL" in _verify(source, "approval-that-does-not-exist").reasons
    assert "NO_APPROVAL" in _verify(source, None).reasons


def test_the_initiator_cannot_approve_their_own_source(source, monkeypatch):
    approval = _open(source)
    assert _decide(monkeypatch, source, approval["approval_id"], user="alice").status_code == 403
    assert not _verify(source, approval["approval_id"]).verified


def test_an_approval_opened_for_another_purpose_does_not_authenticate_a_source(source, monkeypatch):
    item = source["item"]
    other = open_artifact_approval(source["alice"], tenant_id=source["tenant"], project_id=source["project"],
                                   mission_id="other-purpose-" + uuid4().hex, contract_hash="c", artifact_id=item.artifact_id,
                                   version=item.version, content_hash=item.content_hash, run_pipeline="test",
                                   policy_version="unrelated-policy", subject_type="UNRELATED", reason="Synthetic test")
    assert _decide(monkeypatch, source, other["approval_id"]).status_code == 200
    assert "APPROVAL_PURPOSE_MISMATCH" in _verify(source, other["approval_id"]).reasons


def test_different_bytes_or_a_revised_source_invalidate_the_approval(source, monkeypatch):
    approval = _open(source)
    assert _decide(monkeypatch, source, approval["approval_id"]).status_code == 200
    forged = _verify(source, approval["approval_id"], content_hash=hashlib.sha256(b"forged").hexdigest())
    assert "VERIFICATION_STALE: the artifact changed after it was verified" in forged.reasons
    revised = revise_project_artifact(project_id=source["project"], artifact_id=source["item"].artifact_id, actor="alice",
                                      adapter=source["adapter"], expected_version=source["item"].version,
                                      content_text=SYNTHETIC + " edited")["artifact"]
    after = _verify(source, approval["approval_id"], item=revised)
    assert not after.verified and {"SUBJECT_HASH_MISMATCH", "SUBJECT_VERSION_MISMATCH"} <= set(after.reasons)


def test_principals_outside_the_tenant_or_project_get_no_evidence(source, monkeypatch):
    approval = _open(source)
    assert _decide(monkeypatch, source, approval["approval_id"]).status_code == 200
    stranger = Principal("mallory", "tenant-other", "admin", frozenset({"*"}))
    outsider = Principal("carol", source["tenant"], "admin", frozenset({"prj-elsewhere"}))
    assert "PRINCIPAL_TENANT_MISMATCH" in _verify(source, approval["approval_id"], principal=stranger).reasons
    assert "PRINCIPAL_PROJECT_DENIED" in _verify(source, approval["approval_id"], principal=outsider).reasons
    with pytest.raises(PermissionError):
        open_source_approval(stranger, tenant_id=source["tenant"], project_id=source["project"],
                             artifact_id=source["item"].artifact_id, version=source["item"].version,
                             content_hash=source["item"].content_hash, sop_id="F01")


def test_evidence_can_never_claim_runtime_authority():
    base = {"verified": True, "reasons": (), "tenant_id": "t", "project_id": "p", "artifact_id": "a",
            "artifact_version": 1, "artifact_hash": "h", "approval_id": "x"}
    for override in ({"grants_runtime_authority": True}, {"external_effects": "publish"}, {"policy_version": "other"}):
        with pytest.raises(ValidationError):
            SourceApprovalEvidence(**base, **override)
