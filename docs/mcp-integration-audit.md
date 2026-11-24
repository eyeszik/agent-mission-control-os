# MCP integration audit — candidate selection and the PAARA profile (2026-11-24)

**Terminal state: `IMPLEMENTED_WITH_LIMITATIONS`.** One candidate (C05 PAARA Connector Audit) is integrated as a
reviewed, pinned, read-only, **disabled-by-default** gateway profile. Nothing is enabled, deployed or billed.

Machine-readable evidence: [`evidence/mcp-integration-2026-11/`](evidence/mcp-integration-2026-11/) —
`candidate_matrix.json` (C01–C18, gates, scores), `benchmarks.json` (raw runs), `test_results.json`, `harness/`.

## D01 — Baseline (verified)

| Fact | Value |
|---|---|
| Base commit | `7ac18f8af1079cdff91dd11f672ba023100b4b06` (`master`, clean worktree) |
| MCP client | `agency/council/mcp_client.py`: stdio only, official `mcp` SDK, operator allowlist in `AMC_MCP_SERVERS`, SHA-256 pins (ASI04), minimal env, typed errors |
| Tool authority | `agency/council/gateway.py` `invoke`: allowlist → seat scopes → execution bounds → schema → Ed25519 capability → approval (non-READ) → timeout → redacted audit |
| Approvals / audit | `approvals` rows decided on `/approvals/{id}/decide`; `council_tool_audits` via `persistence/council.py` |
| CI | `backend-council` job installs `[dev,council]` with `constraints-council.txt` (`mcp==1.30.0`) |
| Gates at base | 5/7 pass; `verify_repository_invariants` and `verify_manifest` **fail at base** (DEF-2; fixed on `master` by #301, merged into this branch: 7/7 pass) |
| Council MCP tests at base | 23/23 pass on `mcp 1.30.0`; **3 fail on `mcp 2.3.0`** (DEF-1) |

Subsystem classification relevant to MCP: gateway + MCP client `IMPLEMENTED_VERIFIED` (tests above); HTTP/SSE MCP
transports `ABSENT` (`mcp_integration_spec.json` lists them as optional only); OS-level network sandbox for MCP
servers `ABSENT` (the process inherits host networking; only the tool allowlist limits reachable code paths).

## D02 — MCP capability inventory before this change

Local tools: `workspace.list_files`, `workspace.read_file` (READ), `workspace.write_scaffold` (WRITE, approval),
`policy.scan_text` (READ). MCP tools: none configured (`.env.example`: `AMC_MCP_SERVERS=`). No marketing
calculators, connector-risk scoring, web research or document tools are reachable by a seat.

## D03/D04 — Candidates, threat model and gates

Trust boundary: seat → `gateway.invoke` (authority) → `mcp_client` (adapter) → stdio server process → its
downstream (network/files). The gateway is the only enforcement point; it cannot sandbox the server process, so
G7 is satisfied only by servers whose **source** shows no network/process/write capability on the allowlisted
paths, and G9 only when every executed file is covered by a pin.

| ID | Candidate | Cat. | Decision | Deciding evidence |
|---|---|---|---|---|
| C01 | CodeExplorer | A | DEFER | VS Code extension + hosted app; no runtime consumer |
| C02 | Graphenium | A | DEFER | Rust build, rmcp 0.1, optional LLM keys |
| C03 | Sentinel-IR | A | DEFER | Developer-side code IR; reads local trees |
| C04 | Draugr | A/D | DEFER | Value needs cloud/VirusTotal credentials |
| **C05** | **PAARA Connector Audit** | **B** | **SELECT** | **All ten gates PASS; stdlib-only; 141/141 oracle** |
| C06 | WebRouter | D | REJECT | Paid providers + arbitrary fetch; research providers DISABLED by rule |
| C07 | OpenSERP | D | DEFER | Hosted API key; billing |
| C08 | Social Fetch | D | REJECT | Hosted proxy with key; third-party social data |
| C09 | upGrowth Toolkit | B | PILOT | Best feature fit; G3 UNKNOWN (Node), G9 FAIL as-is (unpinned `worker.mjs`), SSRF tool |
| C10–C12 | KitchenSink4Word/PPT/XL | C | DEFER | AGPL-3.0; startup update check egress |
| C13 | Surehand | C | REJECT | Needs After Effects; arbitrary ExtendScript |
| C14 | Fairquery Agent Trust | B/D | DEFER | Free tools overlap `security/pii.py`; paid Apify tools |
| C15 | Offprompt | A | REJECT | Browser secret collection; workstation-only |
| C16 | Lucy Memory | B/D | REJECT | Second system of record beside Project OS |
| C17 | ClickHouse Loom | B/D | REJECT | Platform with its own storage/orchestration |
| C18 | PremAgentic | B/D | REJECT | AGPL+CLA, .NET, own retrieval store |

Per-gate values, licences, commits and notes for every row: `candidate_matrix.json`. glama.ai listings were
unreachable here and were **not** used as evidence; every row is from the upstream source at the listed commit.

## D05 — Benchmarks (offline, `unshare -rn`, N stated)

| Run | Result | Notes |
|---|---|---|
| B0 protocol probe, PAARA, N=10 | handshake + `tools/list` + 5 calls; init p50 23 ms, session p50 55 ms; deterministic | 3 tools, all `readOnlyHint` |
| B0 protocol probe, upGrowth, N=10 | init p50 44 ms, session p50 67 ms; deterministic | 29 tools; `ai_crawler_access_check` attempted egress (blocked); `book_strategy_call` returns a sales link |
| B1 PAARA correctness | **141/141** | 13 published bands + all 128 Y/N combinations vs an independent band-rule oracle |
| B2 upGrowth correctness | **9/9** (7/9 before a harness key fix) | ROAS, break-even, ROI, CAC/LTV/payback, invalid input |

Not run (with reasons in `benchmarks.json`): CodeExplorer vs Graphenium (NOT_TESTED), WebRouter vs OpenSERP
(**BLOCKED**: paid, spend not authorised), the memory and document comparisons (rejected/deferred first). No
statistical claim is made; these are single-host functional measurements.

## D06 — Selection decision

| Dimension (weight) | C05 PAARA | C09 upGrowth |
|---|---|---|
| Feature gap (25%) | 2 | 4 |
| Architectural compatibility (20%) | 5 | 3 |
| Security and governance (20%) | 5 | 3 |
| Measured improvement (15%) | 3 | 4 |
| Reliability and maintenance (10%) | 3 | 3 |
| Cost and simplicity (10%) | 5 | 3 |
| **Total** | **75** | **68** |
| Hard gates | 10/10 PASS | G3 UNKNOWN, G9 FAIL as-is |

C05 is selected because it is the only candidate that passes every hard gate; scores do not override gates.
Its incremental value is **modest and stated as such**: a cited, deterministic risk band (Low–Critical) for a
connector or MCP server, which seats or operators can use when deciding whether to admit a server to
`AMC_MCP_SERVERS`. C09 offers more agency value and is the recommended next candidate (below).

## D07 — Integration design (as built)

| Item | Design |
|---|---|
| A. Surface | Existing `gateway.invoke` → `mcp_client`; no new route, store, approval path or orchestrator |
| B. Transport | stdio, one process per call (no state shared across tenants), `python -I` |
| C. Registration | Operator places the entry printed by `mcp_profiles` into `AMC_MCP_SERVERS` |
| D. Schemas | Declared strict schemas (`additionalProperties: false`, enums, `maxLength: 120`), then the server's own schema |
| E. Allowlist | `list_connectors`, `lookup_connector`, `score_connector`; all READ, scope `mcp:read` |
| F/G. AuthZ, tenancy | Unchanged gateway: seat scopes, capability token, audit row carries tenant/project; audits readable only by the owning tenant |
| H. Normalisation | Text + structured content, redacted by `redact_value`; results are data, never instructions |
| I. Audit | `council_tool_audits` (ALLOWED/DENIED/FAILED/TIMEOUT with reason code, args hash, duration) |
| J. Timeout/retry | 10 s per tool; no automatic retry (READ and idempotent; a caller may re-invoke) |
| K. Quotas/spend | No spend possible (no network); execution bounds (budget, loop, velocity, halt) unchanged |
| L. Kill switch | Remove the `paara` entry (or empty `AMC_MCP_SERVERS`) and restart |
| M. Observability | Audit rows + `GET /missions/tools` (`mcp_installed`, `mcp_config_errors`) |
| N. Recovery | Typed refusals: `MCP_PIN_MISMATCH`, `MCP_RESULT_TOO_LARGE`, `TOOL_TIMEOUT`, `MCP_SERVER_UNAVAILABLE`, `MCP_CALL_FAILED`, `SCHEMA_INVALID` |
| Supply chain | Profile pins the reviewed upstream bytes (script **and** data file, passed as an argument so the spawn-time pin covers it); refuses sibling paths that would import unpinned code; `PAARA_KIT_SRC` never reaches the server |

## D08 — Changes

| File | Change |
|---|---|
| `agency/council/mcp_profiles.py` | **New.** Reviewed-profile builder + CLI (prints only) |
| `agency/council/mcp_client.py` | Fails closed on `mcp` 2.x (DEF-1); per-tool `max_result_bytes` bound + config validation |
| `agency/council/gateway.py` | `ToolSpec.max_result_bytes`; declared-schema violations become `SCHEMA_INVALID` and are audited (DEF-3) |
| `services/langgraph/pyproject.toml` | `mcp>=1.28,<2` (DEF-1) |
| `tests/test_mcp_paara_profile.py` | **New.** 30 tests (unit, protocol, security, reliability, E2E) |
| `tests/fixtures/vendor/paara_connector_audit/` | **New.** Byte-identical upstream server + data + MIT licence + provenance (tests only) |
| `tests/council_support.py`, `test_council_gateway.py`, `test_capability_tokens.py` | Skip with a stated reason under an unsupported SDK instead of failing on a missing tool |
| `.github/workflows/ci.yml` | `backend-council` also runs `test_mcp_paara_profile.py` and `test_capability_tokens.py` |
| `docs/mission-council.md`, `.env.example` | Pins, result bound, SDK support, profiles, kill switch |
| `manifest.json` | Re-pinned the changed tracked files; added `mcp_profiles.py` |

### Defects found

| ID | Class | Status | Description |
|---|---|---|---|
| DEF-1 | DEPENDENCY_CONFLICT | **Fixed** | `mcp>=1.28,<3` admitted 2.x, under which `call_tool(read_timeout_seconds=timedelta)` raises `TypeError`; every MCP call failed as `MCP_CALL_FAILED`. Now `<2`, and an installed 2.x lists no MCP tool |
| DEF-3 | SECURITY_FAILURE (audit gap) | **Fixed** | A violation of an operator-declared MCP `input_schema` raised raw `jsonschema.ValidationError` out of `invoke`: untyped, **unaudited**. Now `SCHEMA_INVALID` + DENIED audit. Regression: 4 parametrised cases failed before the fix |
| DEF-2 | AUTHORIZATION_BLOCKER (pre-existing) | **Resolved upstream by the repository owner in #301** (merged into this branch); not changed here | Commit `7ac18f8` (dependabot) bumped Next.js 16.4.5→16.4.6 without updating the audited-version invariant or `manifest.json`. Fixing it asserts an audit of 16.4.6; that decision is not this change's to make. `apps/web/package.json` and `pnpm-lock.yaml` (the only two drifted manifest entries) were deliberately **not** re-pinned |

## D09 — Test evidence

`evidence/mcp-integration-2026-11/test_results.json` (TEST_ID, command, expected, observed, status, limitation).

| Suite | Result |
|---|---|
| New `test_mcp_paara_profile.py` | 30/30 PASS (4 declared-schema cases failed before the DEF-3 fix) |
| Council CI set + security regressions | 137 PASS, 8 SKIP (CrewAI/AutoGen absent locally), 0 FAIL |
| Same MCP files on unsupported `mcp 2.3.0` | 29 PASS, 24 SKIP, 0 FAIL (base: 3 FAIL) |
| Full backend suite | 2566 PASS / 19 FAIL / 164 SKIP; base 2536 / 19 / 164 — **identical failure set**, all reproduced on a clean base worktree (Python 3.13 Unicode parity fixtures, host ffprobe, DEF-2) |
| Live API enable → rollback | PASS: 3 tools listed, then none |
| Verifier gates | 7/7 PASS after merging `master` (#301 resolved DEF-2); before the merge 5/7, the other 2 failing only on DEF-2 |

## D10 — Operation and rollback

**Enable (non-production, operator decision):**

1. Place the reviewed files (commit `9051282`) in a read-only directory owned by root, e.g.
   `/opt/mcp/paara/paara_mcp_server.py` and `/opt/mcp/paara/data/coding-sheet.csv` (mode 0644, dirs 0755).
   Ensure neither `/opt/mcp/paara-repo` nor `/opt/mcp/paara/paara_scanner_src` exists.
2. Install the `council` extra with `constraints-council.txt` (supported `mcp` 1.x).
3. `python -m services.langgraph.agency.council.mcp_profiles paara --server-script /opt/mcp/paara/paara_mcp_server.py --python /usr/bin/python3`
   — exit 0 prints the entry; exit 2 prints the refusal reason.
4. Put the printed JSON in `AMC_MCP_SERVERS` (merge with existing entries), restart, and confirm
   `GET /missions/tools` lists exactly `mcp.paara.{list_connectors,lookup_connector,score_connector}` and no
   `mcp_config_errors`.

**Rollback (integration):** remove the `paara` key from `AMC_MCP_SERVERS` (or empty it) and restart; verify
`GET /missions/tools` lists no `mcp.paara.*` tool. No data, table or migration was added, so nothing else to undo.

**Rollback (code):** `git revert <merge commit>`; then run `python scripts/verify_manifest.py` and the council
test files. Reverting also restores DEF-1 and DEF-3.

## D11 — Dependencies and licences

No new runtime dependency. `mcp` range narrowed (`<2`). Vendored test fixture: PAARA server (MIT, © 2026 Vivek
Kumar), standard library only, no transitive dependencies. Candidate licences: `candidate_matrix.json`
(AGPL-3.0: C10–C12, C18).

## Recommended next candidate — C09 upGrowth Growth Toolkit (PILOT)

Highest agency value (26 deterministic marketing calculators: ROAS, CAC/LTV, PPC forecast, break-even, schema and
meta-tag builders; 9/9 oracle checks). Before it can pass the gates:

1. **G3** — decide that the API runtime ships Node ≥ 18 (it is in the web toolchain but not declared for the
   backend), or reject.
2. **G9/ASI04** — pin `worker.mjs` too: pass it as an extra argument (the stdio shim ignores argv) through a
   reviewed profile, exactly as the PAARA data file is pinned here.
3. **G7** — allowlist the calculators only; exclude `ai_crawler_access_check` (fetches caller-chosen hosts,
   SSRF to internal names), `book_strategy_call` (vendor upsell) and `find_growth_moves` (third-party text).
4. Add a correctness suite per allowlisted tool against independent formulas, since outputs feed client advice.
