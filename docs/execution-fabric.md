# Execution fabric

Source spec: `EXECUTION_FABRIC_MASTER_FRAMEWORK`, built on `feat/method-router-delegation-60c58d7c@f371bdc1`.

The execution fabric is the governed execution plane that the planners lacked. The planners stop at waves, and before this layer both compiled planners ended in `EXECUTOR_GAP`. The fabric consumes those waves and turns eligible cells into ProjectOS artifact versions, backed by permits, receipts and observations. Every other cell gets a truthful state instead of a blanket gap.

```
compiled.planner / compiled.method_mission         (unchanged; still plan-only)
 → execution_fabric.schedule   (read adapter; recomputes the wave plan to prove freshness)
 → execution_fabric.consumer   (eligibility → collision split → 2-phase WAL → dispatch → commit)
     → agency.skills.dispatcher.dispatch_skill    (canonical N3 capability gate)
     → persistence.projects.create/revise_project_artifact   (ProjectOS/N4, optimistic concurrency)
     → persistence.proofs   (DispatchPermit, ExecutionReceipt, ObservationReceipt, FailureFingerprint)
     → persistence.idempotency   (reservation = WAL intent)
 → MissionExecutionReport + release boundary (N2 release_guard_failures)
 → execution_fabric.coverage   (coverage graph, autonomy envelopes, cross-modal witness)
```

## What is reused, and what is new

| Concern | Owner |
| --- | --- |
| Waves, cells, cell transitions | **reused:** `compiled.execution.schedule_waves` / `advance_cell` |
| Capability authorization | **reused:** `skills.dispatcher.dispatch_skill`; `Skill` gained metadata only |
| Role output authorization | **reused:** N3 `get_role` / `assert_role_may_produce` |
| Artifacts, versions, dependency invalidation | **reused:** ProjectOS `create_project_artifact` / `revise_project_artifact(expected_version=)` |
| Permits and receipts | **reused:** trust-kernel `DispatchPermit` / `ExecutionReceipt` / `ObservationReceipt` / `FailureFingerprint` |
| Idempotency | **reused:** `persistence.idempotency.reserve_idempotency` |
| Release gating | **reused:** N2 `release_guard_failures` (the fabric never releases) |
| Injection screening | **reused:** `compiled.role_sources.scan_for_injection` |
| DTCG, SVG, contrast, video contract | **reused:** `design_tokens`, `assets.render_logo_svg`, `ui_ux.tokens.wcag_contrast_ratio`, `project_os.video` |
| Execution contracts, consumer, adapters, read models | **new:** `agency/execution_fabric/` |

Nothing canonical was modified except `dispatcher.py`. That change is additive, and dispatch authorization is unchanged:

- `Skill` gained `side_effect_class`, `sandbox_requirement`, `provider_requirement`, `validator_ids` and `timeout_class`, all validated at construction.
- `register_skill` refuses to redefine an existing skill id.

## Truthful states

`ExecutionState` lists the states a cell can report:

- `EXECUTABLE`, `EXECUTING`, `SUCCEEDED`, `FAILED`
- `BLOCKED_AUTHORITY`, `BLOCKED_TOOL`, `BLOCKED_PROVIDER`, `BLOCKED_DEPENDENCY`, `BLOCKED_CONTRACT`, `BLOCKED_POLICY`
- `NEEDS_HUMAN`, `PROVIDER_GAP`

Every reason is a stable code, and the cell's state is the most fundamental reason, in this precedence:

1. authority
2. policy
3. contract
4. human
5. dependency
6. tool
7. provider
8. gap

Unknown codes fail closed to `BLOCKED_POLICY`.

| Provider situation | State |
| --- | --- |
| Not installed in this repository: `llm_drafting`, `t2i`, `ai_video` | `PROVIDER_GAP` |
| No search-data provider (`search_volume`) | `GAP_NO_SEARCH_PROVIDER` (state `PROVIDER_GAP`) |
| Installed but unreachable (e.g. `zo` disabled) | `BLOCKED_PROVIDER` |
| Missing local binary (`ffprobe`) or network namespace | `BLOCKED_TOOL` |

