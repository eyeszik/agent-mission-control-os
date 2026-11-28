# AMCOS unified production: implementation status (branch `arena/91f7ec9b-agent-mission-control-os`)

Status: **PARTIAL**. This session delivered a verified slice of the production contract, not the full
brief→release→delivery chain. Specification ≠ code ≠ service; local tests ≠ live activation; nothing here
was deployed, published, spent, or pushed to GitHub.

Base: `master` @ `009ceb336fdb6bde5f71660129f26201d6009c11`. Scope boundary: local code, config and docs only.

Evidence terms used below:

- **EXISTING_VERIFIED**: the owning module exists and its named test module passed in the full backend run
  (see §4). Behaviour-specific coverage was not re-audited line by line this session.
- **IMPLEMENTED**: added and tested in this session.
- **PARTIAL**: some of the requirement exists or is implemented; named gaps remain.
- **BLOCKED**: needs a tool, provider, host permission or authority this sandbox does not have. Reason given.
- **DEFERRED**: not started in this session. Reason and approval implications given.

---

## 1. Implemented changes

| # | Change | Files | Why |
|---|---|---|---|
| 1 | Documented three env vars read by the code but missing from `.env.example`: `AMC_INNOVATION_SOLO_OWNER_APPROVAL`, `AMC_INNOVATION_SOLO_OWNER_MODEL`, `OLLAMA_NO_CLOUD`. Each entry states its local-only guard. | `.env.example` | Baseline failure `test_every_environment_variable_the_code_reads_is_documented` (introduced by commit 009ceb3). |
| 2 | Re-pinned `.env.example` in `manifest.json` with the prescribed blob-SHA script. Only that entry changed. | `manifest.json` | Required by the integrity gate. |
| 3 | Aligned the UCPO website generator to the audited Next.js pin `16.4.3` (was `16.4.2`). `verify_repository_invariants.py` already requires `16.4.3`, and `docs/innovation/solo-owner-policy.md` records the same drift. | `services/langgraph/agency/ucpo/source.py`, `services/langgraph/tests/test_ucpo_pipeline.py` (one assertion), `docs/ucpo/repository-audit.md` | Once `apps/web/node_modules` was installed, the sandboxed build failed its fail-closed `dependency_check`. The failure was a real version mismatch. The assertion that encoded the stale value was updated; it was not weakened. |
| 4 | Browser-QA tests now skip with an explicit `NOT_RUN` reason when Playwright Chromium is absent. The probe reuses `agency/ucpo/qa.py::_playwright_paths()`. CI installs Chromium, so these tests still run there. The tampered-source test (no browser needed) keeps only the sandbox gate. | `services/langgraph/tests/test_ucpo_build.py` (+ manifest re-pin) | The Chromium download host is outside the sandbox allowlist, so the QA cannot be executed here. A `FAIL` would misreport an environment limit as a product defect. |
| 5 | **Exact timeline timing contract** (new package): rational timebase (`num/den` fps, 1–240), frame-exact seconds→frames (no floats, no silent rounding), clip transitions (`cut`/`dissolve`), overlap accounting `total = Σdur − Σoverlap`, structural rules (no duplicate IDs, overlap shorter than both neighbours, must end on a `cta`, must carry a `message`/`headline`), cutdowns that may only **trim** master shots, exact target length, canonical content hash. | `services/langgraph/agency/timeline/__init__.py` | Contract E requires transition accounting (6×5s−5×0.4s=28s) and frame verification. No existing module modelled transitions (`agency/vnexus/video.py` is cut-only). Pure arithmetic; no media, no provider. |
| 6 | 18 tests for (5): the 28 s example; a frame-exact 30 s master (6×160f − 5×12f = 900f at 30 fps); two 15 s cutdowns that keep message + CTA and trim only; rejection of truncation, extension, wrong length, unknown source, mismatched master/timebase, misaligned 0.4 s at 24 fps, float input, unsafe IDs, and hash drift. | `services/langgraph/tests/test_timeline_timing.py` | Meaningful tests for the new module. |
| 7 | This status document. | `docs/amcos-unified-production-status.md` | Traceability and handoff (M02/W16). |

Design note on the contract's timing example: "6×5s−5×0.4s=28s" is a valid arithmetic check and is tested
as such. It is **not** a 30 s film. The 30 s reference master uses 6×160 frames at 30 fps. The module rejects a
28 s timeline against a 30 s target, which is the intended behaviour.

---

