"""Sentinel tool gateway: allowlist, scopes, schemas, approval binding, replay, redaction, timeouts, MCP failures."""

from __future__ import annotations

import json
import sys
import time
import tempfile
from pathlib import Path

import pytest

from services.langgraph.agency.council import gateway
from services.langgraph.agency.council.gateway import GatewayDenied, invoke
from services.langgraph.persistence import council as store
from services.langgraph.tests.council_support import (
    client,
    council,  # noqa: F401 - fixture
    decide,
    gated_mission,
    isolated_python,
    key,
)


def _ctx(mission: dict) -> dict:
    return {"tenant_id": mission["tenant_id"], "project_id": mission["project_id"], "mission_id": mission["mission_id"],
            "user_id": "tester"}


def _view(mission: dict) -> dict:
    row = store.get_mission_row(mission["mission_id"])
    return {"mission_id": mission["mission_id"], "requested_actions": mission["requested_actions"],
            "approval_subject_hash": row["approval_subject_hash"]}


def _files() -> dict:
    return {"files": [{"path": "components/Probe.tsx", "content": "export const Probe = () => null;\n"}]}


def _denied(fn) -> GatewayDenied:
    with pytest.raises(GatewayDenied) as caught:
        fn()
    return caught.value


def _audit_codes(mission_id: str) -> list[tuple[str, str]]:
    return [(a["decision"], a["reason_code"]) for a in store.list_tool_audits(mission_id)]


