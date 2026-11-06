# ABC-v6 traceability

This maps each ABC-v6 requirement to the code that implements it and the test that checks it, in this repository.

| Status | Meaning |
|---|---|
| **IMPLEMENTED** | Code exists and a test exercises it. |
| **PARTIAL** | Some of the requirement is real; the gap is named. |
| **SPEC_ONLY** | Described or typed, but not executed. |
| **MISSING** | Not built. |
| **BLOCKED** | Code exists, but this host lacks a dependency, so it is a reported state. |

Tests are in `services/langgraph/tests/test_abc_v6.py` unless another path is given.

## Baseline and reuse decisions

- **Baseline.** `origin/master` at `08517bf0` (the governed intake slice, PR #122). It was re-run in a clean
  worktree with a fresh SQLite database; the result is recorded in the PR description. The PR #122 slice was
  re-verified before this change built on it, using the 30 intake tests.
- **Reused unchanged:**
  - Project OS artifacts: `create_project_artifact` / `revise_project_artifact` with CAS versions, content-addressed
    storage and `register_storage_object`.
  - The approvals table, plus `/approvals/{id}/decide` with its role and separation-of-duties checks.
  - The fabric's `svg_safety` / `palette_conformance` verifiers and `network_namespace_available`.
  - `agency.assets.render_logo_svg`.
  - `canonical_hash`.
  - The nine-stage domain graph.
  - The fail-closed publication and paid-media integrations.
- **Extended:**
  - The intake release gate was moved into the shared `agency/intake/release.py`. It gained a
    `CROSS_PROJECT_ARTIFACT` reason and is now used by the intake runner, the visual engine and durable jobs.
  - SQLite migration 14, with a Supabase mirror.
- **Created:**
  - `agency/visual/`: routes, renderers, verifier, browser harness.
  - `agency/durable/`: FSM, ticks, visual job, genome, build DAG, governance, proofs, observability.
  - `persistence/durable_runs.py`.
  - Three scripts: manifests, seal and samples.

## §0 invariants

The same mapping is generated into `runtime/abc/SYSTEM_GENOME.yaml`. `compile_abc_manifests.py` fails if any named
enforcing symbol stops resolving.

| Id | Enforced by | Test | Status |
|---|---|---|---|
| I01 real by default; simulation labelled | `artifact_release_verdict` (`SIMULATION_NOT_RELEASABLE`), `governance.decide` | `test_t05_simulation_cannot_release` | IMPLEMENTED |
| I02 missing capability → BLOCKED | `router.route`, `capabilities.probe_*` | `test_t06_*` | IMPLEMENTED |
| I03 no unauthorized external effects | `governance.decide` (G3/G4 never allowed), `spend_execution_available() is False` | `test_t15_*` | IMPLEMENTED |
| I04 persisted bytes + independent observation | `engine.readback_verify`, `ticks.run_tick` OBSERVING/VERIFYING | `test_t13_*`, `test_t02_*` | IMPLEMENTED |
| I05 approval binds hash, version, scope, reviewer | `open_artifact_approval`, `artifact_release_verdict` | `test_t14_*` | IMPLEMENTED |
| I06 tenant/project isolation | `submit_visual_job`, handler precheck, `CROSS_PROJECT_ARTIFACT`, project-scoped ticks | `test_t04_*` | IMPLEMENTED |
| I07 durable state, bounded ticks, stable idempotency | `claim_due_job`, `reserve_intent`, `idempotency_key` | `test_t03_*`, `test_t16_*` | IMPLEMENTED |
| I08 preserve existing semantics | the domain stages are unchanged; existing primitives are reused | `test_t19_domain_stages_preserved`, the full suite | IMPLEMENTED |
| I09 verify interfaces against installed versions | probes import or run the installed tool and record its version | `test_t06_*` | IMPLEMENTED |
| I10 subjective ≠ objective proof | `verify.HUMAN_LEVELS`: Q5–Q7 are never machine-passed | `test_q5_to_q7_are_never_machine_passed` | IMPLEMENTED |
| I11 never weaken safety/rights/security | rights block first; `svg_safety`; allowlisted transition columns | `test_t17_*`, `test_t02_illegal_*` | IMPLEMENTED |
| I12 reviewable, reversible, testable | new modules only; additive migration; seal from real commands | `test_t20_*` | IMPLEMENTED |

## §1–§5 model

| Requirement | Symbol | Test | Status |
|---|---|---|---|
| §1 nine domain stages preserved | `delivery.workflow.topology` (unchanged) | `test_t19_domain_stages_preserved` | IMPLEMENTED |
| §1 capability inventory | `visual.capabilities.probe_all`, the seal's `environment_snapshot` | `test_t06_*` | IMPLEMENTED |
| §2 MissionGenome fields and admission rules | `durable.genome.compile_genome` | `test_genome_admission_rules` | IMPLEMENTED |
| §2 every predicate names an evidence-producing verifier | `VERIFIER_REGISTRY` (raises otherwise) | `test_genome_admission_rules` | IMPLEMENTED |
| §3 three predicates never equated | `build_dag.build_complete` / `release_eligible` / `runtime_active` | `test_three_predicates_are_never_conflated_*` | IMPLEMENTED |
| §4 Build DAG A00–A11 | `build_dag.BUILD_DAG`; toposort, closure, critical path, waves, deterministic ids | `test_t01_*` | IMPLEMENTED |
| §4 a node cannot pass on a report | `node_status`: evidence only; NOT_RUN ≠ PASSED | `test_t20_*` | IMPLEMENTED |
| §4 CAS protection of DAG state | — | — | PARTIAL: node status is recomputed from command evidence on every seal and never stored as mutable state, so there is nothing to CAS. The DAG is not executed by the durable runtime. |
| §5 20-state FSM, legal edges, persisted transitions | `durable.fsm`, `durable_runs.transition` | `test_t02_*` | IMPLEMENTED |
| §5 11-step tick, fencing, write-ahead, key | `durable.ticks.run_tick` | `test_t02_*`, `test_t03_*` | IMPLEMENTED |
| §5 retry classes | `RETRY_SAFE` bounded retry; others dead-letter | `test_repeated_identical_failure_*` | PARTIAL: no handler is `COMPENSATABLE` and no compensation contract exists |
| §5 crash recovery inspects intent and state before replay | `run_tick` RECONCILING plus `VisualRenderHandler.reconcile` | `test_t16_*` (both) | IMPLEMENTED |
| §5 exactly-once | — | — | Not claimed. The guarantee is at-least-once local dispatch with deduplication and reconciliation. |

## §6–§9 production and proof

| Requirement | Symbol | Test | Status |
|---|---|---|---|
| R1 Cycles: PBR, DOF, adaptive sampling, OIDN, colour management, PNG, scene provenance | `visual.blender_runner`, `renderers.render_blender` | `test_t07_t09_*` (needs bpy) | IMPLEMENTED |
| R1 HDRI, EXR output, GPU selection | — | — | PARTIAL: area lights rather than an HDRI, PNG only, CPU device only (the reference host has no GPU) |
| R2 offline diffusion, verified weights and licence | `capabilities.probe_diffusion`, `diffusion_runner.py` | `test_t06_missing_provider_*` | BLOCKED on this host (no torch, diffusers, weights or licence). The runner is untested. |
| R2 OOM bounded reduction | — | — | MISSING |
| Hybrid path (diffusion textures + Blender) | — | — | SPEC_ONLY: depends on R2 |
| R3 renderer choice by shader architecture | `browser.three_renderer_for` | `test_t10_*` | IMPLEMENTED |
| R3 real browser render, shader compile, context loss | `browser.capture_webgl`, `browser_runner.cjs` | `test_t11_*` (needs Chromium) | PARTIAL: raw WebGL in Chromium (SwiftShader). Three.js scenes are BLOCKED (`three` is not installed). |
| R4 vector: XML, viewBox, geometry, palette, safety, multi-size | `verify._svg_checks`, `browser.capture_svg_sizes` | `test_t11_*`, `test_t13_*` | IMPLEMENTED |
| R5 local video: real frames, encode, probe | `renderers.encode_video`, `verify._video_checks` | `test_t12_*` (needs bpy + ffmpeg) | IMPLEMENTED (FreeVideoForge itself is not used: frames come from R1) |
| §7 RealismContract | `visual.contracts.RealismContract` | recorded in `runtime/abc/samples/provenance.json` | PARTIAL: recorded, not enforced by a verifier |
| §7 quality ladder Q0–Q7 | `verify.verify_media` | `test_t13_*`, `test_q5_*` | IMPLEMENTED (Q5–Q7 human) |
| §8 proof-carrying fields | artifact v2 row, intent receipt, `RenderReceipt`, `MediaVerification`, approval row | `test_t18_*`, samples provenance | PARTIAL: assembled from those records; there is no single persisted proof row |
| §8 rejects missing / mismatched / stale / broken / cross-project / simulated / stale approval | `verify_media`, `artifact_release_verdict` | `test_t13_*`, `test_t14_*`, `test_t04_*`, `test_t05_*` | IMPLEMENTED |
| §8 invalid shader output, incomplete browser run | `capture_webgl` findings | `test_t11_*` | IMPLEMENTED for raw WebGL |
| §8 verification states | PASSED / FAILED / INCONCLUSIVE / HUMAN_REQUIRED | `test_multi_size_check_that_cannot_run_*` | PARTIAL: PENDING and RUNNING are durable-job states, not verification-record states |
| §9 TECHNICAL / RIGHTS / HUMAN review | verifier, rights check, approvals with SoD | `test_t13_*`, `test_t17_*`, `test_t14_*` | IMPLEMENTED |
| §9 VISUAL / BRAND review | approval subject `VISUAL_ARTIFACT`; human only | `test_t14_*` | PARTIAL: no structured findings/severity record beyond the approval decision |
| §9 ACCESSIBILITY / SECURITY review of visual output | `svg_safety` (security) | — | PARTIAL: the fabric's WCAG audit is not applied to visual output |

## §10 adaptive modules

| Module | Symbol | Test | Status |
|---|---|---|---|
| PROOF_DEBT_LEDGER | `genome.proof_debt` | `test_proof_debt_and_minimal_proof_set` | IMPLEMENTED (computed, not persisted) |
| EVIDENCE_DOMINATOR_CACHE | `proofs.evidence_valid` | same | PARTIAL: validity rule only; no persistent cache store |
| VISUAL_GENOME | `contracts.VisualGenome` | `test_t07_*` | IMPLEMENTED |
| DUAL_CLOCK_RECEIPTS | `logical_tick` + `wall_*` in telemetry and receipts | `test_t18_*` | IMPLEMENTED |
| CAPABILITY_IMMUNE_REGISTRY | `proofs.capability_registry`, `circuit_state` | `test_repeated_identical_failure_*` | PARTIAL: a read model with a static threshold; no tested-recovery record |
| CONTRADICTION_ENGINE | `genome.find_conflicts` | `test_genome_admission_rules` | IMPLEMENTED |
| CAUSAL_INVALIDATION | `proofs.invalidated_by`; existing CRG and blast radius | `test_proof_debt_*` | IMPLEMENTED |
| NEGATIVE_KNOWLEDGE | `ticks._fingerprint`, `failure_fingerprints` | `test_repeated_identical_failure_*` | IMPLEMENTED |
| PROOF_MINIMIZER | `proofs.minimal_proof_set` (exact up to 16 records) | `test_proof_debt_*` | IMPLEMENTED |
| NOVELTY_WITHIN_CONSTRAINTS | the existing `agency/creative` bounded Pareto search | existing creative tests | PARTIAL: not wired to visual variants |

## §11–§12 observability and governance

| Requirement | Symbol | Test | Status |
|---|---|---|---|
| per-tick telemetry fields | `ticks.run_tick` telemetry | `test_t18_*` | IMPLEMENTED (cost and GPU memory are `NOT_MEASURED`) |
| metrics from persisted rows; BASELINE_UNKNOWN | `observability.metrics` | `test_t18_*` | IMPLEMENTED |
| OpenTelemetry-compatible spans | `observability.spans` / `emit_spans` | `test_t18_*` | PARTIAL: span documents are built; the SDK is not installed, so nothing is exported |
| Datadog | — | — | NOT_CONFIGURED |
| operator UI | — | — | MISSING: no frontend surface for durable jobs |
| G0–G4, enforced symbols, NonActionReceipt | `durable.governance`; the intake `NonActionReceipt` | `test_t15_*` | IMPLEMENTED |

## §13–§14 tests

| Test | Status here | Notes |
|---|---|---|
| T01, T02, T03, T04, T05, T06, T10, T13, T14, T15, T16, T17, T18 | run in every environment | |
| T07, T09, T12 | run where bpy (+ FFmpeg) exist; otherwise skipped as NOT_RUN | |
| T08 | runs where `unshare -rn` works | |
| T11 | runs where Chromium + `@playwright/test` exist | It covers WebGL/SVG in a real browser. The app's existing Playwright E2E was not run by this change. |
| T19 | `test_t19_*` plus the seven CI gates and the full suite | |
| T20 | `test_t20_*` plus `runtime/abc/verification-seal.json` | |

The seven adversarial families map onto these tests:

| Family | Tests |
|---|---|
| OUTCOME | T02, T13 |
| CONTEXT | T04, the genome tests |
| CONFLICT | the genome conflicts, T15 |
| AUTONOMY | T03, T16 |
| FAILURE | T06, T17, negative knowledge |
| REUSE | T19, the manifest check, `test_idempotency_key_is_stable_and_scope_sensitive` |
| PROOF | T13, T14, `test_q5_*`, T20 |