## 2. Requirement and Q01–Q38 coverage

### 2a. Q01–Q38 dispositions

| Q | Subject | M IDs | Disposition | Evidence / gap |
|---|---|---|---|---|
| Q01 | needs / request | M03, M05 | EXISTING_VERIFIED | `agency/intake` governed intake mission; `test_intake_mission.py`. M03 field set (rights, missing inputs) not audited. |
| Q02 | counterevidence | M04 | DEFERRED | No counterevidence model. Needs strategy-evidence schema (claims/evidence/counter). No fabricated results. |
| Q03 | finite scope | M05 | DEFERRED | No deliverable-contract module for quantity/format/acceptance. |
| Q04 | omissions | M02, M16 | DEFERRED | Requirement traceability exists only inside UCPO (`data-req`). No cross-stage omission check. |
| Q05 | brand representation | M06 | EXISTING_VERIFIED (partial) | `test_brand_core.py`, `test_brand_production_foundation.py`. No versioned brand record that feeds other stages. |
| Q06 | invariants | M07 | EXISTING_VERIFIED (partial) | Series invariants in `agency/prompt_families`; `test_prompt_os.py`. No per-channel invariant matrix. |
| Q07 | traits→decisions | M07 | DEFERRED | Not implemented. |
| Q08 | propagation | M11, M21 | DEFERRED | Only genome-dependency invalidation (`agency/foundry`, `test_foundry.py`). No brand-revision propagation. |
| Q09 | distinct concepts | M08 | EXISTING_VERIFIED | `agency/creative` bounded concept search; `test_creative_runtime.py`. |
| Q10 | creative risk / hard gates | M08 | EXISTING_VERIFIED | Non-compensable hard gate in `agency/creative` (documented); `test_creative_runtime.py`. |
| Q11 | blind review | M08 | EXISTING_VERIFIED | Lineage-blind critics (`agency/creative`); `test_creative_runtime.py`. Independence limits are not stated as evidence. |
| Q12 | cross-media | M07, M09 | DEFERRED | No cross-media adaptation layer. |
| Q13 | executable paths | M09, M26 | EXISTING_VERIFIED (partial) | `agency/execution_fabric` (LOCAL/SANDBOX only, provider gaps reported); `test_execution_fabric.py`. |
| Q14 | production methods | M26, M31 | BLOCKED | Local render needs ffmpeg, Blender or Chromium. None are installed (`ffmpeg`, `blender`, `chromium` absent). Diffusion/hosted generation: no authorized provider. |
| Q15 | asset-specific completion | M09, M26 | BLOCKED | Depends on Q14. No per-asset completion evidence produced in this session. |
| Q16 | forgotten essentials | M04, M05 | DEFERRED | Requires the deliverable contract (Q03). |
| Q17 | UCPO mapping | M21, M22 | DEFERRED (mapping) | UCPO builds from its brief (`agency/ucpo`, `test_ucpo_pipeline.py`, `test_ucpo_contracts.py`: EXISTING_VERIFIED). The brand-version → brief mapping with no re-entry is not implemented. |
| Q18 | buyer journeys | M22, M23 | DEFERRED | No journey model. |
| Q19 | functioning pages | M22, M23 | BLOCKED | Sandboxed build now **PASSES** (`test_ucpo_build.py`, `typecheck`+`next build` in namespace isolation). Browser QA (axe, reflow, keyboard, console) **NOT_RUN**: Chromium cannot be downloaded in this sandbox. |
| Q20 | client isolation | M24 | DEFERRED | No client workspace/credential separation implemented beyond tenant scoping. |
| Q21 | provider translation | M25 | EXISTING_VERIFIED (partial) | Cinematic prompt compilers (`agency/cinematic`, `test_cinematic.py`). No verified live provider dialect; translation-loss report not audited. |
| Q22 | composition | M29, M30 | EXISTING_VERIFIED (partial) | `ShotIR` framing fields (`ShotSize`, `CameraAngle`, `LensIntent`) in `cinematic/schemas.py`. Prompt-level only. |
| Q23 | provenance | M27 | EXISTING_VERIFIED (partial) | `GenerationOutcome.provenance` and `ace_evidence`; `test_ace_provenance.py`. No media-hash lineage. |
| Q24 | reuse | M28 | EXISTING_VERIFIED (partial) | Creative capability registry reuse dispositions (`test_creative_runtime.py`). Reuse rights/expiry: DEFERRED. |
| Q25 | treatment | M29 | DEFERRED | `cinematic/story.py` exists but is not connected to a timed shot graph. |
| Q26 | shot graph | M09, M29 | IMPLEMENTED (timing only) | `agency/timeline`: exact starts, transitions, totals, cutdown validation (`test_timeline_timing.py`, 18 tests). Missing: shot composition, rights and reference fields on the timeline. |
| Q27 | T2V detail | M30, M31 | BLOCKED | No authorized hosted T2V provider. Cinematic terminates at prompts by design (`agency/cinematic/CLAUDE.md`). |
| Q28 | continuity | M32 | BLOCKED (media) | Prompt-level continuity handshakes exist (`cinematic/continuity.py`). Media-level continuity needs generation providers. |
| Q29 | alternatives | M08 | EXISTING_VERIFIED | Bounded concept search (population ≤ 4, generations ≤ 2); `test_creative_runtime.py`. |
| Q30 | local repair | M08, M32 | EXISTING_VERIFIED (creative only) | ≤ 1 correction checked by TriDiff in `agency/creative`. Media local repair: BLOCKED (Q14). |
| Q31 | synchronization | M33 | IMPLEMENTED (timing only) | Frame-exact dissolves and totals (`agency/timeline`). Audio, caption and VO sync: DEFERRED (no finishing stage). |
| Q32 | finished film | M31, M33 | BLOCKED | No renderer or encoder in this sandbox. **No 30 s film has been produced.** The contract-level timing for it is tested. |
| Q33 | ambiguous effects | M10, M37 | EXISTING_VERIFIED | Ambiguity pauses intake; publish, spend and send are never dispatched (`docs/intake-mission.md`, `test_intake_mission.py`). |
| Q34 | budget | M19 | DEFERRED | Existing cost and rate limits (`test_cost_and_rate_limits.py`, EXISTING_VERIFIED). No transactional cross-worker reservations, rolling caps or uncertainty reserves. |
| Q35 | authority | M37 | EXISTING_VERIFIED | `security/approval_authority.py`; `test_approval_authority.py`, `test_approvals.py`. Exact artifact-action-target binding not re-audited. |
| Q36 | portability | M34 | DEFERRED | No editable-source package, OTIO or C2PA. |
| Q37 | learning | M40 | DEFERRED | No baselines exist. Observability already reports `NOT_MEASURED` (`agency/durable/observability.py`), which is the correct stance. |
| Q38 | unsupported handoff | M10, M18 | EXISTING_VERIFIED (partial) | UCPO `CAPABILITY_GAP` for generation providers; cinematic stops at prompts (CLAUDE.md contracts). |

