"""A real stdio MCP server for the Sentinel gateway tests (official ``mcp`` SDK, FastMCP).

``hidden_admin`` exists on the server but is not allowlisted, so the gateway must never expose it.
"""

import time

from mcp.server.fastmcp import FastMCP

server = FastMCP("council-test")


@server.tool()
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


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
