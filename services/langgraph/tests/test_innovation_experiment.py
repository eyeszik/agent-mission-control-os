"""Actual bounded local computation over disclosed synthetic inputs, not market evidence."""
from uuid import uuid4
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.langgraph.agency.execution_fabric.adapters.innovation import LexicalInput, calculate, lexical_measurement, verify_measurement
from services.langgraph.agency.innovation import local_experiment as local
from services.langgraph.agency.innovation.contracts import InnovationBrief
from services.langgraph.agency.innovation.service import create_run, tick_run, get_run
from services.langgraph.agency.project_os.storage import LocalStorageAdapter, StorageIntegrityError
from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError, get_artifact
from services.langgraph.persistence.database import atomic_transaction
from services.langgraph.persistence.projects import project_artifact_id, revise_project_artifact
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user, new_project


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    tenant = "t-lex-" + uuid4().hex[:12]
    as_user(monkeypatch, "lex-author", tenant=tenant)
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    project = new_project("Lexical fixture")
    project_id = project["project_id"]
    principal = Principal(user_id="lex-author", tenant_id=tenant, role="operator", allowed_project_ids=frozenset({project_id}))
    adapter = LocalStorageAdapter(tmp_path)
    initial = create_run(principal, project_id, InnovationBrief(objective="Fictional fixture: improve tool sharing"), uuid4().hex, adapter)
    run_id = initial["run"]["run_id"]
    complete = tick_run(principal, project_id, run_id, 1, adapter)
    assert complete["run"]["status"] == "COMPLETED"
    return principal, project_id, run_id, adapter, complete


def test_actual_fabric_computation_receipts_and_learning_preserve_simulation(experiment):
    principal, project, run, adapter, original = experiment
    result = local.run_local_experiment(principal, project, run, 2, adapter)
    assert result["status"] == "COMPLETED", result
    assert result["execution_mode"] == "LOCAL_COMPUTATION"
    assert result["input_provenance"] == "SIMULATED_OFFLINE_FIXTURE"
    assert result["measurements"] == {"case_count": 39, "baseline_retained_items": 39,
        "candidate_retained_items": 35, "baseline_redundant_items": 4, "candidate_redundant_items": 0, "unit": "items"}
    assert result["learning"]["decision"] == "SUPPORTED" and not result["release_authorized"]
    summary = result["proof"]["summary"]
    assert summary["dispatch_count"] == summary["execution_count"] == summary["matched_observation_count"] == 1
    assert get_run(principal, project, run, adapter) == original
    stored = local.read_report(principal, project, run, 2, adapter)
    assert stored["result_hash"] == result["result_hash"]
    assert stored["learning"] == result["learning"]


def test_replay_does_not_recompute_or_add_receipts(experiment, monkeypatch):
    principal, project, run, adapter, _ = experiment
    first = local.run_local_experiment(principal, project, run, 2, adapter)
    from services.langgraph.agency.execution_fabric import consumer
    def no_dispatch(*args, **kwargs):
        raise AssertionError("Replayed experiment must not dispatch again")
    monkeypatch.setattr(consumer, "dispatch_skill", no_dispatch)
    again = local.run_local_experiment(principal, project, run, 2, adapter)
    assert again["replayed"] is True
    assert again["result_hash"] == first["result_hash"]
    assert again["proof"]["summary"]["execution_count"] == 1


def test_cross_tenant_and_stale_versions_denied(experiment):
    principal, project, run, adapter, _ = experiment
    other = Principal(user_id="other", tenant_id="other-tenant", role="operator", allowed_project_ids=frozenset({project}))
    with pytest.raises(HTTPException) as denied:
        local.run_local_experiment(other, project, run, 2, adapter)
    assert denied.value.status_code == 403
    with pytest.raises(StaleArtifactVersionError):
        local.run_local_experiment(principal, project, run, 1, adapter)


def test_actual_stored_measurement_tampering_is_refused(experiment):
    principal, project, run, adapter, _ = experiment
    result = local.run_local_experiment(principal, project, run, 2, adapter)
    result_id = result["result_ref"].rsplit(":v", 1)[0]
    with atomic_transaction():
        revise_project_artifact(project_id=project, artifact_id=result_id, actor=principal.user_id,
            adapter=adapter, expected_version=1, content_text='{"fixture":"substituted output"}')
    with pytest.raises((StorageIntegrityError, KeyError)):
        local.read_report(principal, project, run, 2, adapter)


def test_bounded_input_and_independent_measurement_refusal():
    fields = {"source_ref": "fixture:v1", "source_hash": "a" * 64, "input_provenance": "SIMULATED_OFFLINE_FIXTURE"}
    inputs = LexicalInput(**fields, mechanisms=["A   b", "a b", "Unrelated"])
    assert calculate(inputs)["baseline_redundant_items"] == 1
    assert calculate(inputs)["candidate_redundant_items"] == 0
    payload = {"inputs": inputs.model_dump(mode="json")}
    output = lexical_measurement(payload)
    assert verify_measurement(output, payload).passed
    assert not verify_measurement({"content": '{"measurements":"fabricated"}'}, payload).passed
    for bad in (["x"] * 65, ["x" * 2001], []):
        with pytest.raises(ValidationError):
            LexicalInput(**fields, mechanisms=bad)


@pytest.mark.parametrize("field", ["measurement", "learning", "foreign_proof"])
def test_rewritten_learning_cannot_spoof_observation_or_read_foreign_proofs(experiment, monkeypatch, field):
    principal, project, run, adapter, _ = experiment
    result = local.run_local_experiment(principal, project, run, 2, adapter)
    identity = result["experiment_id"].removeprefix("lexical-")
    artifact_id = project_artifact_id(project, "innovation-learning-" + identity)
    head = get_artifact(artifact_id)
    stored = json.loads(adapter.get_bytes(head["content_location"]))
    if field == "measurement":
        stored["measurements"]["case_count"] = 64
    elif field == "learning":
        stored["learning"]["decision"] = "DISCONFIRMED"
    else:
        stored["fabric_run_id"] = "foreign-fabric-run"
        original = local.get_run_proof_bundle
        def no_foreign_read(fabric_run_id):
            assert fabric_run_id != "foreign-fabric-run", "Foreign proof content must not be read"
            return original(fabric_run_id)
        monkeypatch.setattr(local, "get_run_proof_bundle", no_foreign_read)
    revise_project_artifact(project_id=project, artifact_id=artifact_id, actor=principal.user_id,
        adapter=adapter, expected_version=1, content_text=json.dumps(stored))
    with pytest.raises(StorageIntegrityError):
        local.read_report(principal, project, run, 2, adapter)


def test_read_refuses_incomplete_permit_receipt_chain(experiment, monkeypatch):
    principal, project, run, adapter, _ = experiment
    local.run_local_experiment(principal, project, run, 2, adapter)
    original = local.get_run_proof_bundle
    def missing_permit(fabric_run_id):
        proof = original(fabric_run_id)
        proof["dispatch_permits"] = []
        proof["summary"]["dispatch_count"] = 0
        return proof
    monkeypatch.setattr(local, "get_run_proof_bundle", missing_permit)
    with pytest.raises(StorageIntegrityError, match="canonical observation"):
        local.read_report(principal, project, run, 2, adapter)