### 2b. Mandatory M-register status (M01–M42)

| M | Status | Note |
|---|---|---|
| M01 Assessment | PARTIAL | Repo, owners, baseline and gates captured in §4. |
| M02 Traceability | PARTIAL | This document. No machine-checked requirement graph. |
| M03 Intake | EXISTING_VERIFIED (partial) | Intake mission. |
| M04 Strategy | DEFERRED | |
| M05 Deliverable contract | DEFERRED | |
| M06 Brand | PARTIAL | Brand modules exist; no versioned brand record feeding production. |
| M07 Adaptation | DEFERRED | |
| M08 Creative direction | EXISTING_VERIFIED (partial) | Hard gates, blind critics, bounded search. |
| M09 Production graph | PARTIAL | Timing graph only. |
| M10 Handoffs | DEFERRED | Schema validation before expensive dispatch not generalised. |
| M11 Revision | DEFERRED | |
| M12 Worker | DEFERRED | Durable runtime exists; **no worker is deployed and `RuntimeActive` stays false** (`agency/durable/CLAUDE.md`). |
| M13 Reliability | PARTIAL | Fenced leases, write-ahead intents and at-least-once semantics exist in `agency/durable` (EXISTING, not re-audited). |
| M14 Cancellation | DEFERRED | |
| M15 Isolation | PARTIAL | UCPO sandbox probe demonstrated here (`unshare -rmn`). Other paths not reviewed. |
| M16 Engineering | DEFERRED | Isolated patch/executor not built in this session. |
| M17 Retrieval | DEFERRED | |
| M18 Routing | EXISTING_VERIFIED (partial) | `agency/model_router.py`; `test_ace_model_router.py`. |
| M19 Budgets | DEFERRED | See Q34. |
| M20 GitHub | DEFERRED | No webhook or draft-PR flow built. Not activated. |
| M21 Brand→web | DEFERRED | See Q17. |
| M22 Web | PARTIAL | Sandboxed build passes; browser QA BLOCKED. |
| M23 Function | BLOCKED | Needs browser QA. |
| M24 Client isolation | DEFERRED | |
| M25 Prompt compiler | EXISTING_VERIFIED (partial) | |
| M26 Asset production | BLOCKED | Q14. |
| M27 Provenance | PARTIAL | |
| M28 Reuse | DEFERRED | |
| M29 Film | DEFERRED | |
| M30 Prompts | PARTIAL | Cinematic prompt compile exists; no per-shot specification set. |
| M31 Media execution | BLOCKED | No authorized live provider; no local renderer installed. |
| M32 Continuity | BLOCKED | Q28. |
| M33 Finishing | DEFERRED | Timing only. |
| M34 Portability | DEFERRED | |
| M35 Dashboard | DEFERRED | |
| M36 Events | DEFERRED | Existing SSE replay (`test_events.py`) is EXISTING_VERIFIED for runs. |
| M37 Governance | EXISTING_VERIFIED (partial) | |
| M38 Delivery | DEFERRED | |
| M39 Observability | PARTIAL | Existing opt-in OTel and local telemetry. No Datadog ingestion (no endpoint or credentials). |
| M40 Learning | DEFERRED | |
| M41 Operations | PARTIAL | §5 setup/run/recovery. |
| M42 Acceptance | DEFERRED | Not executed end-to-end. |

