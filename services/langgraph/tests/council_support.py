"""Shared helpers for the mission council tests: principals, idea/mission setup, approval decisions."""

from __future__ import annotations

import shlex
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.app.main import app

TENANT = "tenant-events-test"
AUTHOR = "council-author"
REVIEWER = "council-reviewer"

client = TestClient(app)


def as_user(monkeypatch, user: str, role: str = "operator", tenant: str = TENANT, projects: str = "*") -> None:
    monkeypatch.setenv("AMC_LOCAL_USER_ID", user)
    monkeypatch.setenv("AMC_LOCAL_ROLE", role)
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", tenant)
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", projects)


def key() -> dict:
    return {"Idempotency-Key": str(uuid4())}


@pytest.fixture
def council(monkeypatch, tmp_path):
    """Inline execution, mock model, separation of duties enforced, exports in a temp dir."""
    monkeypatch.setenv("COUNCIL_EXECUTION", "inline")
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    for name in ("ENABLE_REAL_MODELS", "DEFAULT_MODEL_PROVIDER", "AMC_MCP_SERVERS", "AMC_ALLOW_SELF_APPROVAL"):
        monkeypatch.delenv(name, raising=False)
    as_user(monkeypatch, AUTHOR)
    return {"project_id": f"proj-council-{uuid4().hex[:10]}", "export_root": tmp_path}


def create_idea(project_id: str, *, title: str = "Agent metrics widget",
                description: str = "Real-time metrics for council activity. Show a dashboard timeline.") -> dict:
    response = client.post("/missions/ideas", json={"project_id": project_id, "title": title, "description": description},
                           headers=key())
    assert response.status_code == 201, response.text
    return response.json()


def dispatch(idea_id: str, engine: str = "langgraph", materialize: bool = True, headers: dict | None = None):
    return client.post("/missions/dispatch", json={"idea_id": idea_id, "engine": engine, "materialize_scaffold": materialize},
                       headers=headers or key())


def decide(monkeypatch, approval_id: str, decision: str, *, user: str = REVIEWER, role: str = "reviewer"):
    as_user(monkeypatch, user, role)
    response = client.post(f"/approvals/{approval_id}/decide", json={"decision": decision}, headers=key())
    as_user(monkeypatch, AUTHOR)
    return response


def events(mission_id: str) -> list[dict]:
    return client.get(f"/missions/{mission_id}/timeline", params={"limit": 500}).json()["events"]


def event_types(mission_id: str) -> list[str]:
    return [e["event_type"] for e in events(mission_id)]


def seat_runs(mission_id: str, seat: str) -> int:
    return sum(1 for e in events(mission_id) if e["event_type"] == "SEAT_STARTED" and e["node_id"] == seat)


def gated_mission(monkeypatch, project_id: str, engine: str = "langgraph") -> dict:
    idea = create_idea(project_id)
    response = dispatch(idea["idea_id"], engine)
    assert response.status_code == 202, response.text
    mission = client.get(f"/missions/{response.json()['mission_id']}").json()
    assert mission["status"] == "needs_approval", mission
    return mission


def isolated_python(tmp_path) -> str:
    """A private launcher for the running interpreter, safe to pin as an MCP command.

    ``mcp_client`` refuses to start a server whose command is group- or world-writable,
    because a writable interpreter cannot be trusted to still be the file that was
    pinned. The interpreter a hosted CI runner supplies does not meet that bar --
    GitHub's ``/opt/hostedtoolcache/.../bin/python`` is writable -- so a fixture that
    pins ``sys.executable`` is admitted locally and rejected on CI, which is why these
    MCP tests failed only on the runner.

    The launcher lives in a ``0700`` directory and is a short script that execs this
    exact interpreter, so:

    * the pinned file is not writable by anyone else;
    * the server still runs with this interpreter's own environment and packages,
      which a copied binary would lose;
    * it is byte-identical for the same interpreter path, so pinning is stable.

    Skipping when the interpreter is writable would drop the MCP coverage on exactly
    the machines that need it, so the launch is made valid rather than skipped.
    """
    import os
    import stat
    import sys
    from pathlib import Path

    if not (os.stat(sys.executable).st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        return sys.executable

    private = Path(tmp_path) / "mcp-interpreter"
    private.mkdir(mode=0o700, exist_ok=True)
    os.chmod(private, 0o700)
    target = private / "python"
    target.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
    os.chmod(target, 0o755)
    if os.stat(target).st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError(f"could not create a private launcher for {sys.executable}")
    return str(target)
