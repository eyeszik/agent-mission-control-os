"""Reviewed MCP server profiles: admit one source-reviewed upstream server, read-only, fully pinned.

A profile is **not** an activation. ``build_server_entry`` returns the JSON entry for one server; nothing
is reachable until an operator places that entry in ``AMC_MCP_SERVERS`` in their own environment. The
gateway remains the only tool path, and every check it makes still applies: allowlist, seat scopes, the
declared and the server's input schema, capability token, execution bounds, audit with redaction, timeout
and the result-size bound.

What a profile adds over a hand-written entry:

* the exact upstream bytes that were reviewed are pinned by sha256, so an unreviewed release is refused
  before any pin is computed;
* data files the server reads are passed as arguments, so the gateway's spawn-time pin check covers
  them as well (the server ignores its argv);
* sibling paths from which the server would import unpinned code are refused;
* the tool surface is a closed allowlist of READ tools with strict, ``additionalProperties: false``
  schemas and a per-tool result bound, never what the server happens to list.

Profiles (decision record: ``docs/mcp-integration-audit.md``):

``paara``  PAARA Connector Audit (vkktask/paara-connector-audit-kit @ 9051282, MIT). Scores a connector
           or MCP server with the PAARA seven-factor rule. Standard library only, no network, no writes.

CLI (prints the entry; it never sets the environment)::

    python -m services.langgraph.agency.council.mcp_profiles paara \\
        --server-script /opt/mcp/paara/paara_mcp_server.py --python /usr/bin/python3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


class ProfileError(ValueError):
    """The server files or interpreter do not match what was reviewed; nothing is emitted."""


@dataclass(frozen=True)
class ReviewedFile:
    relative: str  # relative to the directory of the server script
    sha256: str


@dataclass(frozen=True)
class McpProfile:
    name: str
    server: str  # key in AMC_MCP_SERVERS; tools are exposed as mcp.<server>.<tool>
    upstream: str
    upstream_commit: str
    license: str
    entry: ReviewedFile
    data_files: tuple[ReviewedFile, ...]
    forbidden_siblings: tuple[str, ...]


_FACTORS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
_LABEL = {"type": "string", "minLength": 1, "maxLength": 120}


def _paara_tools() -> dict[str, dict]:
    """A fresh copy of the PAARA allowlist: three READ tools, strict schemas, bounded results."""
    def tool(description: str, schema: dict, max_bytes: int) -> dict:
        return {"sensitivity": "READ", "scopes": ["mcp:read"], "timeout_s": 10, "max_result_bytes": max_bytes,
                "description": description, "input_schema": {"type": "object", "additionalProperties": False, **schema}}

    factors = {f: {"type": "string", "enum": ["Y", "N", "U"]} for f in _FACTORS}
    return {
        "list_connectors": tool("List the 13 connectors in the published PAARA audit with their risk bands.",
                                {"properties": {}}, 16_000),
        "lookup_connector": tool("Look up one connector of the published PAARA audit by name.",
                                 {"properties": {"name": _LABEL}, "required": ["name"]}, 8_000),
        "score_connector": tool("Score a connector from its F1-F7 codes (Y/N/U) with the PAARA band rule.",
                                {"properties": {"name": _LABEL, "restricted": {"type": "boolean"}, **factors},
                                 "required": list(_FACTORS)}, 8_000),
    }


PAARA = McpProfile(
    name="paara", server="paara",
    upstream="https://github.com/vkktask/paara-connector-audit-kit",
    upstream_commit="9051282d22d1f00f6083ae20872ef308d2382535", license="MIT",
    entry=ReviewedFile("paara_mcp_server.py", "f6ffd4120fcab0a210f7b4b1b364d55609ff4a578c9a1abe98be4c354b46e89b"),
    data_files=(ReviewedFile("data/coding-sheet.csv",
                             "96321a1c29b8b49f87895e5a51ac7f73c000d3ce05601b90bd3aa2db66b71604"),),
    # The server imports scoring code from these when they exist; that code would not be pinned.
    forbidden_siblings=("../paara-repo", "paara_scanner_src"),
)

PROFILES: dict[str, McpProfile] = {PAARA.name: PAARA}
_TOOLS = {PAARA.name: _paara_tools}


def profile_tools(name: str) -> dict[str, dict]:
    return _TOOLS[name]()


def _reviewed_path(base: Path, reviewed: ReviewedFile) -> Path:
    from .mcp_client import file_sha256

    path = base / reviewed.relative
    if path.is_symlink() or not path.is_file():
        raise ProfileError(f"{reviewed.relative} must be a regular file (not a symlink)")
    if file_sha256(str(path)) != reviewed.sha256:
        raise ProfileError(f"{reviewed.relative} does not match the reviewed sha256 {reviewed.sha256}")
    return path


def _checked_interpreter(interpreter: str | os.PathLike) -> str:
    path = Path(interpreter)
    if not path.is_absolute() or not path.is_file():
        raise ProfileError("the interpreter must be an absolute path to an existing file")
    return str(path)


def _checked_script(profile: McpProfile, server_script: str | os.PathLike) -> Path:
    script = Path(server_script)
    if not script.is_absolute():
        raise ProfileError("the server script must be an absolute path")
    if script.name != Path(profile.entry.relative).name:
        raise ProfileError(f"the server script must be the reviewed {profile.entry.relative}")
    _reviewed_path(script.parent, ReviewedFile(script.name, profile.entry.sha256))
    for sibling in profile.forbidden_siblings:
        if (script.parent / sibling).exists():
            raise ProfileError(f"{sibling} exists next to the server; it would load unpinned code")
    return script


def _assert_admissible(name: str, entry: dict) -> None:
    from .mcp_client import _pin_problem

    # The gateway's own admission check: every pin present, matching, and not group- or world-writable.
    problem = _pin_problem(name, entry["command"], entry["args"], entry["pins"])
    if problem:
        raise ProfileError(problem)


def build_server_entry(name: str, server_script: str | os.PathLike, interpreter: str | os.PathLike) -> dict:
    """The ``AMC_MCP_SERVERS`` fragment for one reviewed profile. Raises ``ProfileError`` on any mismatch."""
    from .mcp_client import file_sha256, pinned_paths

    profile = PROFILES.get(name)
    if profile is None:
        raise ProfileError(f"unknown profile {name!r}; known: {sorted(PROFILES)}")
    command = _checked_interpreter(interpreter)
    script = _checked_script(profile, server_script)
    data = [str(_reviewed_path(script.parent, item)) for item in profile.data_files]
    args = ["-I", str(script), *data]
    entry = {"command": command, "args": args, "tools": profile_tools(name),
             "pins": {path: file_sha256(path) for path in pinned_paths(command, args)}}
    _assert_admissible(profile.server, entry)
    return {profile.server: entry}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a pinned AMC_MCP_SERVERS entry for a reviewed MCP profile.")
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--server-script", required=True, help="absolute path to the reviewed server script")
    parser.add_argument("--python", default=sys.executable, help="absolute interpreter path (default: this one)")
    args = parser.parse_args(argv)
    try:
        entry = build_server_entry(args.profile, args.server_script, args.python)
    except ProfileError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(entry, indent=2, sort_keys=True))
    return 0


__all__ = ["PAARA", "PROFILES", "McpProfile", "ProfileError", "ReviewedFile", "build_server_entry", "main",
           "profile_tools"]


if __name__ == "__main__":
    raise SystemExit(main())
