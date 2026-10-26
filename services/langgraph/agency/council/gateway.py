"""Sentinel tool gateway: the only way a council seat reaches a tool.

Deny by default. A call is refused unless, in order:

1. the tool is on the allowlist (local tools below, or MCP tools an operator
   listed in ``AMC_MCP_SERVERS``; anything else an MCP server offers is hidden);
2. the calling seat holds every scope the tool needs (least privilege);
3. the arguments validate against the tool's schema;
4. for any non-READ tool: an approval exists for this tenant and project, was
   resolved ``approve`` for this exact mission (thread), binds the mission's
   gate subject and policy version, lists this action, and has not been used
   for this action before (``council_approval_consumptions``). SHELL tools are
   disabled outright: there is no isolated executor yet.

Every attempt, allowed or not, is written to ``council_tool_audits`` with
secrets and personal data redacted and file contents reduced to a hash. Calls
run under a timeout. Tool results are untrusted data.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import council as store
from services.langgraph.security.pii import redact_value

from .contracts import POLICY_VERSION, RequestedAction, ScaffoldFile
from .policy import scan

SEAT_SCOPES: dict[str, frozenset[str]] = {
    "george": frozenset({"workspace:read", "mcp:read"}),
    "fable": frozenset({"workspace:read", "policy:scan", "mcp:read"}),
    "arty": frozenset({"workspace:read", "workspace:write", "mcp:read"}),
    # The mission service acts for an approved mission (it materializes Arty's scaffold).
    "service": frozenset({"workspace:read", "workspace:write", "policy:scan", "mcp:read", "mcp:write", "mcp:external"}),
}


class GatewayDenied(Exception):
    def __init__(self, code: str, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    provider: str  # "local" | "mcp"
    description: str
    sensitivity: str  # READ | WRITE | SHELL | EXTERNAL
    scopes: frozenset[str]
    input_schema: dict
    timeout_s: float = 10.0
    server: str | None = None
    handler: Callable[..., dict] | None = field(default=None, compare=False)
    args_model: type[BaseModel] | None = field(default=None, compare=False)

    def public(self) -> dict:
        return {"tool_id": self.tool_id, "provider": self.provider, "description": self.description,
                "sensitivity": self.sensitivity, "scopes": sorted(self.scopes), "input_schema": self.input_schema,
                "timeout_s": self.timeout_s, "requires_approval": self.sensitivity != "READ",
                "enabled": self.sensitivity != "SHELL", "server": self.server}


# ------------------------------------------------------------------------------- local tools


def mission_workspace(tenant_id: str, project_id: str, mission_id: str) -> Path:
    from services.langgraph.agency.exporter import resolve_export_root

    return Path(resolve_export_root()).resolve() / "council" / tenant_id / project_id / mission_id


def _inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise GatewayDenied("PATH_OUTSIDE_WORKSPACE", "path escapes the mission workspace")
    return target


class _ReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-./]*$")


class _ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _WriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[ScaffoldFile] = Field(min_length=1, max_length=16)


class _ScanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)


def _read_file(ctx: dict, args: _ReadArgs) -> dict:
    root = mission_workspace(ctx["tenant_id"], ctx["project_id"], ctx["mission_id"])
    target = _inside(root, args.path)
    if not target.is_file():
        raise GatewayDenied("FILE_NOT_FOUND", "no such file in the mission workspace", 404)
    data = target.read_bytes()[:64_000]
    return {"path": args.path, "content": data.decode("utf-8", errors="replace"), "bytes": len(data)}


def _list_files(ctx: dict, args: _ListArgs) -> dict:
    root = mission_workspace(ctx["tenant_id"], ctx["project_id"], ctx["mission_id"])
    if not root.is_dir():
        return {"files": []}
    return {"files": sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())[:200]}


def _write_scaffold(ctx: dict, args: _WriteArgs) -> dict:
    root = mission_workspace(ctx["tenant_id"], ctx["project_id"], ctx["mission_id"]) / "scaffold"
    written = []
    for item in args.files:
        target = _inside(root, item.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(item.content, encoding="utf-8")
        os.replace(tmp, target)  # atomic per file; rewriting identical bytes is idempotent
        written.append({"path": f"scaffold/{item.path}", "sha256": hashlib.sha256(item.content.encode()).hexdigest()})
    return {"written": written}


def _scan_text(ctx: dict, args: _ScanArgs) -> dict:
    result = scan(args.text, [])
    return {"level": result.level, "findings": [f.code for f in result.findings]}


def _local(tool_id: str, description: str, sensitivity: str, scopes: set[str], model: type[BaseModel], handler) -> ToolSpec:
    return ToolSpec(tool_id=tool_id, provider="local", description=description, sensitivity=sensitivity,
                    scopes=frozenset(scopes), input_schema=model.model_json_schema(), handler=handler, args_model=model)


LOCAL_TOOLS = {
    spec.tool_id: spec for spec in (
        _local("workspace.list_files", "List files in this mission's workspace.", "READ", {"workspace:read"}, _ListArgs,
               _list_files),
        _local("workspace.read_file", "Read a text file from this mission's workspace.", "READ", {"workspace:read"},
               _ReadArgs, _read_file),
        _local("workspace.write_scaffold", "Write Arty's validated scaffold files into this mission's workspace.", "WRITE",
               {"workspace:write"}, _WriteArgs, _write_scaffold),
        _local("policy.scan_text", "Run the deterministic Sentinel policy scan on text.", "READ", {"policy:scan"},
               _ScanArgs, _scan_text),
    )
}


# ---------------------------------------------------------------------------------- registry


def registry(*, include_mcp: bool = True) -> dict[str, ToolSpec]:
    tools = dict(LOCAL_TOOLS)
    if include_mcp:
        from .mcp_client import mcp_tools

        tools.update(mcp_tools())
    return tools


def action_target(tool_id: str, mission_id: str) -> str:
    """The target an approval names for a tool. Derived server-side, never taken from the caller."""
    return f"council/{mission_id}/scaffold/" if tool_id == "workspace.write_scaffold" else tool_id


def requested_action(tool_id: str, mission_id: str) -> dict:
    spec = registry().get(tool_id)
    if spec is None:
        raise GatewayDenied("TOOL_NOT_ALLOWLISTED", f"{tool_id} is not on the tool allowlist")
    return RequestedAction(tool_id=tool_id, sensitivity=spec.sensitivity,
                           target=action_target(tool_id, mission_id)).model_dump()


def action_hash(mission_id: str, tool_id: str, args: dict) -> str:
    return canonical_hash({"mission_id": mission_id, "tool_id": tool_id, "args": args})


def _redacted_args(args: dict) -> dict:
    """Redact secrets/PII; never store file contents in the audit log, only their hash and size."""
    clean = json.loads(json.dumps(args, default=str))
    for item in clean.get("files", []) if isinstance(clean.get("files"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("content"), str):
            body = item.pop("content")
            item["content_sha256"] = hashlib.sha256(body.encode()).hexdigest()
            item["content_bytes"] = len(body.encode())
    return redact_value(clean)


def _check_approval(*, ctx: dict, mission: dict | None, spec: ToolSpec, args: dict, approval_id: str | None) -> str:
    """Return the action hash once every binding holds; raise GatewayDenied otherwise."""
    from services.langgraph.persistence.approvals import get_approval

    if not approval_id:
        raise GatewayDenied("APPROVAL_REQUIRED", f"{spec.tool_id} is {spec.sensitivity}; it needs a human approval")
    if mission is None:
        raise GatewayDenied("APPROVAL_SCOPE_INVALID", "sensitive tools run only for a mission")
    approval = get_approval(approval_id)
    if approval is None:
        raise GatewayDenied("APPROVAL_NOT_FOUND", "approval does not exist", 404)
    if approval["tenant_id"] != ctx["tenant_id"] or approval["project_id"] != ctx["project_id"]:
        raise GatewayDenied("APPROVAL_SCOPE_INVALID", "approval belongs to another tenant or project")
    if approval["run_id"] != mission["mission_id"]:
        raise GatewayDenied("APPROVAL_SCOPE_INVALID", "approval was granted for a different mission")
    if approval.get("status") != "resolved" or approval.get("decision") != "approve":
        raise GatewayDenied("APPROVAL_NOT_GRANTED", "approval is not resolved as approve")
    if not mission.get("approval_subject_hash") or approval.get("subject_hash") != mission["approval_subject_hash"]:
        raise GatewayDenied("APPROVAL_SUBJECT_MISMATCH", "approval does not bind this mission's gate subject")
    if approval.get("policy_version") != POLICY_VERSION:
        raise GatewayDenied("APPROVAL_POLICY_MISMATCH", "approval was decided under a different policy version")
    approved = {(a["tool_id"], a["target"]) for a in (mission.get("requested_actions") or [])}
    if (spec.tool_id, action_target(spec.tool_id, mission["mission_id"])) not in approved:
        raise GatewayDenied("ACTION_NOT_APPROVED", "this action is not among the approved requested actions")
    return action_hash(mission["mission_id"], spec.tool_id, args)


def invoke(tool_id: str, args: dict, *, ctx: dict, seat: str, mission: dict | None = None,
           approval_id: str | None = None, idempotent_retry: bool = False) -> dict:
    """Run one allowlisted tool call for ``ctx`` = {tenant_id, project_id, mission_id, user_id}."""
    started = time.monotonic()
    tools = registry()
    spec = tools.get(tool_id)
    audit = {"tenant_id": ctx["tenant_id"], "project_id": ctx["project_id"], "mission_id": ctx.get("mission_id"),
             "seat": seat, "tool_id": tool_id, "args_redacted": _redacted_args(args),
             "args_hash": canonical_hash(args), "approval_id": approval_id}

    def deny(code: str, message: str, status: int = 403, sensitivity: str = "UNKNOWN") -> GatewayDenied:
        store.record_tool_audit(**audit, sensitivity=sensitivity, decision="DENIED", reason_code=code,
                                duration_ms=int((time.monotonic() - started) * 1000))
        return GatewayDenied(code, message, status)

    if spec is None:
        raise deny("TOOL_NOT_ALLOWLISTED", f"{tool_id} is not on the tool allowlist")
    if spec.sensitivity == "SHELL":
        raise deny("SHELL_DISABLED", "shell execution is disabled until an isolated executor exists",
                   sensitivity=spec.sensitivity)
    missing = spec.scopes - SEAT_SCOPES.get(seat, frozenset())
    if missing:
        raise deny("SCOPE_NOT_GRANTED", f"seat {seat} lacks scopes {sorted(missing)}", sensitivity=spec.sensitivity)
    try:
        parsed = spec.args_model.model_validate(args) if spec.args_model else _validate_json_schema(spec, args)
    except (ValidationError, ValueError) as exc:
        raise deny("SCHEMA_INVALID", f"arguments do not match the tool schema: {str(exc)[:200]}", 422,
                   spec.sensitivity) from exc
    hashed = None
    if spec.sensitivity != "READ":
        try:
            hashed = _check_approval(ctx=ctx, mission=mission, spec=spec, args=args, approval_id=approval_id)
        except GatewayDenied as exc:
            raise deny(exc.code, str(exc), exc.status, spec.sensitivity) from exc
        audit["action_hash"] = hashed
        first = store.consume_approval(approval_id=approval_id, mission_id=mission["mission_id"], action_hash=hashed,
                                       consumed_by=ctx.get("user_id") or "service")
        if not first and not idempotent_retry:
            raise deny("APPROVAL_REPLAY", "this approval was already used for this action", 409, spec.sensitivity)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="sentinel-tool")
    try:
        if spec.provider == "local":
            future = pool.submit(spec.handler, ctx, parsed)
        else:
            from .mcp_client import call_mcp_tool

            future = pool.submit(call_mcp_tool, spec, args)
        result = future.result(timeout=spec.timeout_s)
    except concurrent.futures.TimeoutError:
        store.record_tool_audit(**audit, sensitivity=spec.sensitivity, decision="TIMEOUT", reason_code="TOOL_TIMEOUT",
                                duration_ms=int((time.monotonic() - started) * 1000))
        raise GatewayDenied("TOOL_TIMEOUT", f"{tool_id} exceeded {spec.timeout_s}s", 504) from None
    except GatewayDenied as exc:
        store.record_tool_audit(**audit, sensitivity=spec.sensitivity, decision="FAILED", reason_code=exc.code,
                                duration_ms=int((time.monotonic() - started) * 1000))
        raise
    except Exception as exc:
        store.record_tool_audit(**audit, sensitivity=spec.sensitivity, decision="FAILED", reason_code="TOOL_FAILED",
                                result_summary=type(exc).__name__, duration_ms=int((time.monotonic() - started) * 1000))
        raise GatewayDenied("TOOL_FAILED", f"{tool_id} failed: {type(exc).__name__}", 502) from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    store.record_tool_audit(**audit, sensitivity=spec.sensitivity, decision="ALLOWED", reason_code="OK",
                            result_summary=json.dumps(redact_value(result), default=str)[:500],
                            duration_ms=int((time.monotonic() - started) * 1000))
    return {"tool_id": tool_id, "result": redact_value(result), "action_hash": hashed}


def _validate_json_schema(spec: ToolSpec, args: dict) -> dict:
    try:
        import jsonschema
    except ImportError as exc:  # MCP tools are only listed when the mcp extra (which ships jsonschema) is installed
        raise ValueError("jsonschema unavailable; MCP tool arguments cannot be validated") from exc
    jsonschema.validate(args, spec.input_schema)
    return args


__all__ = ["LOCAL_TOOLS", "SEAT_SCOPES", "GatewayDenied", "ToolSpec", "action_hash", "action_target", "invoke",
           "mission_workspace", "registry", "requested_action"]