def test_unknown_tools_are_denied_and_audited(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    error = _denied(lambda: invoke("os.system", {}, ctx=_ctx(mission), seat="arty"))
    assert error.code == "TOOL_NOT_ALLOWLISTED"
    assert _audit_codes(mission["mission_id"]) == [("DENIED", "TOOL_NOT_ALLOWLISTED")]


def test_least_privilege_scopes(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    error = _denied(lambda: invoke("workspace.write_scaffold", _files(), ctx=_ctx(mission), seat="george"))
    assert error.code == "SCOPE_NOT_GRANTED"


def test_arguments_are_schema_validated_and_paths_bounded(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    bad = {"files": [{"path": "../../etc/passwd.md", "content": "x"}]}
    assert _denied(lambda: invoke("workspace.write_scaffold", bad, ctx=_ctx(mission), seat="arty")).code == "SCHEMA_INVALID"
    assert _denied(lambda: invoke("workspace.read_file", {"path": "x", "extra": 1}, ctx=_ctx(mission),
                                  seat="george")).code == "SCHEMA_INVALID"
    traversal = _denied(lambda: invoke("workspace.read_file", {"path": "scaffold/../../../../secrets.md"}, ctx=_ctx(mission),
                                       seat="george"))
    assert traversal.code == "PATH_OUTSIDE_WORKSPACE"


def test_writes_need_an_approval_bound_to_this_mission(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    other = gated_mission(monkeypatch, council["project_id"])
    view = _view(mission)
    assert _denied(lambda: invoke("workspace.write_scaffold", _files(), ctx=_ctx(mission), seat="arty",
                                  mission=view)).code == "APPROVAL_REQUIRED"
    pending = mission["approval"]["approval_id"]
    assert _denied(lambda: invoke("workspace.write_scaffold", _files(), ctx=_ctx(mission), seat="arty", mission=view,
                                  approval_id=pending)).code == "APPROVAL_NOT_GRANTED"
    decide(monkeypatch, other["approval"]["approval_id"], "approve")
    foreign = _denied(lambda: invoke("workspace.write_scaffold", _files(), ctx=_ctx(mission), seat="arty", mission=view,
                                     approval_id=other["approval"]["approval_id"]))
    assert foreign.code == "APPROVAL_SCOPE_INVALID"


def test_an_approval_is_used_once_per_action_and_replays_are_refused(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    decide(monkeypatch, mission["approval"]["approval_id"], "approve")
    approval_id = mission["approval"]["approval_id"]
    first = invoke("workspace.write_scaffold", _files(), ctx=_ctx(mission), seat="arty", mission=_view(mission),
                   approval_id=approval_id)
    assert first["result"]["written"][0]["path"] == "scaffold/components/Probe.tsx"
    replay = _denied(lambda: invoke("workspace.write_scaffold", _files(), ctx=_ctx(mission), seat="arty",
                                    mission=_view(mission), approval_id=approval_id))
    assert replay.code == "APPROVAL_REPLAY"
    tampered = {**_view(mission), "approval_subject_hash": "0" * 64}
    mismatch = _denied(lambda: invoke("workspace.write_scaffold", {"files": [{"path": "x.md", "content": "y"}]},
                                      ctx=_ctx(mission), seat="arty", mission=tampered, approval_id=approval_id))
    assert mismatch.code == "APPROVAL_SUBJECT_MISMATCH"
    assert ("ALLOWED", "OK") in _audit_codes(mission["mission_id"])
    assert ("DENIED", "APPROVAL_REPLAY") in _audit_codes(mission["mission_id"])


def test_audit_log_redacts_secrets_and_never_stores_file_bodies(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    invoke("policy.scan_text", {"text": "contact me at someone@example.com with token api_key_ABCDEF1234567890XYZ"},
           ctx=_ctx(mission), seat="fable")
    decide(monkeypatch, mission["approval"]["approval_id"], "approve")
    invoke("workspace.write_scaffold", _files(), ctx=_ctx(mission), seat="arty", mission=_view(mission),
           approval_id=mission["approval"]["approval_id"])
    stored = json.dumps(store.list_tool_audits(mission["mission_id"]))
    assert "someone@example.com" not in stored and "api_key_ABCDEF1234567890XYZ" not in stored
    assert "export const Probe" not in stored and "content_sha256" in stored


def test_slow_tools_time_out(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    spec = gateway.LOCAL_TOOLS["workspace.list_files"]
    slow = gateway.ToolSpec(**{**spec.__dict__, "timeout_s": 0.2,
                               "handler": lambda ctx, args: time.sleep(1) or {"files": []}})
    monkeypatch.setitem(gateway.LOCAL_TOOLS, "workspace.list_files", slow)
    error = _denied(lambda: invoke("workspace.list_files", {}, ctx=_ctx(mission), seat="george"))
    assert error.code == "TOOL_TIMEOUT"
    assert ("TIMEOUT", "TOOL_TIMEOUT") in _audit_codes(mission["mission_id"])


# ------------------------------------------------------------------------------------- MCP

SERVER = Path(__file__).parent / "fixtures" / "council_mcp_server.py"
# A pinned file that exists but cannot be executed, so spawning it fails with an OS error.
_NON_EXECUTABLE = Path(tempfile.mkstemp(prefix="amc-mcp-nonexec-")[1])
_NON_EXECUTABLE.write_text("not a program\n")
_NON_EXECUTABLE.chmod(0o644)


@pytest.fixture
def mcp_server(monkeypatch, council, tmp_path):  # after ``council``, which clears AMC_MCP_SERVERS  # noqa: F811
    pytest.importorskip("mcp")
    pytest.importorskip("jsonschema")
    from services.langgraph.agency.council.mcp_client import file_sha256
    interpreter = isolated_python(tmp_path)
    monkeypatch.setenv("AMC_MCP_SERVERS", json.dumps({"testsrv": {
        "command": interpreter, "args": ["-I", str(SERVER)],
        "pins": {interpreter: file_sha256(interpreter), str(SERVER): file_sha256(str(SERVER))},
        "tools": {"echo": {"sensitivity": "READ"}, "fail": {"sensitivity": "READ"},
                  "slow": {"sensitivity": "READ", "timeout_s": 1}, "run_shell": {"sensitivity": "SHELL"},
                  "absent": {"sensitivity": "READ"}}},
        "broken": {"command": str(_NON_EXECUTABLE), "tools": {"ping": {"sensitivity": "READ"}},
                   "pins": {str(_NON_EXECUTABLE): file_sha256(str(_NON_EXECUTABLE))}},
        "relative": {"command": "python", "tools": {"x": {"sensitivity": "READ"}}}}))


def test_mcp_tools_are_allowlisted_only(mcp_server, council):  # noqa: F811
    body = client.get("/missions/tools").json()
    ids = {t["tool_id"] for t in body["tools"]}
    # Surface the operator-facing refusal reason on failure. Without this the only
    # signal is "testsrv is missing from the allowlist", which does not say why the
    # configuration was rejected.
    assert {"mcp.testsrv.echo", "mcp.testsrv.run_shell"} <= ids, body["mcp_config_errors"]
    assert "mcp.testsrv.hidden_admin" not in ids
    assert any("relative: command must be an absolute path" in e for e in body["mcp_config_errors"])


def test_mcp_server_without_pins_is_refused_at_configuration(monkeypatch, council):  # noqa: F811
    from services.langgraph.agency.council import mcp_client
    monkeypatch.setenv("AMC_MCP_SERVERS", json.dumps({"x": {"command": "/bin/true", "tools": {"y": {"sensitivity": "READ"}}}}))
    servers, errors = mcp_client.configured_servers()
    assert "x" not in servers
    assert any(e.startswith("x: no pins") for e in errors)


def _tampered_server(monkeypatch, tmp_path, mcp_client):
    marker = tmp_path / "tampered-ran"
    copy = tmp_path / "server.py"
    copy.write_text(SERVER.read_text())
    interpreter = isolated_python(tmp_path)
    monkeypatch.setenv("AMC_MCP_SERVERS", json.dumps({"tampered": {
        "command": interpreter, "args": ["-I", str(copy)],
        "pins": {interpreter: mcp_client.file_sha256(interpreter), str(copy): mcp_client.file_sha256(str(copy))},
        "tools": {"echo": {"sensitivity": "READ"}}}}))
    servers, errors = mcp_client.configured_servers()
    assert "tampered" in servers and not errors
    spec = mcp_client.mcp_tools()["mcp.tampered.echo"]
    # Change the file after the tool was listed. Only the spawn-time check can catch this.
    copy.write_text(f"open({str(marker)!r}, 'w').close()\n" + copy.read_text())
    return spec, marker


def test_mcp_server_changed_after_listing_is_refused_at_spawn(monkeypatch, tmp_path, council):  # noqa: F811
    pytest.importorskip("mcp")
    from services.langgraph.agency.council import mcp_client
    spec, marker = _tampered_server(monkeypatch, tmp_path, mcp_client)
    # Configuration is re-read at call time, so the tampered server is no longer configured. The refusal
    # must come before any process starts. The pin check in ``_call`` covers the window in between.
    with pytest.raises(GatewayDenied) as exc:
        mcp_client.call_mcp_tool(spec, {"text": "x"})
    assert exc.value.code in {"MCP_PIN_MISMATCH", "MCP_SERVER_NOT_CONFIGURED"}
    assert not marker.exists(), "the tampered server must never start"


def test_mcp_tampered_server_is_dropped_from_the_registry(monkeypatch, tmp_path, council):  # noqa: F811
    pytest.importorskip("mcp")
    from services.langgraph.agency.council import mcp_client
    _, marker = _tampered_server(monkeypatch, tmp_path, mcp_client)
    mission = gated_mission(monkeypatch, council["project_id"])
    denied = _denied(lambda: invoke("mcp.tampered.echo", {"text": "x"}, ctx=_ctx(mission), seat="george"))
    assert denied.code == "TOOL_NOT_ALLOWLISTED"
    assert not marker.exists()

def test_mcp_call_round_trips_through_a_real_server(mcp_server, monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    result = invoke("mcp.testsrv.echo", {"text": "hello council"}, ctx=_ctx(mission), seat="george")
    assert result["result"]["content"] == ["hello council"]


def test_mcp_failures_are_typed_and_audited(mcp_server, monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    cases = [
        ("mcp.testsrv.echo", {"text": 42}, "SCHEMA_INVALID"),
        ("mcp.testsrv.fail", {}, "MCP_TOOL_ERROR"),
        ("mcp.testsrv.slow", {"seconds": 5}, "TOOL_TIMEOUT"),
        ("mcp.testsrv.absent", {}, "MCP_TOOL_MISSING"),
        ("mcp.broken.ping", {}, "MCP_SERVER_UNAVAILABLE"),
        ("mcp.testsrv.run_shell", {"command": "rm -rf /"}, "SHELL_DISABLED"),
    ]
    for tool_id, args, code in cases:
        assert _denied(lambda t=tool_id, a=args: invoke(t, a, ctx=_ctx(mission), seat="george")).code == code, tool_id
    decisions = {code for _, code in _audit_codes(mission["mission_id"])}
    assert {"SCHEMA_INVALID", "MCP_TOOL_ERROR", "TOOL_TIMEOUT", "SHELL_DISABLED"} <= decisions


def test_tools_endpoint_reports_mcp_absence_honestly(monkeypatch, council):  # noqa: F811
    from services.langgraph.agency.council import mcp_client
    from services.langgraph.api.routes import missions

    monkeypatch.setattr(mcp_client, "mcp_installed", lambda: False)
    monkeypatch.setattr(missions, "mcp_installed", lambda: False)
    monkeypatch.setenv("AMC_MCP_SERVERS", json.dumps({"x": {"command": "/bin/true", "tools": {"y": {"sensitivity": "READ"}}}}))
    body = client.get("/missions/tools").json()
    assert body["mcp_installed"] is False
    assert not any(t["provider"] == "mcp" for t in body["tools"])
    assert client.get("/missions/engines", headers=key()).status_code == 200
