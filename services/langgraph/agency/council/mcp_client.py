"""Allowlisted MCP client for the Sentinel gateway (stdio transport, official ``mcp`` SDK).

Servers and the tools exposed from each are declared by the operator in
``AMC_MCP_SERVERS`` (JSON). Nothing else a server offers is reachable::

    {"docs": {"command": "/usr/bin/python3", "args": ["-I", "/opt/mcp/docs_server.py"],
              "tools": {"search": {"sensitivity": "READ", "scopes": ["mcp:read"], "timeout_s": 10}}}}

The server process gets a minimal environment (no credentials are passed
through), its declared input schema is enforced before a call, and errors,
timeouts and unavailable servers become typed gateway errors. Requires the
``council`` extra; without it no MCP tool is listed.
"""

from __future__ import annotations

import asyncio
import builtins
import importlib.util
import json
import os
from datetime import timedelta
from pathlib import Path

from .gateway import GatewayDenied, ToolSpec

SENSITIVITIES = {"READ", "WRITE", "EXTERNAL", "SHELL"}
_SAFE_ENV = ("PATH", "LANG", "LC_ALL")


def mcp_installed() -> bool:
    return importlib.util.find_spec("mcp") is not None


def configured_servers() -> tuple[dict[str, dict], list[str]]:
    """Valid server entries and the reasons any entries were rejected (fail closed)."""
    raw = (os.environ.get("AMC_MCP_SERVERS") or "").strip()
    if not raw:
        return {}, []
    try:
        data = json.loads(raw)
    except ValueError:
        return {}, ["AMC_MCP_SERVERS is not valid JSON"]
    if not isinstance(data, dict):
        return {}, ["AMC_MCP_SERVERS must be an object"]
    valid, errors = {}, []
    for name, entry in data.items():
        if not isinstance(entry, dict) or not str(name).isidentifier():
            errors.append(f"{name}: invalid entry")
            continue
        command = str(entry.get("command") or "")
        tools = entry.get("tools") or {}
        if not Path(command).is_absolute():
            errors.append(f"{name}: command must be an absolute path")
            continue
        if not isinstance(tools, dict) or not tools:
            errors.append(f"{name}: no tools allowlisted")
            continue
        bad = [t for t, spec in tools.items() if not isinstance(spec, dict) or spec.get("sensitivity") not in SENSITIVITIES]
        if bad:
            errors.append(f"{name}: tools {bad} need a sensitivity in {sorted(SENSITIVITIES)}")
            continue
        valid[name] = {"command": command, "args": [str(a) for a in entry.get("args") or []], "tools": tools}
    return valid, errors


def mcp_tools() -> dict[str, ToolSpec]:
    if not mcp_installed():
        return {}
    servers, _ = configured_servers()
    out: dict[str, ToolSpec] = {}
    for server, entry in servers.items():
        for tool, spec in entry["tools"].items():
            tool_id = f"mcp.{server}.{tool}"
            out[tool_id] = ToolSpec(
                tool_id=tool_id, provider="mcp", description=str(spec.get("description") or f"{tool} on MCP server {server}"),
                sensitivity=spec["sensitivity"], scopes=frozenset(spec.get("scopes") or [f"mcp:{spec['sensitivity'].lower()}"]),
                input_schema=spec.get("input_schema") or {"type": "object"},
                timeout_s=float(spec.get("timeout_s") or 10), server=server)
    return out


async def _call(spec: ToolSpec, args: dict) -> dict:
    import jsonschema
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    servers, _ = configured_servers()
    entry = servers.get(spec.server or "")
    if entry is None:
        raise GatewayDenied("MCP_SERVER_NOT_CONFIGURED", f"MCP server {spec.server} is not configured", 502)
    tool_name = spec.tool_id.split(".", 2)[2]
    params = StdioServerParameters(command=entry["command"], args=entry["args"],
                                   env={k: os.environ[k] for k in _SAFE_ENV if k in os.environ})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = {t.name: t for t in (await session.list_tools()).tools}
        if tool_name not in listed:
            raise GatewayDenied("MCP_TOOL_MISSING", f"server {spec.server} does not offer {tool_name}", 502)
        try:
            jsonschema.validate(args, listed[tool_name].inputSchema or {"type": "object"})
        except jsonschema.ValidationError as exc:
            raise GatewayDenied("SCHEMA_INVALID", f"arguments rejected by the server schema: {exc.message[:200]}", 422) from exc
        result = await session.call_tool(tool_name, args, read_timeout_seconds=timedelta(seconds=spec.timeout_s))
    texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
    if result.isError:
        raise GatewayDenied("MCP_TOOL_ERROR", ("; ".join(texts) or "tool reported an error")[:300], 502)
    return {"content": texts, "structured": result.structuredContent}


_GROUP = getattr(builtins, "BaseExceptionGroup", ())  # Python 3.11+; anyio wraps task failures in it


def _unwrap(exc: BaseException) -> BaseException:
    while _GROUP and isinstance(exc, _GROUP) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def call_mcp_tool(spec: ToolSpec, args: dict) -> dict:
    if not mcp_installed():
        raise GatewayDenied("MCP_NOT_INSTALLED", "the mcp package is not installed", 503)
    try:
        return asyncio.run(asyncio.wait_for(_call(spec, args), timeout=spec.timeout_s + 5))
    except GatewayDenied:
        raise
    except BaseException as exc:  # noqa: BLE001 - anyio wraps failures in exception groups
        inner = _unwrap(exc)
        if isinstance(inner, GatewayDenied):
            raise inner from None
        if isinstance(inner, (TimeoutError, asyncio.TimeoutError)):
            raise GatewayDenied("TOOL_TIMEOUT", f"{spec.tool_id} timed out", 504) from None
        if isinstance(inner, OSError):
            raise GatewayDenied("MCP_SERVER_UNAVAILABLE", f"MCP server {spec.server} could not start", 502) from None
        raise GatewayDenied("MCP_CALL_FAILED", f"{spec.tool_id}: {type(inner).__name__}", 502) from None


__all__ = ["call_mcp_tool", "configured_servers", "mcp_installed", "mcp_tools"]
