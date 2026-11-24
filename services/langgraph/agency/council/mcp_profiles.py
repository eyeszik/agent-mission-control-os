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

``paara``     PAARA Connector Audit (vkktask/paara-connector-audit-kit @ 9051282, MIT). Scores a connector
              or MCP server with the PAARA seven-factor rule. Standard library only, no network, no writes.
``upgrowth``  upGrowth Growth Toolkit (upGrowth-in/upgrowth-growth-toolkit @ 3b64720, MIT). 26 deterministic
              marketing calculators and generators (ROAS, CAC/LTV, PPC, break-even, schema and meta tags).
              Needs an operator-supplied Node >= 20. Runs under the Node permission model (read access to its
              own three files only; no child processes, workers, addons or writes) with a preload that
              disables ``fetch`` and the other network globals. Three upstream tools are never allowlisted
              (``mcp_profile_upgrowth.EXCLUDED_TOOLS``).

CLI (prints the entry; it never sets the environment)::

    python -m services.langgraph.agency.council.mcp_profiles paara \\
        --server-script /opt/mcp/paara/paara_mcp_server.py --interpreter /usr/bin/python3
    python -m services.langgraph.agency.council.mcp_profiles upgrowth \\
        --server-script /opt/mcp/upgrowth/src/stdio.mjs --interpreter /usr/bin/node
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
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
    runtime: str = "python"  # "python" | "node"


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

# ------------------------------------------------------------------------------------- upGrowth

_STRING_LIMITS = {"text": 60_000, "currency": 8}  # content_seo_check documents 60,000 characters
_DEFAULT_STRING_MAX = 2_000
_DEFAULT_ARRAY_MAX = 50
_FREE_FORM_MAX_PROPERTIES = 40
_UPGROWTH_RESULT_BYTES = 24_000


def _harden(schema: dict, name: str = "") -> dict:
    """Close objects, bound every string and array. Returns a new schema; the input is not changed."""
    out = copy.deepcopy(schema)
    kind = out.get("type")
    if kind == "object":
        props = out.get("properties")
        if props:
            out["properties"] = {key: _harden(value, key) for key, value in props.items()}
            out["additionalProperties"] = False
        else:  # free-form payload (schema_generator's ``data``): bound its size instead
            out.setdefault("maxProperties", _FREE_FORM_MAX_PROPERTIES)
    elif kind == "array":
        out.setdefault("maxItems", _DEFAULT_ARRAY_MAX)
        if isinstance(out.get("items"), dict):
            out["items"] = _harden(out["items"], name)
    elif kind == "string" and "enum" not in out:
        out.setdefault("maxLength", _STRING_LIMITS.get(name, _DEFAULT_STRING_MAX))
    return out


def _upgrowth_tools() -> dict[str, dict]:
    """A fresh copy of the upGrowth allowlist: 26 READ tools, hardened schemas, bounded results."""
    from .mcp_profile_upgrowth import UPSTREAM_TOOLS

    return {name: {"sensitivity": "READ", "scopes": ["mcp:read"], "timeout_s": 10,
                   "max_result_bytes": _UPGROWTH_RESULT_BYTES, "description": f"upGrowth: {spec['title']}",
                   "input_schema": _harden(spec["input_schema"])}
            for name, spec in UPSTREAM_TOOLS.items()}


UPGROWTH = McpProfile(
    name="upgrowth", server="upgrowth",
    upstream="https://github.com/upGrowth-in/upgrowth-growth-toolkit",
    upstream_commit="3b6472027ebbd7f7fc69b82766e61810fb400615", license="MIT",
    entry=ReviewedFile("stdio.mjs", "cd30ebf885601db6c89d0c0099acc8dadff662c94c8d8ffce1d08b88a1e6c311"),
    # stdio.mjs imports ./worker.mjs. Passing it as an (ignored) argument puts it under the gateway's pin.
    data_files=(ReviewedFile("worker.mjs", "022af4d73fda963d9ac5f3554ee7b8bd362048a93c5ea0dffcc8f0b8cbee313a"),),
    forbidden_siblings=(), runtime="node",
)

NO_NETWORK_PRELOAD = Path(__file__).with_name("mcp_no_network.mjs")
MIN_NODE_MAJOR = 20  # the permission model and global fetch/Request
_NODE_VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

PROFILES: dict[str, McpProfile] = {PAARA.name: PAARA, UPGROWTH.name: UPGROWTH}
_TOOLS = {PAARA.name: _paara_tools, UPGROWTH.name: _upgrowth_tools}


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


def node_version(command: str) -> tuple[int, int, int]:
    """The version an interpreter reports for itself. Raises ``ProfileError`` when it cannot be read."""
    try:
        done = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10,
                              env={"PATH": "/usr/bin:/bin"}, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProfileError(f"could not run {command} --version: {type(exc).__name__}") from exc
    match = _NODE_VERSION.match(done.stdout.strip())
    if done.returncode != 0 or not match:
        raise ProfileError(f"{command} did not report a Node version")
    return int(match[1]), int(match[2]), int(match[3])


def permission_flag(version: tuple[int, int, int]) -> str:
    """``--permission`` from Node 22.13 / 23.5; ``--experimental-permission`` on 20.0-22.12 and 23.0-23.4."""
    major, minor, _ = version
    if major < MIN_NODE_MAJOR:
        raise ProfileError(f"Node {major}.{minor} is too old; the profile needs Node >= {MIN_NODE_MAJOR}")
    stable = major >= 24 or (major == 22 and minor >= 13) or (major == 23 and minor >= 5)
    return "--permission" if stable else "--experimental-permission"


def _node_args(command: str, script: Path, data: list[str]) -> list[str]:
    """Permission model with read access to exactly the server files and the preload; network globals off."""
    preload = NO_NETWORK_PRELOAD
    if preload.is_symlink() or not preload.is_file():
        raise ProfileError(f"{preload.name} is missing; it ships with this module")
    readable = [str(script), *data, str(preload)]
    return [permission_flag(node_version(command)), *(f"--allow-fs-read={path}" for path in readable),
            "--import", str(preload), str(script), *data]


def _runtime_args(profile: McpProfile, command: str, script: Path, data: list[str]) -> list[str]:
    if profile.runtime == "node":
        return _node_args(command, script, data)
    return ["-I", str(script), *data]


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
    args = _runtime_args(profile, command, script, data)
    entry = {"command": command, "args": args, "tools": profile_tools(name),
             "pins": {path: file_sha256(path) for path in pinned_paths(command, args)}}
    _assert_admissible(profile.server, entry)
    return {profile.server: entry}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a pinned AMC_MCP_SERVERS entry for a reviewed MCP profile.")
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--server-script", required=True, help="absolute path to the reviewed server script")
    parser.add_argument("--interpreter", "--python", dest="interpreter", default=None,
                        help="absolute interpreter path (python profiles default to this interpreter)")
    args = parser.parse_args(argv)
    interpreter = args.interpreter or (sys.executable if PROFILES[args.profile].runtime == "python" else None)
    if interpreter is None:
        print("refused: --interpreter is required for a Node profile (an absolute path to node)", file=sys.stderr)
        return 2
    try:
        entry = build_server_entry(args.profile, args.server_script, interpreter)
    except ProfileError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(entry, indent=2, sort_keys=True))
    return 0


__all__ = ["NO_NETWORK_PRELOAD", "PAARA", "PROFILES", "UPGROWTH", "McpProfile", "ProfileError", "ReviewedFile",
           "build_server_entry", "main", "node_version", "permission_flag", "profile_tools"]


if __name__ == "__main__":
    raise SystemExit(main())
