"""The three supplied scenario suites, ported from self-contained mocks to the real implementation.

The originals (test_missions_router.py, test_crewai_engine.py, test_e2e_mcos_idea_flow.py) defined
their own FastAPI app, CrewAI stand-ins and engine mocks, so they only tested themselves. Each test
below keeps the original scenario and assertion intent, against the real routes and engines:

* ``/api/missions/approve {thread_id, approved}`` becomes the governed pair: decide the bound approval
  at ``/approvals/{id}/decide`` as a different user, then ``/missions/{id}/resume``;
* "resumed_and_completed" is ``completed``; "aborted_by_user"/"aborted_by_sentinel" is ``rejected``;
* the e2e "simulated Sentinel approval" is a real reviewer decision (no approval is fabricated).
"""

from __future__ import annotations

import concurrent.futures

import pytest

from services.langgraph.agency.council.engines import get_engine
from services.langgraph.tests.council_support import (
    client,
    council,  # noqa: F401 - fixture
    create_idea,
    decide,
    dispatch,
    key,
)

# --------------------------------------------------------------- test_missions_router.py, ported


def test_dispatch_mission_langgraph_engine(council):
    idea = create_idea(council["project_id"], title="Deployment pipeline", description="Create an automated deployment pipeline.")
    response = dispatch(idea["idea_id"], "langgraph")
    assert response.status_code == 202
    data = client.get(f"/missions/{response.json()['mission_id']}").json()
    assert data["engine"] == "langgraph" and data["idea_id"] == idea["idea_id"]
    assert data["status"] == "needs_approval"  # requires_approval: paused at the Sentinel gate
    assert data["risk"]["requires_approval"] is True


def test_dispatch_mission_crewai_engine(council):
    idea = create_idea(council["project_id"], title="Design tokens", description="Synthesize design system tokens.")
    response = dispatch(idea["idea_id"], "crewai", materialize=False)
    if not get_engine("crewai").availability()[0]:
        assert response.status_code == 503 and response.json()["error"]["code"] == "ENGINE_UNAVAILABLE"
        return
    data = client.get(f"/missions/{response.json()['mission_id']}").json()
    assert data["status"] == "completed" and data["engine"] == "crewai"
    assert data["results"]["arty"]["engine"] == "crewai"


def test_dispatch_mission_invalid_engine(council):
    idea = create_idea(council["project_id"])
    response = dispatch(idea["idea_id"], "unsupported_framework")
    assert response.status_code == 400
    assert "Unsupported orchestration engine" in response.json()["detail"]


def test_dispatch_mission_validation_error(council):
    response = client.post("/missions/dispatch", json={"engine": "langgraph"}, headers=key())
    assert response.status_code == 422


def test_approve_sentinel_gate_endpoint(monkeypatch, council):
    idea = create_idea(council["project_id"])
    mission = client.get(f"/missions/{dispatch(idea['idea_id']).json()['mission_id']}").json()
    assert decide(monkeypatch, mission["approval"]["approval_id"], "approve").status_code == 200
    resumed = client.post(f"/missions/{mission['thread_id']}/resume", headers=key())
    assert resumed.status_code == 200
    data = client.get(f"/missions/{mission['thread_id']}").json()
    assert data["thread_id"] == mission["mission_id"]
    assert data["decision"]["decision"] == "approve" and data["status"] == "completed"


def test_approve_sentinel_gate_rejection(monkeypatch, council):
    idea = create_idea(council["project_id"])
    mission = client.get(f"/missions/{dispatch(idea['idea_id']).json()['mission_id']}").json()
    decide(monkeypatch, mission["approval"]["approval_id"], "reject")
    client.post(f"/missions/{mission['thread_id']}/resume", headers=key())
    data = client.get(f"/missions/{mission['thread_id']}").json()
    assert data["decision"]["decision"] == "reject" and data["status"] == "rejected"


# ----------------------------------------------------------------- test_crewai_engine.py, ported