### 2c. Work packages

| W | Status | Note |
|---|---|---|
| W01 inventory / baseline | PARTIAL | §4. |
| W02 engagement / deliverable / brand contracts | DEFERRED | |
| W03 handoffs / DAG / versioning | PARTIAL | Timing DAG only. |
| W04 worker / admission / leases / cancel | DEFERRED | |
| W05 isolated engineering executor | DEFERRED | |
| W06 router / budgets / retrieval / MCP | DEFERRED | |
| W07 strategy / creative / brand connections | DEFERRED | |
| W08 UCPO / web / landing-page journeys | PARTIAL | Build passes; browser QA BLOCKED. |
| W09 image / design / provenance | DEFERRED | Deterministic visual engine exists; blocked by missing tools here. |
| W10 cinematic / references / continuity / prompts | PARTIAL | Prompt-only by design. |
| W11 media / edit / audio / captions / cutdown | PARTIAL | Cutdown timing contract only. |
| W12 dashboard / approval integration | DEFERRED | |
| W13 delivery / portability / observability / operations | DEFERRED | |
| W14 E2E / adversarial / recovery | DEFERRED | |
| W15 GitHub / external activation preparations | DEFERRED | |
| W16 regression / coverage / evidence handoff | PARTIAL | §4 and this document. |

---

## 3. End-to-end demonstration evidence

**Not achieved.** The contract's connected chain (brief → strategy → approved brand → UCPO site → 30 s film →
manifest → brand revision → selective rebuild) was not run. The reference engagement (Northline Workflow
Studio) was not produced.

What was demonstrated, with evidence:

- **Timing contract (synthetic, no media):** a 6 × 5 s timeline with 5 × 0.4 s dissolves = 28 s (840 frames at 30 fps).
  A 30 s master = 6 × 160 f with 5 × 12 f dissolves = 900 f. Two 15 s cutdowns = 450 f each, trims only, both
  ending on the CTA. Source: `services/langgraph/tests/test_timeline_timing.py`, all passing.
- **UCPO sandboxed build (synthetic brief):** `test_ucpo_build.py::test_build_refuses_tampered_source_before_running_anything`
  passes in the final run. In the run immediately after the Next pin fix, the defective-generator test's build step
  returned `PASSED` (its assertion on `result.status` held) before browser QA reported `BLOCKED`. Browser QA did
  **not** run, so no page-level evidence exists.

Not produced: rendered frames, a finished film, real captions, thumbnails, a social asset set, a site preview
with browser evidence, or a brand-revision diff.

---

## 4. Test results and baseline failures

Environment: Python 3.11.2 venv (`pip install -e "./services/langgraph[dev]"`); Node v22.22.3; pnpm 10.29.3
(installed via `npx pnpm@10.29.3 install --frozen-lockfile`). Host: no ffmpeg, ffprobe, blender, chromium.

### 4a. Gates (all seven CI verifiers)

