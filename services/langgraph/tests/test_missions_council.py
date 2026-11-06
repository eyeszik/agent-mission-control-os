"""Mission council lifecycle through the real API: dispatch, Sentinel gate, approval, resume, recovery, blueprint."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.langgraph.agency.council import service
from services.langgraph.agency.council.engines import get_engine
from services.langgraph.persistence import council as store
from services.langgraph.persistence.checkpoints import close_checkpointer
from services.langgraph.persistence.database import table, transaction
from services.langgraph.tests.council_support import (
    AUTHOR,
    REVIEWER,
    as_user,
    client,
    council,  # noqa: F401 - fixture
    create_idea,
    decide,
    dispatch,
    event_types,
    gated_mission,
    key,
    seat_runs,
)


def test_engines_endpoint_reports_real_availability(council):
    body = client.get("/missions/engines").json()
    by_name = {e["engine"]: e for e in body["engines"]}
    assert set(by_name) == {"langgraph", "crewai", "autogen"}
    assert by_name["langgraph"]["available"] is True
    for name in ("crewai", "autogen"):
        assert by_name[name]["available"] == get_engine(name).availability()[0]
    assert body["model_mode"] == "MOCK_DETERMINISTIC" and body["real_models_enabled"] is False


def test_tools_endpoint_lists_the_allowlist_with_sensitivity(council):
    tools = {t["tool_id"]: t for t in client.get("/missions/tools").json()["tools"]}
    assert tools["workspace.write_scaffold"]["sensitivity"] == "WRITE"
    assert tools["workspace.write_scaffold"]["requires_approval"] is True
    assert tools["workspace.read_file"]["requires_approval"] is False


def test_langgraph_dispatch_pauses_at_the_sentinel_gate(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    assert mission["phase"] == "GATE" and mission["model_mode"] == "MOCK_DETERMINISTIC"
    assert mission["approval"]["status"] == "pending"
    assert mission["approval"]["subject_hash"] == mission["gate"]["subject_hash"]
    assert "WRITE_ACTION_REQUESTED" in [f["code"] for f in mission["risk"]["findings"]]
    assert mission["scaffold"] is None, "Arty must not run before the gate"
    assert event_types(mission["mission_id"])[:2] == ["MISSION_QUEUED", "MISSION_STARTED"]
    assert "APPROVAL_REQUIRED" in event_types(mission["mission_id"])


def test_approval_resumes_the_paused_checkpoint_and_writes_the_scaffold(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    decided = decide(monkeypatch, mission["approval"]["approval_id"], "approve")
    assert decided.status_code == 200, decided.text
    resumed = client.post(f"/missions/{mission['mission_id']}/resume", headers=key())
    assert resumed.status_code == 200, resumed.text
    final = client.get(f"/missions/{mission['mission_id']}").json()
    assert final["status"] == "completed" and final["phase"] == "DONE"
    assert final["decision"]["decision"] == "approve" and final["decision"]["decided_by"] == REVIEWER
    types = event_types(mission["mission_id"])
    for expected in ("APPROVAL_APPLIED", "TOOL_INVOKED", "MISSION_COMPLETED"):
        assert expected in types
    assert types.index("APPROVAL_REQUIRED") < types.index("APPROVAL_APPLIED") < types.index("MISSION_COMPLETED")
    workspace = Path(council["export_root"]) / "council"
    written = sorted(p.name for p in workspace.rglob("*.tsx"))
    assert written == sorted(f"{c['name']}.tsx" for c in final["scaffold"]["components"])
    audits = client.get(f"/missions/{mission['mission_id']}/tool-audits").json()["items"]
    assert [a["decision"] for a in audits] == ["ALLOWED"]
    assert "content" not in str(audits[0]["args_redacted"]).replace("content_sha256", "").replace("content_bytes", "")
    assert seat_runs(mission["mission_id"], "george") == 1, "resume must not repeat completed seats"


def test_the_author_cannot_approve_their_own_mission(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    refused = decide(monkeypatch, mission["approval"]["approval_id"], "approve", user=AUTHOR)
    assert refused.status_code == 403
    assert client.get(f"/missions/{mission['mission_id']}").json()["approval"]["status"] == "pending"


def test_rejection_is_terminal_and_arty_never_runs(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    assert decide(monkeypatch, mission["approval"]["approval_id"], "reject").status_code == 200
    assert client.post(f"/missions/{mission['mission_id']}/resume", headers=key()).status_code == 200
    final = client.get(f"/missions/{mission['mission_id']}").json()
    assert final["status"] == "rejected" and final["scaffold"] is None
    assert seat_runs(mission["mission_id"], "arty") == 0
    assert "MISSION_REJECTED" in event_types(mission["mission_id"])
    assert client.get(f"/missions/{mission['mission_id']}/tool-audits").json()["items"] == []
    assert not list((Path(council["export_root"]) / "council").rglob("*.tsx"))


def test_resume_requires_a_decision_and_cannot_be_replayed(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    early = client.post(f"/missions/{mission['mission_id']}/resume", headers=key())
    assert early.status_code == 409 and early.json()["error"]["code"] == "APPROVAL_PENDING"
    decide(monkeypatch, mission["approval"]["approval_id"], "approve")
    assert client.post(f"/missions/{mission['mission_id']}/resume", headers=key()).status_code == 200
    again = client.post(f"/missions/{mission['mission_id']}/resume", headers=key())
    assert again.status_code == 409 and again.json()["error"]["code"] == "MISSION_NOT_AWAITING_APPROVAL"
    # The consumption ledger itself refuses a second use of the same approval for the same action.
    assert not store.consume_approval(approval_id=mission["approval"]["approval_id"], mission_id=mission["mission_id"],
                                      action_hash=service.RESUME_ACTION, consumed_by="attacker")


def test_a_stale_gate_subject_is_refused(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    decide(monkeypatch, mission["approval"]["approval_id"], "approve")
    # Tamper: the checkpointed strategy changes after the reviewer approved.
    state = store.latest_checkpoint_state(mission["mission_id"])
    state["strategy"]["summary"] = "A different plan than the one that was approved."
    store.append_checkpoint(mission_id=mission["mission_id"], phase="GATE", engine="langgraph", state=state)
    refused = client.post(f"/missions/{mission['mission_id']}/resume", headers=key())
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "APPROVAL_STALE"
    assert client.get(f"/missions/{mission['mission_id']}").json()["status"] == "needs_approval"


def test_dispatch_validation_and_engine_errors_have_stable_codes(council):
    idea = create_idea(council["project_id"])
    bad = dispatch(idea["idea_id"], "unsupported_framework")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "UNSUPPORTED_ENGINE"
    assert "Unsupported orchestration engine" in bad.json()["detail"]
    missing = client.post("/missions/dispatch", json={"engine": "langgraph"}, headers=key())
    assert missing.status_code == 422
    no_key = client.post("/missions/dispatch", json={"idea_id": idea["idea_id"], "engine": "langgraph"})
    assert no_key.status_code == 422


def test_unavailable_engine_is_reported_not_faked(monkeypatch, council):
    from services.langgraph.agency.council.engines import crewai_engine

    monkeypatch.setattr(crewai_engine.CrewAIEngine, "availability", lambda self: (False, "NOT_INSTALLED: test"))
    idea = create_idea(council["project_id"])
    response = dispatch(idea["idea_id"], "crewai")
    assert response.status_code == 503 and response.json()["error"]["code"] == "ENGINE_UNAVAILABLE"


def test_dispatch_is_idempotent_per_key(council):
    idea = create_idea(council["project_id"])
    headers = key()
    first, second = dispatch(idea["idea_id"], headers=headers), dispatch(idea["idea_id"], headers=headers)
    assert first.json()["mission_id"] == second.json()["mission_id"]
    conflict = dispatch(idea["idea_id"], materialize=False, headers=headers)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    listed = client.get("/missions", params={"project_id": council["project_id"], "idea_id": idea["idea_id"]}).json()
    assert len(listed["items"]) == 1


def test_an_idea_carrying_a_credential_is_refused_before_storage(council):
    response = client.post("/missions/ideas", headers=key(), json={
        "project_id": council["project_id"], "title": "Deploy helper",
        "description": "Use api_key_ABCDEF1234567890XYZ to call the deployment service."})
    assert response.status_code == 422 and response.json()["error"]["code"] == "SECRET_IN_INPUT"


def test_spec_only_mission_completes_without_approval_or_side_effects(council):
    idea = create_idea(council["project_id"])
    mission = client.get(f"/missions/{dispatch(idea['idea_id'], materialize=False).json()['mission_id']}").json()
    assert mission["status"] == "completed" and mission["approval"] is None
    assert mission["scaffold"]["components"]
    assert client.get(f"/missions/{mission['mission_id']}/tool-audits").json()["items"] == []


def test_checkpoints_survive_a_restart_and_resume_where_they_paused(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    close_checkpointer()  # the process's checkpointer connection goes away, as on restart
    decide(monkeypatch, mission["approval"]["approval_id"], "approve")
    assert client.post(f"/missions/{mission['mission_id']}/resume", headers=key()).status_code == 200
    final = client.get(f"/missions/{mission['mission_id']}").json()
    assert final["status"] == "completed"
    assert seat_runs(mission["mission_id"], "george") == 1 and seat_runs(mission["mission_id"], "fable") == 1
    checkpoints = client.get(f"/missions/{mission['mission_id']}/checkpoints").json()
    assert checkpoints["chain_verified"] is True
    assert [c["phase"] for c in checkpoints["checkpoints"]][:3] == ["STRATEGY", "STRATEGY", "AUDIT"]
    assert any(n["interrupted"] for n in checkpoints["native"]), "the native LangGraph history shows the interrupt"


def test_failed_mission_retries_from_its_checkpoint_without_repeating_seats(monkeypatch, council):
    from services.langgraph.agency.council.engines import base

    original = base.audit_step
    calls = {"n": 0}

    def flaky_audit(ctx, state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient infrastructure failure")
        return original(ctx, state)

    monkeypatch.setattr(base, "audit_step", flaky_audit)
    from services.langgraph.agency.council.engines import langgraph_engine

    monkeypatch.setattr(langgraph_engine, "audit_step", flaky_audit)
    idea = create_idea(council["project_id"])
    mission_id = dispatch(idea["idea_id"]).json()["mission_id"]
    failed = client.get(f"/missions/{mission_id}").json()
    assert failed["status"] == "failed" and failed["last_error"] == "ENGINE_ERROR"
    retried = client.post(f"/missions/{mission_id}/retry", headers=key())
    assert retried.status_code == 200, retried.text
    assert client.get(f"/missions/{mission_id}").json()["status"] == "needs_approval"
    assert seat_runs(mission_id, "george") == 1, "George's checkpointed output is reused, not recomputed"
    assert seat_runs(mission_id, "fable") == 1, "the fault fired before Fable started; the retry ran it once"
    assert calls["n"] == 2


def test_recover_waits_for_an_expired_lease_then_continues(monkeypatch, council):
    idea = create_idea(council["project_id"])
    monkeypatch.setenv("COUNCIL_EXECUTION", "thread")
    monkeypatch.setattr(service, "submit", lambda fn: None)  # simulate a worker that died before running
    mission_id = dispatch(idea["idea_id"]).json()["mission_id"]
    row = store.acquire_lease(mission_id, "dead-worker", 300)
    blocked = client.post(f"/missions/{mission_id}/recover", headers=key())
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "MISSION_LEASE_ACTIVE"
    store.update_mission(mission_id, row["version"], lease_expires_at="2000-01-01T00:00:00+00:00")
    monkeypatch.setattr(service, "submit", lambda fn: fn())
    assert client.post(f"/missions/{mission_id}/recover", headers=key()).status_code == 200
    assert client.get(f"/missions/{mission_id}").json()["status"] == "needs_approval"


def test_cancel_retires_the_pending_approval(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    assert client.post(f"/missions/{mission['mission_id']}/cancel", headers=key()).status_code == 200
    final = client.get(f"/missions/{mission['mission_id']}").json()
    assert final["status"] == "cancelled" and final["approval"]["status"] == "stale"
    late = decide(monkeypatch, mission["approval"]["approval_id"], "approve")
    assert late.status_code == 409


def test_other_tenants_and_projects_cannot_see_or_drive_a_mission(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    as_user(monkeypatch, "intruder", "admin", tenant="tenant-intruder")
    for method, path in (("get", ""), ("get", "/timeline"), ("get", "/checkpoints"), ("post", "/resume"), ("post", "/cancel")):
        response = getattr(client, method)(f"/missions/{mission['mission_id']}{path}",
                                           **({"headers": key()} if method == "post" else {}))
        assert response.status_code == 403, (path, response.status_code)
    as_user(monkeypatch, "outsider", "admin", projects="some-other-project")
    assert client.get(f"/missions/{mission['mission_id']}").status_code == 403
    assert client.get("/missions", params={"project_id": council["project_id"]}).status_code == 403


def test_blueprint_merges_best_parts_and_promotes_after_timeline_verification(monkeypatch, council):
    idea = create_idea(council["project_id"])
    approved = client.get(f"/missions/{dispatch(idea['idea_id']).json()['mission_id']}").json()
    decide(monkeypatch, approved["approval"]["approval_id"], "approve")
    client.post(f"/missions/{approved['mission_id']}/resume", headers=key())
    rejected = client.get(f"/missions/{dispatch(idea['idea_id']).json()['mission_id']}").json()
    decide(monkeypatch, rejected["approval"]["approval_id"], "reject")
    client.post(f"/missions/{rejected['mission_id']}/resume", headers=key())

    blueprint = client.post(f"/missions/ideas/{idea['idea_id']}/blueprints", headers=key())
    assert blueprint.status_code == 201, blueprint.text
    body = blueprint.json()
    sources = {s["mission_id"]: s for s in body["sources"]}
    assert sources[approved["mission_id"]]["used_for"][:2] == ["strategy", "scaffold"]
    assert sources[rejected["mission_id"]]["excluded_reason"] == "mission rejected"
    promoted = client.post(f"/missions/blueprints/{body['blueprint_id']}/promote", headers=key())
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["status"] == "PROMOTED" and promoted.json()["verification"]["verified"] is True
    assert client.get(f"/missions/ideas/{idea['idea_id']}").json()["status"] == "PROMOTED"
    assert dispatch(idea["idea_id"]).json()["error"]["code"] == "IDEA_NOT_OPEN"


def test_promotion_refuses_a_tampered_checkpoint_chain(monkeypatch, council):
    idea = create_idea(council["project_id"])
    mission = client.get(f"/missions/{dispatch(idea['idea_id'], materialize=False).json()['mission_id']}").json()
    blueprint = client.post(f"/missions/ideas/{idea['idea_id']}/blueprints", headers=key()).json()
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('council_checkpoints')} SET state_hash = ? WHERE mission_id = ? AND seq = 1",
                   ("0" * 64, mission["mission_id"]))
    refused = client.post(f"/missions/blueprints/{blueprint['blueprint_id']}/promote", headers=key())
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "TIMELINE_VERIFICATION_FAILED"
    assert client.get(f"/missions/blueprints/{blueprint['blueprint_id']}").json()["status"] == "DRAFT"


def test_extracting_a_blueprint_needs_a_completed_mission(monkeypatch, council):
    mission = gated_mission(monkeypatch, council["project_id"])
    refused = client.post(f"/missions/ideas/{mission['idea_id']}/blueprints", headers=key())
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "NO_COMPLETED_MISSIONS"


def test_every_response_carries_a_request_id(council):
    echoed = client.get("/missions/engines", headers={"X-Request-ID": "req-test-12345"})
    assert echoed.headers["X-Request-ID"] == "req-test-12345"
    minted = client.get("/missions/engines", headers={"X-Request-ID": "bad id with spaces"})
    assert minted.headers["X-Request-ID"] != "bad id with spaces" and len(minted.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize("path", ["/missions/engines", "/missions/tools", "/missions/dispatch", "/missions/{mission_id}/resume",
                                  "/missions/{mission_id}/timeline", "/missions/{mission_id}/checkpoints"])
def test_openapi_documents_the_mission_routes(path):
    assert path in client.get("/openapi.json").json()["paths"]
