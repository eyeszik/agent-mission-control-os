"""A real stdio MCP server for the Sentinel gateway tests (official ``mcp`` SDK, FastMCP).

``hidden_admin`` exists on the server but is not allowlisted, so the gateway must never expose it.
"""

import sys
import time
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

# Repository root, so the verifier below can use the gateway's own capability module.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

server = FastMCP("council-test")
_VERIFIER = {"public_key": None}
_VERIFY_TOOL = "mcp.testsrv.echo_verified"


def _public_key_from_argv():
    from cryptography.hazmat.primitives import serialization

    if "--public-key-file" not in sys.argv:
        return None
    path = sys.argv[sys.argv.index("--public-key-file") + 1]
    return serialization.load_pem_public_key(Path(path).read_bytes())


@server.tool()
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


@server.tool()
def echo_verified(text: str, ctx: Context) -> str:
    """Echo only when the gateway's capability verifies for exactly this text (ASI03)."""
    from services.langgraph.agency.council.capability import METADATA_KEY, JTIRegistry, verify

    if _VERIFIER["public_key"] is None:
        _VERIFIER["public_key"] = _public_key_from_argv()
        _VERIFIER["registry"] = JTIRegistry()
    meta = ctx.request_context.meta
    token = getattr(meta, METADATA_KEY, None) or (meta.model_extra or {}).get(METADATA_KEY) if meta else None
    if not token:
        raise RuntimeError("no capability presented")
    claims = verify(token, public_key=_VERIFIER["public_key"], tool_id=_VERIFY_TOOL, args={"text": text},
                    required_scopes=frozenset({"mcp:read"}), registry=_VERIFIER["registry"])
    return f"verified:{claims['jti']}:{text}"


@server.tool()
def fail() -> str:
    """Always fails."""
    raise RuntimeError("deliberate tool failure")


@server.tool()
def slow(seconds: float) -> str:
    """Sleep, then answer."""
    time.sleep(seconds)
    return "done"


@server.tool()
def run_shell(command: str) -> str:
    """A shell-shaped tool; the gateway must refuse it."""
    return f"would run {command}"


@server.tool()
def hidden_admin() -> str:
    """Not allowlisted."""
    return "should never be reachable"


if __name__ == "__main__":
    server.run("stdio")
