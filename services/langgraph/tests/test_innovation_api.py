"""Network-free H02 API, durable-tick and refusal regressions; all content is fixture data."""
from uuid import uuid4

import pytest

from services.langgraph.agency.innovation import service
from services.langgraph.persistence import durable_runs
from services.langgraph.persistence.database import table, transaction
from services.langgraph.persistence.projects import list_project_artifacts, list_project_events
from services.langgraph.tests._project_os_support import as_user, client, new_project

BRIEF = {"objective": "Improve low-distraction library discovery", "mode": "GENERAL", "provider": "simulated"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    tenant = "tenant-innovation-" + uuid4().hex[:12]
    as_user(monkeypatch, "innovation-author", tenant=tenant)
    project = new_project("Innovation fixture")
    return tenant, project["project_id"]


def base(project):
    return f"/innovation/projects/{project[1]}/runs"


def create(project, *, brief=None, key=None):
    response = client.post(base(project), json=brief or BRIEF, headers={"Idempotency-Key": key or uuid4().hex})
    assert response.status_code == 201, response.text
    return response.json()


def test_simulation_is_persisted_and_durable_without_experiment_execution(project):
    initial = create(project, key="same-request")
    url = base(project) + "/" + initial["run"]["run_id"]
    assert initial["run"]["status"] == "RECEIVED" and not initial["run"]["ideas"]
    response = client.post(url + "/tick", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["version"] == 2 and result["run"]["simulation"]
    assert result["run"]["status"] == "COMPLETED"
    assert len(result["run"]["ideas"]) == 35 and len(result["run"]["experiments"]) == 5
    assert all(e["execution_state"] == "NOT_RUN" and e["approval_state"] == "NOT_REQUESTED" for e in result["run"]["experiments"])
    assert client.get(url).json() == result
    assert create(project, key="same-request") == result
    assert client.post(url + "/tick", json={"expected_version": 2}).json() == result
    assert durable_runs.get_job(initial["run"]["run_id"])["state"] == "DORMANT"
    assert {a.status for a in list_project_artifacts(project[1])} == {"draft"}
    events = list_project_events(project[1])
    assert any(e.event_type.value == "ARTIFACT_UPDATED" and e.actor == "innovation-author" for e in events)


def test_pagination_counts_only_this_feature_and_project(project):
    first, second = create(project), create(project)
    response = client.get(base(project) + "?limit=1&offset=1")
    assert response.status_code == 200
    assert response.json()["total"] == 2 and len(response.json()["runs"]) == 1
    assert response.json()["runs"][0]["run_id"] in {first["run"]["run_id"], second["run"]["run_id"]}
    assert client.get(base(project) + "?limit=101").status_code == 422
    assert client.get(base(project) + "?offset=-1").status_code == 422


def test_duplicate_key_with_different_input_refused(project):
    create(project, key="immutable-request")
    response = client.post(base(project), json={**BRIEF, "objective": "A different project objective"}, headers={"Idempotency-Key": "immutable-request"})
    assert response.status_code == 409
    assert client.get(base(project)).json()["total"] == 1


@pytest.mark.parametrize("extra", [{"tenant_id": "forged"}, {"approved": True}, {"external_execution": True}])
def test_forged_authority_and_unknown_fields_are_refused(project, extra):
    response = client.post(base(project), json={**BRIEF, **extra}, headers={"Idempotency-Key": uuid4().hex})
    assert response.status_code == 422
    assert client.get(base(project)).json()["total"] == 0


def test_missing_key_and_malformed_request_refused(project):
    assert client.post(base(project), json=BRIEF).status_code == 422
    assert client.post(base(project), json={**BRIEF, "objective": "short"}, headers={"Idempotency-Key": "x"}).status_code == 422
    assert client.post(base(project), json=BRIEF, headers={"Idempotency-Key": " "}).status_code == 422


@pytest.mark.parametrize("operation", ["get", "list", "tick", "control", "create"])
def test_cross_tenant_access_denied_before_read_or_write(project, monkeypatch, operation):
    initial = create(project)
    url = base(project) + "/" + initial["run"]["run_id"]
    as_user(monkeypatch, "other", tenant="tenant-foreign", projects="*")
    actions = {"get": lambda: client.get(url), "list": lambda: client.get(base(project)),
               "tick": lambda: client.post(url + "/tick", json={"expected_version": 1}),
               "control": lambda: client.post(url + "/control", json={"expected_version": 1, "action": "cancel"}),
               "create": lambda: client.post(base(project), json=BRIEF, headers={"Idempotency-Key": "other"})}
    assert actions[operation]().status_code == 403


def test_project_access_is_required_and_other_project_cannot_read_run(project, monkeypatch):
    initial = create(project)
    other = new_project("Other innovation fixture")
    run_id = initial["run"]["run_id"]
    assert client.get(f"/innovation/projects/{other['project_id']}/runs/{run_id}").status_code == 404
    as_user(monkeypatch, "innovation-author", tenant=project[0], projects=other["project_id"])
    assert client.get(base(project)).status_code == 403


def test_pause_resume_cancel_and_stale_requests(project):
    initial = create(project)
    url = base(project) + "/" + initial["run"]["run_id"]
    paused = client.post(url + "/control", json={"expected_version": 1, "action": "pause"})
    assert paused.status_code == 200 and paused.json()["run"]["status"] == "PAUSED"
    assert client.post(url + "/tick", json={"expected_version": 1}).status_code == 409
    assert client.post(url + "/tick", json={"expected_version": 2}).status_code == 409
    resumed = client.post(url + "/control", json={"expected_version": 2, "action": "resume"})
    assert resumed.status_code == 200 and resumed.json()["version"] == 3
    cancelled = client.post(url + "/control", json={"expected_version": 3, "action": "cancel"})
    assert cancelled.status_code == 200 and cancelled.json()["run"]["status"] == "CANCELLED"
    assert client.post(url + "/tick", json={"expected_version": 4}).json() == cancelled.json()
    assert durable_runs.get_job(initial["run"]["run_id"])["state"] == "STOPPED"


def test_live_provider_is_blocked_and_does_not_synthesize_content(project):
    initial = create(project, brief={**BRIEF, "provider": "live"})
    response = client.post(base(project) + "/" + initial["run"]["run_id"] + "/tick", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["status"] == "BLOCKED" and run["phase"] == "PROVIDER_GAP" and not run["simulation"]
    assert not run["ideas"] and not run["experiments"] and not run["evidence"]
    assert durable_runs.get_job(run["run_id"])["state"] == "BLOCKED_PROVIDER"


def test_create_partial_write_rolls_back_and_key_can_be_retried(project, monkeypatch):
    original = service.durable_runs.create_job
    def fail_after_artifact(**kwargs):
        raise RuntimeError("injected fixture interruption after artifact insertion")
    monkeypatch.setattr(service.durable_runs, "create_job", fail_after_artifact)
    with pytest.raises(RuntimeError, match="fixture interruption"):
        create(project, key="recover-create")
    assert client.get(base(project)).json()["total"] == 0
    monkeypatch.setattr(service.durable_runs, "create_job", original)
    assert create(project, key="recover-create")["version"] == 1


def test_tick_partial_write_rolls_back_intent_receipt_revision_and_job(project, monkeypatch):
    initial = create(project)
    run_id = initial["run"]["run_id"]
    url = base(project) + "/" + run_id
    original = service.revise_project_artifact
    def fail_after_revision(**kwargs):
        original(**kwargs)
        raise RuntimeError("injected fixture interruption after candidate revision")
    monkeypatch.setattr(service, "revise_project_artifact", fail_after_revision)
    with pytest.raises(RuntimeError, match="fixture interruption"):
        client.post(url + "/tick", json={"expected_version": 1})
    assert client.get(url).json() == initial
    assert durable_runs.get_job(run_id)["state"] == "SCHEDULED"
    with transaction() as db:
        row = db.execute(f"SELECT COUNT(*) AS n FROM {table('durable_intents')} WHERE job_id = ?", (run_id,)).fetchone()
        assert int(row["n"]) == 0
    monkeypatch.setattr(service, "revise_project_artifact", original)
    assert client.post(url + "/tick", json={"expected_version": 1}).json()["run"]["status"] == "COMPLETED"


def test_actual_bytes_are_verified_before_readback(project, monkeypatch):
    from services.langgraph.api.routes import innovation
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter
    initial = create(project)
    class CorruptReadAdapter(LocalStorageAdapter):
        def get_bytes(self, storage_uri):
            return b'{"fixture":"tampered"}'
    monkeypatch.setattr(innovation, "storage_adapter", lambda: CorruptReadAdapter(__import__("pathlib").Path("unused")))
    assert client.get(base(project) + "/" + initial["run"]["run_id"]).status_code == 409


def test_unknown_offline_dispatch_failure_is_durable_and_bounded(project, monkeypatch):
    initial = create(project)
    run_id = initial["run"]["run_id"]
    url = base(project) + "/" + run_id
    calls = []
    def fail_dispatch(self, job):
        calls.append(job["job_id"])
        raise RuntimeError("fixture pure dispatch interruption")
    monkeypatch.setattr(service.SimulationHandler, "dispatch", fail_dispatch)
    assert client.post(url + "/tick", json={"expected_version": 1}).status_code == 409
    assert durable_runs.get_job(run_id)["state"] == "RECONCILING"
    assert durable_runs.get_job(run_id)["attempts"] == 1
    final = client.post(url + "/tick", json={"expected_version": 1})
    assert final.status_code == 200, final.text
    assert final.json()["run"]["phase"] == "RETRY_EXHAUSTED"
    assert final.json()["run"]["status"] == "BLOCKED"
    assert durable_runs.get_job(run_id)["state"] == "DEAD_LETTER"
    assert durable_runs.get_job(run_id)["attempts"] == 2
    assert client.post(url + "/tick", json={"expected_version": 2}).json() == final.json()
    assert len(calls) == 2


def test_result_cannot_change_the_admitted_brief(project):
    from pydantic import ValidationError
    from services.langgraph.agency.innovation.compiler import compile_run
    from services.langgraph.agency.innovation.contracts import InnovationBrief
    from services.langgraph.agency.execution.canonical import canonical_hash
    original = InnovationBrief.model_validate(BRIEF)
    forged = InnovationBrief(objective="This is a different fixture objective")
    with pytest.raises(ValidationError, match="admitted brief"):
        service.RunDocument(brief=original, input_hash=canonical_hash(original), run=compile_run(forged, "ir-fixture"))