def test_crewai_council_agents_and_task_delegation():
    pytest.importorskip("crewai")
    from services.langgraph.agency.council.engines.crewai_engine import (
        build_council_crew,
    )

    crew = build_council_crew("Dashboard Feature", "Build real-time agent metrics widget.")
    assert len(crew.agents) == 3
    agents = {agent.role: agent for agent in crew.agents}
    commander = agents["George - Mission Commander"]
    sentinel = agents["Fable/Cipher - Sentinel Guard"]
    maker = agents["Arty - Product Maker"]
    assert commander.allow_delegation, "George (Commander) must be allowed to delegate."
    assert not sentinel.allow_delegation, "Fable/Cipher (Sentinel) must NOT delegate security audits."
    assert len(crew.tasks) == 3
    t_strategy, t_audit, t_prototype = crew.tasks
    assert (t_strategy.agent, t_audit.agent, t_prototype.agent) == (commander, sentinel, maker)
    assert t_audit.context == [t_strategy], "Audit task must depend on Strategy output."
    assert t_prototype.context == [t_strategy, t_audit], "Prototype task must depend on Strategy & Audit outputs."


def test_run_mcos_crew_execution():
    pytest.importorskip("crewai")
    from services.langgraph.agency.council.engines.crewai_engine import run_council_crew

    output = run_council_crew("Agent Metrics Widget", "Real-time metrics for council activity.")
    assert len(output) > 0 and '"components"' in output  # the prototype task's validated scaffold JSON


# ------------------------------------------------------------ test_e2e_mcos_idea_flow.py, ported


def test_full_idea_promotion_flow_simultaneous(monkeypatch, council):
    engines = [e for e in ("langgraph", "crewai", "autogen") if get_engine(e).availability()[0]]
    idea = create_idea(council["project_id"], title="Real-time Agent Council Analytics Dashboard",
                       description="Design a multi-agent dashboard with Framer Motion timelines and Sentinel approval modals.")
    # Step 1: dispatch the idea to every available engine at once.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda e: dispatch(idea["idea_id"], e), engines))
    missions = [client.get(f"/missions/{r.json()['mission_id']}").json() for r in responses]
    # Step 2: every engine stopped at the Sentinel gate.
    assert all(m["status"] == "needs_approval" for m in missions), [m["status"] for m in missions]
    # Step 3: a reviewer (not the author) approves each gate; each mission resumes its own checkpoint.
    for mission in missions:
        assert decide(monkeypatch, mission["approval"]["approval_id"], "approve").status_code == 200
        assert client.post(f"/missions/{mission['mission_id']}/resume", headers=key()).status_code == 200
    finals = [client.get(f"/missions/{m['mission_id']}").json() for m in missions]
    assert all(f["status"] == "completed" and f["scaffold"]["components"] for f in finals)
    # Step 4: merge the best parts into a blueprint and promote it.
    blueprint = client.post(f"/missions/ideas/{idea['idea_id']}/blueprints", headers=key()).json()
    assert {s["engine"] for s in blueprint["sources"]} == set(engines)
    assert all(a["decision"] == "approve" for a in blueprint["content"]["security"]["approvals"])
    promoted = client.post(f"/missions/blueprints/{blueprint['blueprint_id']}/promote", headers=key()).json()
    assert promoted["status"] == "PROMOTED" and promoted["verification"]["verified"] is True
    assert client.get(f"/missions/ideas/{idea['idea_id']}").json()["status"] == "PROMOTED"


def test_idea_promotion_rejection_flow(monkeypatch, council):
    idea = create_idea(council["project_id"], title="Danger", description="Run unauthorized root script on the build host.")
    mission = client.get(f"/missions/{dispatch(idea['idea_id']).json()['mission_id']}").json()
    assert mission["status"] == "needs_approval"
    decide(monkeypatch, mission["approval"]["approval_id"], "reject")
    client.post(f"/missions/{mission['mission_id']}/resume", headers=key())
    rejected = client.get(f"/missions/{mission['mission_id']}").json()
    assert rejected["status"] == "rejected" and rejected["decision"]["decision"] == "reject"
    assert rejected["scaffold"] is None