| Gate | Baseline (009ceb3) | Final |
|---|---|---|
| verify_repository_invariants | PASS | PASS |
| verify_production_readiness | PASS | PASS |
| verify_auth_bindings | PASS | PASS |
| verify_ontology_parity | PASS | PASS |
| verify_design_tokens | PASS | PASS |
| verify_manifest | PASS | PASS (after the three re-pins in §1) |
| verify_guidance_registry | PASS | PASS |
| `python -m compileall -q services/langgraph scripts` | — | PASS |

### 4b. Backend test suite (`python -m pytest services/langgraph/tests -q`)

| Run | Passed | Skipped | Failed | Exit |
|---|---|---|---|---|
| Baseline (009ceb3, before changes) | 1901 | 103 | **1** | 1 |
| Final (this branch) | **1921** | 102 | **0** | 0 |

Reconciliation: 1901 + 18 new timeline tests + 1 fixed env-doc test + 1 UCPO test that now runs = 1921.
Skips: 103 − 3 UCPO build skips + 2 browser-gated skips = 102.

### 4c. Baseline failures, classified

| Test | Baseline result | Cause | Disposition |
|---|---|---|---|
| `test_m0_truthful_records::test_every_environment_variable_the_code_reads_is_documented` | FAIL | Three env vars added in 009ceb3 were not in `.env.example`. | **Fixed** (§1 items 1–2). |
| `test_ucpo_build::test_sandboxed_build_browser_qa_release_and_stale_after_change` | NOT_RUN (skipped; no `node_modules`) | — | Now runs: build step **passes**; browser QA **NOT_RUN** (Chromium unavailable) and skipped. |
| `test_ucpo_build::test_browser_qa_catches_a_defective_generator` | NOT_RUN (skipped) | — | Now **NOT_RUN** (skipped, browser absent). Not a pass. |
| `test_ucpo_build::test_sandboxed_build...` (first run after `pnpm install`) | FAIL | Next pin drift `16.4.2` vs `16.4.3` (`dependency_check` failed closed). | **Fixed** (§1 item 3). |
| Browser QA on this host | BLOCKED | `npx playwright install chromium` → download failure (host not on the sandbox allowlist). | **Environment-blocked.** Not a code defect. Runs in CI, which installs Chromium. |

No baseline failure was hidden by a skip, weakened assertion or fabricated pass. The one assertion edited
(`test_ucpo_pipeline.py`, expected Next version) now matches the audited pin required by
`verify_repository_invariants.py`.

### 4d. Requirement → test map (this session)

| Req | Method | Expected | Observed | Exit | Evidence | Limits | Result |
|---|---|---|---|---|---|---|---|
| Q26/Q31 timing | unit | 28 s / 30 s / 15 s exact | as expected | 0 | `test_timeline_timing.py` | No media | PASS |
| Q29/Q30 cutdown integrity | unit | truncation & extension rejected | rejected | 0 | same | | PASS |
| Env documentation (G-03) | gate | no undocumented env reads | none | 0 | `test_m0_truthful_records.py` | | PASS |
| UCPO tampered source | sandbox integration | refused before execution | refused | 0 | `test_ucpo_build.py` | | PASS |
| UCPO browser QA (Q19) | browser | axe/reflow/keyboard pass | not executed | — | — | Chromium unavailable | NOT_RUN |
| Media render (Q14/Q32) | local render | frames/duration verified | not executed | — | — | No ffmpeg/Blender | BLOCKED |

Not run: fault injection, crash/recovery, tenant-denial E2E, live provider tests, Postgres parity (CI covers it),
and the TypeScript side of the timeline contract (no Zod twin exists).

---

## 5. Setup, run and recovery instructions

```bash
cd agent-mission-control-os
python3 -m venv .venv && . .venv/bin/activate
pip install -e "./services/langgraph[dev]"
npx -y pnpm@10.29.3 install --frozen-lockfile        # enables UCPO sandbox build tests

# Gates (CI order)
python scripts/verify_repository_invariants.py && python scripts/verify_production_readiness.py \
 && python scripts/verify_auth_bindings.py && python scripts/verify_ontology_parity.py \
 && python scripts/verify_design_tokens.py && python scripts/verify_manifest.py \
 && python scripts/verify_guidance_registry.py

# Focused tests
python -m pytest services/langgraph/tests/test_timeline_timing.py services/langgraph/tests/test_ucpo_build.py -q

# Full backend suite (about 45 minutes on this host; run it as a background process)
python -m pytest services/langgraph/tests -q
```

