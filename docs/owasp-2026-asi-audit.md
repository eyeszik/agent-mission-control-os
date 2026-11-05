# OWASP 2026 ASI01–ASI10: codebase audit and remediation record

Audited at commit `009ceb3` (the base of this branch), with the working-tree changes listed in §4.
Evidence is cited as `file:line`. A control counts as **COVERED** only when a file and a test exercise
it. **PARTIAL** means real controls exist but at least one stated risk remains. **GAP** means no
control was found.

Honest limits: this is a code-and-test audit. It is not a penetration test, not a threat-model
review with the owner, and not evidence of production behaviour. The gateway and sandbox claims are
about code paths, not about any deployed environment.

## 1. Audit matrix

| ASI | Risk | Status | Existing controls (evidence) | Gaps / residual risk |
|---|---|---|---|---|
| **01 Goal hijack** | Hidden instructions in input, Markdown, HTML or RAG text | **PARTIAL** | Ingest runs `sanitize_input` (`graph/nodes/ingest.py:17`). RAG documents run `injection_findings` and are rejected at `project_os/knowledge.py:99` and `:158`. Pattern set at `knowledge.py:48`. | **Defect found and fixed in this session** (see §2). Heuristic regex only; no Markdown/HTML parser; no hidden-instruction detection beyond phrase lists. |
| **02 Tool misuse** | Unvalidated or over-broad tool calls | **COVERED (strong)** with one addition | Council tool allowlist `council/gateway.py:184` and `:247`; seat scopes (`SCOPE_NOT_GRANTED`); JSON-schema or Pydantic argument validation (`SCHEMA_INVALID`); shell tools disabled (`:249`); approval bound to mission and action hash (`_check_approval`, `:269`) and consumed once (`APPROVAL_REPLAY`, `:276`); redacted audit (`_redacted_args`, `:193`). MCP servers need absolute commands and an explicit tool allowlist (`council/mcp_client.py:54`, `:57`). Actions gateway: risk scoring, budget reservation and approval gates (`actions/gateway.py:248`, `:555`). | Call-volume and repetition bounds were missing. **Added in this session** (§3, `reliability/execution_bounds.py`, wired at `council/gateway.py:258`). |
| **03 Identity / privilege abuse** | Static keys, long-lived or unscoped tokens, agent impersonation | **COVERED (partial)** | User tokens validated per request against Supabase `/auth/v1/user` (`security/auth.py:55-73`). Server-side tenant membership (`auth.py:109`). Approvals bind to the approver (`security/approval_authority.py:46`, `:65`). **Agent-to-tool capability tokens** (`agency/council/capability.py`): short-lived, single-use Ed25519 tokens minted by the gateway per MCP call (`council/gateway.py:307-311`), bound to tool, SHA-256 of arguments, seat, scopes and `jti`. Tool servers verify with the public key only. Verified end to end against a real MCP server (`tests/fixtures/council_mcp_server.py`, `echo_verified`). | Capabilities cover **MCP tools only**. Local gateway tools are still authorised by seat scope, not by a token. The `jti` registry is process-local, so single use holds per worker, not across workers. If `AMC_CAPABILITY_SIGNING_KEY_FILE` is unset the key is per process, so tokens do not verify across restarts. No token-exchange (OBO) flow. |
| **04 Supply chain** | Tampered tool manifests, prompt templates or dependencies | **COVERED (partial)** | **MCP servers SHA-256 pinned** (`council/mcp_client.py`; `MCP_PIN_MISMATCH` 403 at `:123`; pins checked at config and at spawn). Tests: `tests/test_council_gateway.py` (14 passed). Repository integrity manifest with git blob SHA pins (`manifest.json`, 318 files). Exact-version lockfiles (`pnpm-lock.yaml`, `--frozen-lockfile`). UCPO dependency check fails closed (`ucpo/sandbox.py`). | Python dependencies are version-constrained but not hash-pinned. No signed-manifest check for external prompt templates. A file changed between config read and spawn is caught only at spawn. |
| **05 Unexpected code execution** | RCE through shell, code or build endpoints | **COVERED (partial)** | Code sandbox runs under `unshare -rmn` with a **read-only root inside the mount namespace** (`execution_fabric/adapters/code_sandbox.py`, `mount_namespace_available`). Syntax check uses in-memory `compile()`, because bytecode writes are blocked. Tests: `tests/test_sandbox_mount_isolation.py` (real processes: writes to the repo, `/tmp` and home fail; reads succeed) and `test_execution_fabric.py` (60 passed together). Council shell disabled (`council/gateway.py`). UCPO build runs in user, mount and network namespaces, or returns `BLOCKED_ISOLATION` (`ucpo/sandbox.py`). | Depends on the host permitting `unshare`. Where it does not, the sandbox refuses rather than running unconfined. The CVE-2026-33017 mitigation was not located by name and was not verified. |
| **06 Memory poisoning** | Tainted RAG or memory entries; cross-tenant contamination | **COVERED (partial)** | Per-tenant and project scoping (`project_os/knowledge.py`); SHA-256 digest of each document before ingest (`knowledge.py:153`); injection scan and rights gate before storage (`:158`, `:162`). | Digests are computed over `uri + text`, which is good for integrity, but no per-session segmentation of working memory was found. Scanner is heuristic. |
| **07 Inter-agent communication** | Forged or replayed handoffs; unauthenticated inter-service calls | **COVERED (partial)** | HMAC-SHA256 protocol v2 on protected ingress (`security/hmac_ingress.py`): domain, timestamp, nonce and body signed (`signed_material` :65, `verify_v2` :99). 300 s freshness. **Shared nonce store** in the existing DB layer (`security/replay_store.py`, `hmac_replay_nonces`, Postgres migration and SQLite v21), used by default. `memory` is refused with multiple workers. Multi-worker test: 7 passed on each of 3 runs. **mTLS** (`security/mtls.py`): all-or-none configuration, client certificate required at the handshake, launcher wiring in `infra/run/amc-api.sh`. Tests: `tests/test_mtls_transport.py` on synthetic CA chains (trusted client accepted; no certificate refused; other-CA refused). | Synthetic certificates only; no real deployment. Trust is CA-level: any certificate from the configured CA is accepted, so per-service identity needs one CA per trust domain. The app cannot read the peer certificate through uvicorn, so there is no per-CN check. In-process handoffs are not signed. The earlier multi-worker 500s did not reproduce in a fresh environment; their root cause is **unconfirmed**. |
| **08 Cascading failures** | Retry storms, runaway recursion, failing node taking the pipeline down | **PARTIAL** | Model router: bounded attempts (≤ 5), jitter, per-provider cooldown (`agency/model_router.py:291`, `:375`). Durable ticks: `MAX_RETRIES = 3` (`agency/durable/ticks.py:39`). Circuit-state classification (`durable/proofs.py:85`). | **GAP (now addressed):** no bound on recursion depth or repeated tool calls at the tool gateway, and no per-tool circuit breaker there. `project_os/reliability.py:32` records `circuit_breaker` as `NOT_IMPLEMENTED`. The LangGraph recursion limit is not set explicitly. **Added in this session** (§3). |
| **09 Trust exploitation** | Persuasion pressure, unconfirmed high-risk actions | **COVERED (partial)** | Every approval request stores framing evidence (`framing_level`, `framing_codes`) from `security/approval_framing.py:assess()` (URGENCY, PRESSURE_TO_APPROVE, MINIMIZATION, UNSUPPORTED_ASSURANCE, OMITS_TARGET). **Enforced gate:** approving a HIGH summary without `framing_acknowledged=true` raises `FramingAcknowledgementRequired` (`persistence/approvals.py:11`, `:171`) and returns 409 (`api/routes/approvals.py`). Rejection is never gated. Migration `supabase/migrations/20261104_amc_approval_framing_v1.sql`. Tests: `tests/test_approval_framing.py`, including the refusal and acknowledged paths. Contract: `framing_level` and `framing_codes` in the OpenAPI spec and the zod schema; the API returns `framing_codes` as a list. | `assess()` is a **heuristic over text**, not a judgement of truth or intent. It can miss paraphrase and can flag honest urgency. The gate forces a conscious acknowledgement; it does not prove the summary is accurate. No measured false-positive or false-negative rate yet. |
| **10 Rogue agents** | Goal drift, self-replication, unapproved tool use | **COVERED (partial)** | Unapproved tool use is blocked by the allowlist and approvals (ASI02). **Anomaly strikes** in `SessionGuard` (`agency/reliability/execution_bounds.py`): `VELOCITY_EXCEEDED`, `TOOL_SPRAWL`, `GOAL_DRIFT` (against the linked idea's title and description), `REFUSAL_STREAK`, `REPLICATION_DETECTED`. Each strike refuses the call that shows it. **Three strikes halt the session** (`SESSION_HALTED`, HTTP 423). Only `clear_halt(...)` lifts a halt, and it needs a named human owner and a note. It is a library function with **no HTTP endpoint**. Halted guards are never evicted (`SESSION_REGISTRY_FULL` instead). Tests: `tests/test_asi10_anomaly_halt.py`, including a real gateway call refused with 423. | Process-local: a halt does not survive a restart or span workers. Goal drift is a heuristic on English content words, and it is off when no idea is linked (missions carry no objective field). No measured baselines for any threshold. `step_entropy_cap` is still a repetition bound, not entropy. A halt can be lifted only by code, so there is no UI for it. |

## 2. Defects found and fixed in this session

1. **ASI01: sanitizer skipped strings inside lists.** `sanitize_input` only recursed into dicts inside lists, so
   `{"constraints": ["Ignore all previous instructions …"]}` passed through unredacted in the ingest node
   (`graph/nodes/ingest.py:17`). Fixed in `security/sanitize.py`: the recursion now covers every string at
   any depth.
2. **ASI01: script stripping was case-sensitive and single-pass.** `<SCRIPT>` passed through, and
   `<scr<script>ipt>` reassembled a tag after one pass. Fixed: case-insensitive, applied until stable.
3. **Cross-language parity.** The TypeScript twin (`packages/pii/src/sanitize.ts`) mirrored the Python gaps
   by design, and its header said widening "belongs in the Python reference first". I updated Python first,
   then the twin, then regenerated `packages/pii/tests/fixtures/pii-parity.json` through its generator. The
   regenerated diff touches only the `sanitize` section (verified by comparing JSON sections).

## 3. Controls added (ASI03 / ASI04 / ASI05 / ASI07 / ASI08 / ASI09 / ASI10)

| Control | Where | Enforces |
|---|---|---|
| Session execution guard | `agency/reliability/execution_bounds.py` | Depth, call budget, session timeout, identical-argument repetition, per-tool circuit breaker (ASI08). |
| Anomaly strikes and halt | same | Velocity, tool sprawl, goal drift, refusal streak, replication. Three strikes halt the session. Owner-keyed `clear_halt`. Halted guards never evicted. |
| Gateway integration | `agency/council/gateway.py` (`invoke`) | Guard admission before any effect; objective terms from the linked idea; 423 for halted sessions, 429 for other bounds. Refusals audited as `DENIED`. |
| Capability tokens | `agency/council/capability.py`, `mcp_client.py` | Gateway mints Ed25519 tokens per MCP call and verifies them before the approval is consumed. Tool servers hold only the public key. |
| MCP pinning | `agency/council/mcp_client.py` | SHA-256 pins for every command and file argument; a mismatch is refused. |
| Sandbox mount isolation | `agency/execution_fabric/adapters/code_sandbox.py` | Read-only root in a mount namespace; in-memory compile check. |
| Shared replay store | `security/replay_store.py`, `hmac_ingress.py`, `persistence/database.py` | Nonces in the shared DB layer, used by all workers. |
| mTLS | `security/mtls.py`, `infra/run/amc-api.sh` | Client certificate required at the TLS handshake when configured. |
| Approval framing | `security/approval_framing.py`, `persistence/approvals.py`, `api/routes/approvals.py` | Framing evidence stored per request; HIGH approvals need explicit acknowledgement (409 otherwise). |
| Payload integrity contract | `agency/state_contract/__init__.py` | Canonical SHA-256 per payload, `PayloadIntegrityError`, quarantine and rollback. |

Limits, stated plainly:

- The spec's `step_entropy_cap = 0.05` has no operational definition. It is a bound on identical repeated calls, **not** Shannon entropy.
- Guard state, capability `jti` memory and halts are process-local. Only the HMAC replay store is shared across workers today.
- A tripped guard refuses calls and can halt a session. It does not terminate the agent process.
- The payload digest covers `content` only, as the contract specifies.

## 4. Remaining gaps, ranked by risk

1. **ASI10 persistence:** halts and strikes are process-local. Persist them through the DB layer before relying on halts in a multi-worker deployment.
2. **ASI03 scope:** local gateway tools are not capability-gated. Extend the token check to them, or accept seat scope as the control for them explicitly.
3. **ASI09 heuristic:** framing detection is text-pattern based. Measure false positives and negatives on a labelled set before treating it as a content control.
4. **ASI10 baselines:** every anomaly threshold is a reviewed starting point. Collect measured baselines before tuning.
5. **ASI07 multi-worker 500s:** an earlier run showed 8 server errors under concurrent startup. They did not reproduce after an environment reset (3 consecutive passes). The root cause is **unconfirmed**. Reproduce under concurrency and read the traceback before changing code.
6. **ASI04 Python dependencies:** not hash-pinned.
7. **ASI01 hidden content:** Markdown and HTML parsing before scanning, not only regex.
8. **Not done in this turn:** the Northline run and the brand descendant tests remain blocked (see `docs/amcos-unified-production-status.md`). No named brand descendant test exists; `test_vnexus_intelligence.py` is an unconfirmed match.
9. **Browser QA:** the Chromium used is a stand-in (`scripts/qa/provision-qa-chromium.sh`), not Playwright's own build. It has no WebGL, so `test_abc_v6.py::test_t11...` fails. CI must use Playwright's Chromium.
10. **Narration:** no local TTS, so narration is timed silence and a FreeVideoForge "good render" fails the strict audio gate. The fix is a real TTS engine.

## 5. Verification

### Run record (final, this environment)

| Check | Command | Result |
|---|---|---|
| Full backend suite | `pytest services/langgraph/tests -q` | **2061 passed, 62 skipped, 1 failed** (58 min) |
| The one failure | `test_abc_v6.py::test_t11_browser_executes_shaders...` | `NO_WEBGL_CONTEXT`: the stand-in Chromium exposes no WebGL. Environment limit, not a shader defect. Left failing on purpose. |
| Browser QA gate (real browser) | `pytest test_ucpo_build.py` | 5 passed, no skips |
| Multi-worker replay | `pytest test_hmac_replay_shared.py` (3 runs) | 7 passed each run |
| mTLS transport | `pytest test_mtls_transport.py` | passed (synthetic CA chains) |
| Capability tokens | `pytest test_capability_tokens.py` | passed, including end-to-end MCP verification |
| ASI10 halt | `pytest test_asi10_anomaly_halt.py` | passed (includes gateway 423) |
| ASI09 framing | `pytest test_approval_framing.py test_approvals.py test_avic_contracts.py` | 10 passed |
| FreeVideoForge with ffprobe | `FVF_FFPROBE=<ffprobe> pytest` | 182 passed, 1 failed (silent narration, item 10), 1 skipped |
| FreeVideoForge without ffprobe | `pytest` | 144 passed, 40 skipped |
| Repository gates | `verify_repository_invariants`, `verify_production_readiness`, `verify_auth_bindings`, `verify_ontology_parity`, `verify_design_tokens`, `verify_manifest`, `verify_guidance_registry` | all exit 0 |
| Lint gate | `ruff check --select E4,E7,E9,F` on changed Python | clean |

Skipped tests are environment gates: local video and image backends (`NOT_APPLICABLE`; no ComfyUI at `127.0.0.1:8188`) and other unavailable-host gates.
