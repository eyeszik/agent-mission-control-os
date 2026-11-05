---
name: agent-tool-security
description: Work on the agent tool-call security controls in the council gateway - scoped Ed25519 capability tokens (ASI03), MCP server pinning (ASI04), approval framing evidence (ASI09), and the anomaly strike and session halt (ASI10). Use when changing services/langgraph/agency/council/gateway.py, capability.py, mcp_client.py, agency/reliability/execution_bounds.py, security/approval_framing.py, or persistence/approvals.py.
---

# Agent tool-call security controls

## Invariants (do not weaken)
1. **Capabilities (ASI03).** Only the gateway holds the Ed25519 signing key. Tool servers verify with the public
   key only. Each token is single-use (`jti` registry), bound to one tool (`aud`), one argument hash (`args_sha256`),
   and a short TTL. Verification order: signature, issuer, audience, args, TTL, not-before, expiry, scopes, then `jti`.
   The gateway mints and verifies the token **before** consuming an approval.
2. **MCP pinning (ASI04).** Each configured server is SHA-256 pinned. A mismatch refuses the server.
   Use an existing, pinned, non-executable file for the unavailable-server case. A nonexistent path is dropped at config and
   returns `TOOL_NOT_ALLOWLISTED`, not `MCP_SERVER_UNAVAILABLE`.
3. **Approval framing (ASI09).** `assess()` is a heuristic. It labels a summary NONE, REVIEW, or HIGH. Storing the
   level is not a judgement of truth. Approving a HIGH summary needs `framing_acknowledged=true`, else 409
   (`FramingAcknowledgementRequired`). Rejection is never gated.
4. **Anomaly halt (ASI10).** Strikes come only from `_STRIKE_CODES`. Three strikes halt the session (423 `SESSION_HALTED`).
   Only `clear_halt(...)` lifts a halt. It needs a named human owner and a note, and it is **not** an HTTP endpoint.
   Halted guards are never evicted. A full registry of halted sessions refuses newcomers (`SESSION_REGISTRY_FULL`).

## Checklist before merging a change here
- `ruff check --select E4,E7,E9,F` on every changed file. Fixture-injection F811 uses targeted `# noqa: F811`.
- Run `test_capability_tokens.py`, `test_council_gateway.py`, `test_execution_bounds.py`, `test_asi10_anomaly_halt.py`,
  `test_approval_framing.py`, `test_approvals.py`.
- Regenerate pins: edit `manifest.json` entries deliberately, then run `scripts/verify_manifest.py`.
- Do not add a second approval endpoint, artifact store, or orchestrator.

## Known limits (state them, do not hide them)
- Guard state is process-local. Halts and budgets do not survive a restart or span workers.
- Goal drift uses idea title and description words. It is a heuristic, English-only, and has no measured baseline.
- Mission objectives are not a field. Drift is off when no idea is linked.
