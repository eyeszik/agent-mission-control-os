# Vendored test fixture: upGrowth Growth Toolkit MCP server

Third-party code, vendored **for tests only**. It is not packaged (`services/langgraph/tests` is outside the
wheel's package list) and nothing in the runtime imports it. It lets the gateway's MCP path be tested end to
end, offline, against the exact upstream bytes that were reviewed.

| Field | Value |
|---|---|
| Upstream | https://github.com/upGrowth-in/upgrowth-growth-toolkit |
| Commit | `3b6472027ebbd7f7fc69b82766e61810fb400615` |
| Server version | `upgrowth-growth-toolkit` 1.4.2 |
| Licence | MIT (`LICENSE`, copied unmodified) |
| `src/stdio.mjs` sha256 | `cd30ebf885601db6c89d0c0099acc8dadff662c94c8d8ffce1d08b88a1e6c311` |
| `src/worker.mjs` sha256 | `022af4d73fda963d9ac5f3554ee7b8bd362048a93c5ea0dffcc8f0b8cbee313a` |

Both files are byte-identical to upstream. Do not edit them: `agency/council/mcp_profiles.py` pins these
hashes and refuses any other bytes. To adopt a new upstream release, review its source again, replace both
files, regenerate `agency/council/mcp_profile_upgrowth.py` from the new `tools/list`, and update the hashes
in the profile and here in the same change.

Review notes (see `docs/mcp-integration-audit.md`): `stdio.mjs` imports only `node:readline` and
`./worker.mjs`; `worker.mjs` has no imports, no `eval`/`Function`, no `process` access. Its only network
calls are `fetch` in `ai_crawler_access_check` and a Cloudflare route fallthrough that the stdio shim never
reaches. The profile never allowlists that tool, runs the server under the Node permission model, and
preloads `agency/council/mcp_no_network.mjs`, which disables `fetch`.
