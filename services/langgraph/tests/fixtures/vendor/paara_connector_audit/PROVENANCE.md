# Vendored test fixture: PAARA Connector Audit MCP server

Third-party code, vendored **for tests only**. It is not packaged (`services/langgraph/tests` is outside the
wheel's package list) and nothing in the runtime imports it. It exists so the gateway's MCP path can be tested
end to end, offline, against the exact upstream bytes that were reviewed.

| Field | Value |
|---|---|
| Upstream | https://github.com/vkktask/paara-connector-audit-kit |
| Commit | `9051282d22d1f00f6083ae20872ef308d2382535` (2026-11-17) |
| Server version | `paara-connector-audit` 1.2.2 |
| Licence | MIT (`LICENSE`, copied unmodified) |
| `paara_mcp_server.py` sha256 | `f6ffd4120fcab0a210f7b4b1b364d55609ff4a578c9a1abe98be4c354b46e89b` (`mcp-server/paara_mcp_server.py`) |
| `data/coding-sheet.csv` sha256 | `96321a1c29b8b49f87895e5a51ac7f73c000d3ce05601b90bd3aa2db66b71604` (`mcp-server/data/coding-sheet.csv`) |

Both files are byte-identical to upstream. Do not edit them: `agency/council/mcp_profiles.py` pins these hashes
and refuses any other bytes. To adopt a new upstream release, review its source again, replace both files,
and update the hashes in the profile and here in the same change.

Review notes (see `docs/mcp-integration-audit.md`): standard library only (`csv`, `difflib`, `json`, `os`,
`sys`, `pathlib`); no network, subprocess or file writes; three read-only tools. It can import scoring code
from `$PAARA_KIT_SRC`, `../paara-repo/src` or `paara_scanner_src/` when present. The gateway does not pass
`PAARA_KIT_SRC` to the server, and the profile refuses a layout where either sibling path exists.