Recovery: this session changed no persistence, schema or migration. Revert is a `git revert` of the branch
commit(s). The timing module is pure and stateless. Re-pinning the manifest after an intentional edit is
required; use the blob-SHA script in `CLAUDE.md`, never hand-copied hashes.

Rebuilding `apps/web/node_modules` is reproducible from the lockfile. Browser QA needs the Playwright Chromium
cache (`PLAYWRIGHT_BROWSERS_PATH`), which is set up in CI.

---

## 6. Blocked and deferred capabilities

**Blocked (environment or authority):**

1. Chromium download for browser QA. Host not on the sandbox allowlist (needs a host-allowlist decision, or a
   pre-provisioned browser cache).
2. Local renderers: ffmpeg, ffprobe, Blender. Not installed; installing them requires a system package step and
   is outside the scope approved here.
3. Hosted image/video generation and T2V: no authorized provider, key or budget. Per the repo's guidance,
   generation providers stay `CAPABILITY_GAP` and must not be faked.
4. Live GitHub webhooks, draft PRs and write credentials: not authorized in this session.
5. Datadog ingestion: no collector endpoint or credentials.

**Deferred (not started):** M04–M05 strategy and deliverable contracts; M06–M07 brand versioning and adaptation;
M10–M11 handoff validation and revision/invalidation; M12–M14 worker, admission, cancellation (durable runtime
exists but is not running as a service); M16–M17 isolated engineering executor and retrieval; M19 transactional
budget reservations; M20 GitHub intake; M21–M22 brand→UCPO no-re-entry mapping; M24 client isolation; M28–M30
reuse, film treatment and per-shot prompt set; M33–M34 finishing and portability (OTIO/C2PA); M35 dashboard
integration; M38 delivery reconciliation; M40 learning metrics; and the reference engagement outputs in §F.

Approval implications: each deferred item that touches external effects (publication, spend, hosting, client
credentials) stays disabled. No external effect was enabled in this session.

---

## 7. External activation decisions

No external activation was requested or performed. Decisions the owner should make:

- **Browser host allowlist.** Decide whether the sandbox may reach the Playwright CDN, or whether a pre-provisioned
  Chromium cache is supplied. Until then, browser QA stays `NOT_RUN` here.
- **Local render tools.** Decide whether to install ffmpeg and Blender in the workspace (system-level change).
- **Generation providers and budget.** No provider, key or spend cap is configured. Any paid generation needs an
  explicit budget and approval record.
- **Deployment.** UCPO `deployment` remains `NOT_AUTHORIZED`. Nothing was deployed.
- **Durable worker.** `RuntimeActive` stays false. A worker needs an explicit runtime owner, process supervision
  and a shutdown plan before activation.
- **GitHub.** No webhooks, PRs or write credentials. Any PR creation needs a separate scoped approval.
- **Repo changes.** Changes are committed on this branch only. Nothing was merged or pushed to `master`.

---

## 8. Next authorized action

1. **Review this branch** (changes in §1). It is local and reversible.
2. **Decide the browser host question** (§7). This unblocks Q19/M23 browser QA evidence.
3. **Next implementation slice, if authorized:** a versioned brand record plus a validated brand→UCPO brief mapping
   (M06/M21, Q05/Q17/Q08), followed by a deliverable contract (M05, Q03/Q16). These are dependency-ready and need no
   new providers. The timeline contract can then be attached to a shot list with rights and reference fields (Q26).
4. Keep the blocked render, provider and GitHub steps behind the decisions in §7.

## 2026-11-10 — Audited frontend baseline re-pinned to Next.js 16.4.5 / @playwright/test 1.65.0

Dependabot #225/#239 merged the November 2026 security releases ahead of the audited baseline
while `CI` could not start (Actions allow-list rejected `pnpm/action-setup`, every run failed at
startup since 2026-11-08). Re-baselined instead of reverted — 16.4.3 is affected by seven
published advisories fixed in 16.4.5 (incl. GHSA-mfr8-8qww-v76h, High). Council extra
constraints re-pinned to a consistent set (aiofiles 24.1.0, aiosqlite 0.21.0, json_repair 0.60.1,
pydantic 2.12.5, pydantic_core 2.41.5) because crewai hard-requires `pydantic<2.13`; see
`docs/ucpo/repository-audit.md` "Re-audit 2026-11-10" for the full rationale and residual risk.
Verification: `python scripts/verify_repository_invariants.py` exit 0; council engines 72/72
locally; hosted CI re-run pending this change.
