# MCP integration audit — candidate selection, the PAARA and upGrowth profiles (2026-11-24)

**Terminal state: `IMPLEMENTED_WITH_LIMITATIONS`.** Two candidates are integrated as reviewed, pinned, read-only,
**disabled-by-default** gateway profiles: C05 PAARA Connector Audit (first increment, #302) and C09 upGrowth
Growth Toolkit (second increment, [below](#second-increment--c09-upgrowth-growth-toolkit)). Nothing is enabled,
deployed or billed.

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
| **C09** | **upGrowth Toolkit** | **B** | **SELECT (2nd increment)** | Gates met after mitigation: operator-supplied Node, every executed file pinned, permission model + no-network preload, 26 calculators only |
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

## Second increment — C09 upGrowth Growth Toolkit

**Decision:** SELECT, after the repository owner authorised Node as an operator-supplied runtime for this
profile ("proceed with next candidate"). Upstream re-checked at implementation time: unchanged at
`3b6472027ebbd7f7fc69b82766e61810fb400615` (v1.4.2, MIT).

### Gates after mitigation

| Gate | Before | After | How |
|---|---|---|---|
| G3 runtime | UNKNOWN | PASS (conditional on the operator) | The operator supplies Node ≥ 20 by absolute path; the profile reads its version and refuses older or non-Node binaries. Not added to the API's own dependencies. |
| G7 scope | CONDITIONAL | PASS | Node permission model with read access to exactly three files (no child processes, workers, addons or writes); `mcp_no_network.mjs` preload makes `fetch`/`WebSocket`/`EventSource`/`XMLHttpRequest` throw and cannot be undone; the only network tool is never allowlisted; source check: no imports, no `node:net`/`http`. |
| G9 pins | FAIL | PASS | `worker.mjs` is passed as an argument the shim ignores, so the gateway pins it; the preload is pinned the same way. Pinned: `node`, `stdio.mjs`, `worker.mjs`, `mcp_no_network.mjs`. |
| G8 bounds | PASS | PASS | Hardened schemas: `additionalProperties: false`, every string bounded (2,000; 60,000 for article text), arrays ≤ 50, free-form `data` ≤ 40 properties; 24 KB result bound; 10 s timeout; upstream rejects bodies > 64 KiB. |
| G1, G2, G4, G5, G6, G10 | PASS | PASS | MIT; verified handshake on Node 22.12 and 22.23; no credentials; one process per call; all READ; 26 calculators absent from AMCOS before. |

The permission flag follows the interpreter: `--permission` on Node ≥ 22.13 / 23.5, `--experimental-permission`
on 20.0–22.12 and 23.0–23.4 (verified on a checksum-verified Node 22.12.0: `--permission` is rejected there).

### Allowlist

26 tools: `acos_check`, `ad_budget_planner`, `attrition_rate`, `break_even`, `campaign_roi`, `content_seo_check`,
`customer_lifetime_value`, `ecommerce_metrics`, `engagement_rate`, `growth_projection`, `growth_rate`,
`instagram_earnings`, `max_affordable_cac`, `mdr_charges`, `meta_tags_builder`, `period_change`, `ppc_forecast`,
`roas_check`, `robots_txt_generator`, `schema_generator`, `seo_roi`, `share_of_voice`, `unit_economics`,
`website_ad_revenue`, `youtube_earnings`, `ytd_growth`. Never allowlisted: `ai_crawler_access_check` (network,
SSRF to internal names), `book_strategy_call` (vendor sales link), `find_growth_moves` (third-party news text).

Note: outputs default to the INR currency label unless `currency` is passed; seats should pass it.

### Changes

| File | Change |
|---|---|
| `agency/council/mcp_profiles.py` | Runtime-aware builder (`python` / `node`), `UPGROWTH` profile, version-based permission flag, schema hardening |
| `agency/council/mcp_profile_upgrowth.py` | **New.** The 26 upstream input schemas (descriptions removed) and the excluded tools |
| `agency/council/mcp_no_network.mjs` | **New.** Network-denial preload (packaged via `pyproject.toml` include) |
| `tests/test_mcp_upgrowth_profile.py` | **New.** 53 tests |
| `tests/fixtures/vendor/upgrowth_growth_toolkit/` | **New.** Byte-identical upstream `stdio.mjs`, `worker.mjs`, MIT licence, provenance (tests only) |
| `tests/council_support.py` | `isolated_node` launcher (a hosted runner's `node` is group-writable) |
| `tests/test_mcp_paara_profile.py` | The "unknown profile" case used the name `upgrowth`, which now exists; it uses `no-such-profile` |
| `.github/workflows/ci.yml` | Council job: Node 22.12.0, the new test file, and a step that fails if the upGrowth tests skip |

### Defects found while building it

| ID | Class | Status | Description |
|---|---|---|---|
| DEF-4 | IMPLEMENTATION_DEFECT (this change) | **Fixed before merge** | The schema generator stripped every key named `title`/`description`, including *property names*: `meta_tags_builder` lost its required `title` and `description`. The gateway refused the calls (fail closed). The drift test used the same stripping, so it could not see it. Both now strip only annotation keywords; a negative control (re-injecting the loss) makes the drift test fail. |
| — | Design interaction (not a defect) | Documented | ASI10's `TOOL_SPRAWL` guard refuses a 9th distinct tool in one session. It applies to MCP tools too (tested). A seat that needs more than 8 distinct tools splits the work across missions; the limit is the code constant `execution_bounds.MAX_NOVEL_TOOLS` (8), and `TOOL_SPRAWL` is also an anomaly strike (three strikes halt the session). |

### Test evidence

| Suite | Result |
|---|---|
| `test_mcp_upgrowth_profile.py`, Node 22.23.5 (`--permission`) | 53/53 PASS |
| Same, Node 22.12.0 (`--experimental-permission`, CI's version) | 53/53 PASS |
| Per-tool correctness | 22/22 calculators match textbook-formula oracles; 4/4 generators pass structural and escaping checks (JSON-LD cannot break out of `<script>`, meta tags HTML-escaped, `javascript:` URLs dropped, robots.txt newline injection refused) |
| Isolation | `fetch` refused even with network present and after an attempt to reassign it; child process and file write `ERR_ACCESS_DENIED`; an allowlisted crawler would still fail ("Could not reach") |
| Council CI set + security regressions (mcp 1.30) | 190 PASS, 8 SKIP (CrewAI/AutoGen absent locally), 0 FAIL |
| Unsupported mcp 2.3 | 48 PASS, 58 SKIP, 0 FAIL |
| Live API | PAARA + upGrowth: 3 + 26 tools, no config errors; remove upGrowth → 3; empty → 0 (rollback verified) |

Full-suite and gate results: `evidence/mcp-integration-2026-11/upgrowth_test_results.json`.

### Operation and rollback

1. Place the reviewed `src/stdio.mjs` and `src/worker.mjs` (commit `3b64720`) in a root-owned read-only directory,
   e.g. `/opt/mcp/upgrowth/src/` (files 0644, dirs 0755).
2. Install Node ≥ 20 (the repository uses 22.12.0) at a path that is not group- or world-writable.
3. `python -m services.langgraph.agency.council.mcp_profiles upgrowth --server-script /opt/mcp/upgrowth/src/stdio.mjs --interpreter /usr/bin/node`
4. Merge the printed JSON into `AMC_MCP_SERVERS`, restart, and confirm `GET /missions/tools` lists the 26
   `mcp.upgrowth.*` tools and no `mcp_config_errors`.

Rollback: remove the `upgrowth` key (other entries such as `paara` keep working) and restart; verify no
`mcp.upgrowth.*` tool is listed. Code rollback: `git revert` the merge commit.

### Residual risks

- The preload is defence in depth, not a sandbox: it cannot stop code that imports `node:net`. The reviewed bytes
  do not, and any change to them is refused by the pins; a new upstream release needs a new review.
- On Node 20.0–22.12 the permission model is experimental (it prints a warning on stderr).
- Calculator outputs are advice inputs, not facts about a client; seats must still cite their inputs.

## Post-merge reconciliation (2026-11-24)

Evidence: [`post_merge_reconciliation.json`](evidence/mcp-integration-2026-11/post_merge_reconciliation.json),
[`pii_benchmark_c14.json`](evidence/mcp-integration-2026-11/pii_benchmark_c14.json).

**State.** `master` = `977158d` (#304, squash). All 17 files of #304's head `e83538d` are byte-identical on it;
#303 (`c1e4d0a`, unrelated) touched no pinned file. All seven verifier gates pass on `977158d`.

**CI on `977158d`** (run [45490073702](https://github.com/eyeszik/agent-mission-control-os/actions/runs/45490073702),
push, attempt 1): all nine jobs `success`, including Backend on PostgreSQL (tenant RLS runs there with
`AMC_EPHEMERAL_POSTGRES_DSN`) and the council step that fails if the upGrowth tests skip.

**CodeQL — `UNDETERMINED`, attribution blocked.** PR #304's `CodeQL` check reported one new medium alert. Timing
puts it in the Actions or JavaScript analysis. The workflow-permission, secret, untrusted-checkout, poisoning and
injection queries cannot match `ci.yml` as written (workflow-level `contents: read`, push/pull_request only, no
secrets), and manual review of the new JavaScript found no matching pattern; that is not proof against CodeQL's
dataflow. No code-scanning API, annotation or SARIF is reachable from this session, and the local CodeQL download
was denied (not retried). Needed to close it: the alert number, rule id and `path:line` from Security → Code scanning.
Nothing was suppressed or dismissed.

**C14 Fairquery — REJECT as an MCP server; its value goes to `security/pii.py`.** An offline benchmark on 29
synthetic cases (seeded generator, no committed credential-shaped strings) measured Fairquery's free local
detectors at 17/19 recall and 0/10 false positives, against 12/19 and 2/10 for `security/pii.py`. AMCOS misses
international phone numbers, IPv4, AWS access key ids and Google API keys, and redacts ISBN/EAN codes as cards
(no Luhn check). As an MCP tool it cannot fill the gap: redaction runs in-process on every audit write, and its
npm dependency tree (99 packages installed with dev tooling; the runtime imports `@modelcontextprotocol/sdk`, `zod` and `libphonenumber-js` modules) cannot be covered by the gateway's file pins (G9). The right change is to harden
`security/pii.py` and its byte-parity TypeScript twin `@amc/pii` (manifest-pinned, 11 runtime callers) — a
redaction-policy change for the owner to approve, not done here.

**C07 OpenSERP — DEFER_PENDING_OWNER_AUTHORIZATION.** The MCP package (`@openserp/mcp` 0.1.12, MIT) has a
self-hosted mode (`http://localhost:7000`) backed by [karust/openserp](https://github.com/karust/openserp) (MIT,
no per-search billing). That removes the spending question but not the policy one: the server drives headless
Chromium against Google, Bing, Yandex, Baidu, DuckDuckGo and Ecosia (with captcha/proxy handling), sends agents'
query text to those engines, and adds a Go + Chromium service. That is the research-provider egress the repository
keeps DISABLED, plus a terms-of-service question for the owner.

**Others.** Unchanged from `candidate_matrix.json`; no new evidence.

## Recommended next step

No further MCP server. The highest-value follow-up is a `security/pii.py` + `@amc/pii` hardening change (Luhn-check
cards; add AWS/Google key and international phone patterns; decide whether IPv4 counts as sensitive), with the C14
fixture as its regression set. It needs the owner's decision because it changes what the system redacts.
