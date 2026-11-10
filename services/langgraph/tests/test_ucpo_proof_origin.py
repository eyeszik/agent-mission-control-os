"""Synthetic UCPO release-origin tests; no real browser, approval or deployment.

The fake dispatch feeds deterministic observations through the *real* fenced
commit and approval paths. It tests authority plumbing only, not the quality or
integrity of a real website build or browser execution.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import uuid4

from services.langgraph.agency.intake.release import artifact_release_verdict
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.agency.ucpo import service
from services.langgraph.agency.ucpo.brand_web import proof_freshness
from services.langgraph.agency.ucpo.contracts import BuildResult, WebsiteBrief
from services.langgraph.persistence import durable_runs
from services.langgraph.persistence.agency_kernel import get_artifact
from services.langgraph.persistence.projects import create_project_workspace, revise_project_artifact
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests.test_ucpo_pipeline import rendered_from_source

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = json.loads((ROOT / "sample_ucpo_website.json").read_text())


def test_generic_website_proof_requires_exact_committed_job_and_approval(tmp_path, monkeypatch):
    tenant, project = "tenant-ucpo-proof-" + uuid4().hex[:8], "prj-proof-" + uuid4().hex[:8]
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    create_project_workspace(tenant_id=tenant, project_id=project, actor="alice", display_name="Synthetic proof fixture", export_root=tmp_path)
    adapter = LocalStorageAdapter(tmp_path)
    alice = Principal("alice", tenant, "operator", frozenset({project}))
    compiled = service.compile_site_line(alice, project, "halden", WebsiteBrief.model_validate(SAMPLE), adapter=adapter, export_root=tmp_path)
    loaded = service.load_stages(project, "halden", adapter)
    export = {"index.html": base64.b64encode(b"TEST FIXTURE: no browser ran").decode()}
    build = BuildResult(status="PASSED", source_tree_hash=loaded["manifest"].tree_hash,
                        isolation={"note": "SYNTHETIC TEST ONLY"}, steps=(), dependency_manifest={},
                        output_hash=service.export_digest(export))
    qa = rendered_from_source(loaded["requirements"], loaded["ir"], loaded["files"]).model_copy(
        update={"build_output_hash": build.output_hash, "browser": {"name": "SYNTHETIC TEST ONLY"}})
    record = {"build": build.model_dump(mode="json"), "browser_qa": qa.model_dump(mode="json"), "export": export}

    def fake_dispatch(_self, job):
        payload = service._dump(record)
        stored = adapter.put_bytes(tenant_id=job["tenant_id"], project_id=job["project_id"], data=payload)
        return {"storage_uri": stored.storage_uri, "content_hash": stored.content_hash, "route": "TEST FIXTURE ONLY"}

    monkeypatch.setattr(service.SiteBuildHandler, "dispatch", fake_dispatch)
    tick = service.run_build_tick(compiled["job_id"])
    assert tick.final_state == "WAITING_APPROVAL", tick.reasons
    view = service.inspect_site(alice, project, "halden", adapter=adapter)
    assert view["proof"]["eligible_for_approval"] and not view["release"]["allowed"]
    approval_id = view["approval"]["approval_id"]
    head = get_artifact(view["stages"]["release_proof"]["artifact_id"])
    assert proof_freshness(head, approval_id=approval_id) == []

    as_user(monkeypatch, "bob", role="reviewer", tenant=tenant, projects=project)
    decided = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers())
    assert decided.status_code == 200, decided.text

    def verdict():
        return artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=head["artifact_id"],
            verified_version=int(head["version"]), verified_hash=head["content_hash"], approval_id=approval_id,
            tenant_id=tenant, project_id=project)

    assert verdict().allowed  # Fixture evidence and a synthetic reviewer only; no deployment is authorized.
    assert proof_freshness(head, approval_id="different-approval") == ["PROOF_APPROVAL_ORIGIN_MISMATCH"]

    real_get = durable_runs.get_job
    job = real_get(compiled["job_id"])
    monkeypatch.setattr(durable_runs, "get_job", lambda _id: {**job, "result": {**job["result"], "proof_artifact": {}}})
    denied = verdict()
    assert not denied.allowed and "PROOF_JOB_RECEIPT_MISMATCH" in denied.reasons
    monkeypatch.setattr(durable_runs, "get_job", lambda _id: {**job, "project_id": "other-project"})
    assert "PROOF_JOB_MISSING_OR_SCOPE_MISMATCH" in verdict().reasons
    monkeypatch.setattr(durable_runs, "get_job", lambda _id: {**job, "spec": {"ucpo": {"revisions": []}}})
    assert "PROOF_JOB_INPUT_MISMATCH" in verdict().reasons
    monkeypatch.setattr(durable_runs, "get_job", lambda _id: {**job, "result": []})
    assert "PROOF_JOB_RECEIPT_MISMATCH" in verdict().reasons
    monkeypatch.setattr(durable_runs, "get_job", real_get)

    # Advancing an input head invalidates the old proof even if bytes are equal.
    source_id = loaded["entries"]["source"]["artifact_id"]
    source = get_artifact(source_id)
    revise_project_artifact(project_id=project, artifact_id=source_id, actor="alice", adapter=adapter,
                            expected_version=int(source["version"]), content_hash=source["content_hash"],
                            storage_uri=source["content_location"])
    stale = verdict()
    assert not stale.allowed and any(reason.startswith("PROOF_STALE") for reason in stale.reasons)