**Why `llm_drafting` is a gap.** Layer 1's `generate_structured` is bound to its own node schemas. Reusing it for arbitrary N1 artifact types would be an unreviewed provider adapter, so every authored-text artifact reports `PROVIDER_GAP:llm_drafting`.

## Execution contracts (`contracts.py`)

**`ExecutionContext.from_server(...)`** is the only way facts enter execution.

- Mode is `LOCAL` or `SANDBOX`. `LIVE` raises `ExecutionModeError`, because external execution stays LIVE_GATED.
- A client payload may carry only `objective`, `notes` and `inputs`. Any authority-shaped key raises `ClientAuthorityInjection`, as do unknown keys. Authority-shaped keys include `authority_refs`, `approval_refs`, `grants`, `mode`, `tenant_id`, `role_id` and `spend_authorized`.
- A work order holding authority or approval refs that the server context did not issue is blocked (`AUTHORITY_*_NOT_SERVER_ISSUED`).

**`ExecutionRequest`** binds one dispatch to its:

- work order;
- contract hash (the PCWO `work_order_hash`);
- context hash (the capsule hash);
- dependency hashes;
- input hash;
- idempotency key `hash(tenant, project, mission, work_order, contract_hash, input_hash)`.

The reservation scope is per tenant, so identical missions in two tenants never collide or replay each other (EC9).

**`FabricPermit`** wraps the trust kernel's `DispatchPermit` with the tenant, the contract and context hashes, the key, and `expires_at`. `verify_permit` rejects a mismatched subject or tenant, an expired permit, and a permit issued in the future beyond the skew allowance (EC11).

## Wave execution consumer (`consumer.py`)

For each wave the planner emitted:

1. **Freshness.** The wave plan is recomputed with the same scheduler. A different `wave_hash` refuses the whole mission (`STALE_WAVE_PLAN`), and nothing is written. Each cell's recorded input hashes are rechecked against the graph (`STALE_INPUT`).
2. **Eligibility.** The fabric checks, in turn:
   - planner and work-order blockers, and held cells;
   - upstream outcomes;
   - server-issued authority;
   - the N3 role contract and the skill's capability;
   - the skill binding (its declared output must equal the cell's contract);
   - provider and sandbox availability;
   - the side-effect ceiling;
   - the invocation budget;
   - an injection scan of every string in the payload, whether from server inputs, client notes or upstream artifacts.

   Flagged content is quarantined (`INJECTION_QUARANTINED`, EC6) and never dispatched.
3. **Collision split (T6).** Cells in one wave that share a mutation target, resource lock or artifact identity go into separate sub-waves. ProjectOS optimistic concurrency (`expected_version` = the pre-image version captured at preparation) catches anything that slips past, such as a human editing the same artifact mid-run. The result is `STALE_WRITE_COLLISION`, and the other write is never lost.
4. **Two-phase write-ahead (T1).**
   - *Intent:* reserve the key, then persist the permit. The permit's `dependency_version_refs` records the target artifact's pre-image (`target:<artifact>@v<n>`).
   - *Execute:* non-colliding cells dispatch concurrently on a thread pool. Handlers are pure and touch no database.
   - *Commit,* serially and in cell order:
     1. run the validators;
     2. persist the artifact with `provenance_ref = execution:<key>`;
     3. write the `ExecutionReceipt`;
     4. read the stored bytes back and compare SHA-256 for the `ObservationReceipt`;
     5. complete the reservation.

   Object writes are content-addressed and atomic (temporary file plus rename) in the existing `LocalStorageAdapter`.
5. **Reconcile before retry (EC5).** An uncommitted reservation older than `lease_seconds` is compared with the permit's pre-image. Inside the lease it is left alone (`EXECUTION_IN_PROGRESS_ELSEWHERE`).

   | What the reconciler finds | Action |
   | --- | --- |
   | Head version still equals the pre-image | Nothing landed: release the reservation, record `RECOVERING`, retry. |
   | Head's provenance names this key | The write landed: adopt it. No second version is written. |
   | Anything else | Halt with `RECONCILE_DIVERGENT`. |

**Bounded control.** At most `min(work-order max_attempts, 3)` attempts are made. The same failure fingerprint twice trips the circuit breaker and goes to a human (`NEEDS_HUMAN`). A validation failure is `FAILED` and is not retried: the producer must change. Output size and invocation count are budgeted (`BUDGET_EXCEEDED:*`).

**Consequential side effects are never dispatched.** A `REVERSIBLE_WRITE` or `IRREVERSIBLE_WRITE` cell without an approval is `NEEDS_HUMAN`. With an approval it is `BLOCKED_POLICY` (`LIVE_GATED:*`), because no live executor exists. Every fabric skill is `DRAFT` or below.

**Release boundary.** For each deliverable, the report evaluates N2 `release_guard_failures` over the execution facts. With every upstream cell succeeded, the state is `NEEDS_HUMAN` (`approval_missing`, `brand_safety_failed`), and an `APPROVAL_REQUIRED` project event is appended. The fabric never creates an approval, decides one, or releases anything.

**Determinism.** `MissionExecutionReport.outcome_hash` covers states, reasons, artifact refs and content hashes. Running a mission again replays every succeeded cell from the reservation, gives the same outcome hash, and adds no new version.

## Domain sandbox adapters (`adapters/`)

| Domain | Skill | Real behaviour | Gap reported |
| --- | --- | --- | --- |
| Branding / design | `brand_logo_svg`, `dtcg_token_compile` | Deterministic SVG mark via `render_logo_svg`. Tiered DTCG 2025.10 tokens via `design_tokens`. Validators: SVG safety (no script, handlers, external href or DTD), palette conformance (CIE76 ΔE ≤ 2.3), DTCG recompile byte-equality. | `t2i_image_generate` → `PROVIDER_GAP:t2i` |
| UI/UX | `design_system_spec_compile`, `uiux_dom_audit` | Colour pairs with WCAG 2.2 AA verdicts, plus a DOM-audited preview. The headless audit (stdlib parser) covers `lang`, viewport, inline-style contrast, `img` alt, target size ≥ 24 px (SC 2.5.8) and fixed widths over 360 px (reflow). | Computed-style cascade, media-query reflow, focus order and keyboard operability are listed as **not verified**. |
| Code | `code_patch_sandbox` | See the list below this table. | No read-only overlay, seccomp or socket proxy; this is reported in the output. |
| Cinematic | `fvf_ingest_verify` | Validates FreeVideoForge's seven-file contract (refusing runs without zero paid spend). `ffprobe` then measures duration (±0.25 s), codec, fps, frame count (≈ duration × fps ± 1) and optional BT.709 primaries. The master's SHA-256 and FreeVideoForge's own reproducibility guarantee are recorded. | Without `ffprobe`: `TOOL_UNAVAILABLE:ffprobe`. AI video: `PROVIDER_GAP:ai_video`. |
| SEO | `seo_audit` | Local checks over a supplied page set: title and description length (configurable heuristics), exactly one h1, canonical, lang, viewport, image alt, and internal links resolving within the set. | Search demand is always `GAP_NO_SEARCH_PROVIDER`, with no estimated numbers (a validator enforces this). |

The code sandbox:

- uses a fresh temporary copy and never touches the repository;
- accepts relative POSIX `.py` paths only, checked segment by segment (`..`, `.`, absolute, backslash and NUL are rejected);
- produces an AST structural diff, and rejects unparseable patches;
- allows only allowlisted commands (`py_compile`);
- runs them with a scrubbed environment (no inherited keys or proxies);
- applies `RLIMIT_AS`, `CPU`, `NOFILE` and `FSIZE` through an exec shim, not `preexec_fn`;
- runs inside `unshare -rn`, a Linux network namespace (EC7).

## Read models (`coverage.py`)

- **`coverage_graph`** builds the chain ContractRequirement → AcceptanceTest → MethodPlanNode → WorkOrder → Skill → ArtifactVersion → Validator. A missing link is an orphan, and the graph is then `PLAN_INCOMPLETE`. A complete chain that is not fully executed is `EXECUTION_INCOMPLETE`; otherwise it is `COVERED`.
- **`derive_envelope`** derives an `AutonomyEnvelope` per cell. It is the intersection of the work order's side-effect class, the skill's class, the `DRAFT` ceiling, and the server-issued refs, and `live_external_actions` is always `False`. `envelope_within_canonical` proves the derived envelope is never wider than the canonical permissions.
- **`BrandContextCapsule`** (in `capsules.py`) is the one hash-sealed set of brand facts. Its hash enters every input hash, so semantic drift (EC4) produces a new key and an optimistic-concurrency revision rather than a stale replay.
- **`cross_modal_witness`** checks that every produced modality uses the capsule palette within ΔE and names the brand.

## Running it

```bash
python3 orchestrate_brand_pipeline.py fabric-run --input sample_fabric_mission.json   # or: make fabric-run
```

This is the golden mission. It compiles a `design_token_set` and a `design_system_spec` deliverable over existing upstream artifacts, then executes both cells. Both reach `SUCCEEDED`, and both deliverables stop at `NEEDS_HUMAN`. Exit codes: 0 means everything succeeded and stopped at the human boundary, 1 means anything was blocked, failed or a gap, and 2 means unreadable input or `LIVE` mode.

Unlike the planning commands, this command **writes** ProjectOS artifacts, receipts and events to the configured database.

## Edge cases

| Edge case | Handling |
| --- | --- |
| EC1 hydration non-determinism | Not applicable: no frontend surface was added. |
| EC2 wave commit races | Commits are serial and in cell order. Collisions are split into sub-waves, and optimistic concurrency catches outside writers. |
| EC3 missing BTF for eBPF | Not applicable: no eBPF is used. Isolation is a network namespace plus rlimits, and is reported as observed. |
| EC4 semantic drift | The capsule hash is in the input hash, so a new key forces a revision. The cross-modal witness checks the result. |
| EC5 partial WAL crash | Permit pre-image reconciliation, as above. |
| EC6 prompt injection | Every payload string is scanned, and flagged content is quarantined. |
| EC7 OOM in Chromium/FFmpeg | Sandbox rlimits and timeouts. Chromium is not used. `ffprobe` has a 120 s timeout. |
| EC8 supply chain | No new dependencies. sharp is pinned to ≥ 0.35.5 for GHSA-wq5f-xc86-pv6w in a separate commit. |
| EC9 idempotency collisions across tenants | Tenant-scoped reservations, with the tenant inside the key hash. |
| EC10 graph deadlocks | Waves are acyclic and processed once in order. Upstream failure blocks dependants with reasons, so nothing waits. |
| EC11 clock desync on permits | The `expires_at` and future-issue checks use an allowed skew, and the clock is injectable. |

## Not implemented, and why

- **Kernel isolation beyond a network namespace.** Read-only overlay filesystems, seccomp and socket proxies are not present, and the sandbox reports them as `false`.
- **"Spectral" AST comparison and Zhang–Shasha DOM tree distance.** The implemented verifiers are an AST node-type multiset distance with changed-definition sets, and a Levenshtein distance over pre-order tag sequences. Both are named exactly.
- **Byte-identical re-render (T7).** FreeVideoForge renders out of band, and this host has no FFmpeg. The fabric verifies a finished render's declared shape and records its hash and FreeVideoForge's own guarantee. It does not claim reproducibility.
- **Text, image and video generation.** No provider adapters are installed, so these are `PROVIDER_GAP`, never simulated.
- **An API route.** The fabric writes artifacts. Exposing it over HTTP needs an auth binding and tenant-membership review, so it is left for a reviewed change. The CLI and Python API are the entry points.
- **Mutants X1–X30.** The source framework named them only by example. `tests/test_execution_fabric.py` defines thirty concrete mutants, each derived from a stated invariant or edge case, and every one is killed.
