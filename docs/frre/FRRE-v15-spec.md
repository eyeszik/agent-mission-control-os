# AMCOS FRRE v15.0 — Framework Reliability & Remediation Engine
## Evidence-bound specification (W0 discovery + W1 design). No implementation authorized.

Verification date: 2026-11-24 (UTC). Repository: `eyeszik/agent-mission-control-os`.
Method: read-only `git`, GitHub API reads, source inspection at the baseline SHA, one deterministic model check in scratch space.
Repository mutations, PRs, deployments, rule changes: **none performed**.

---

## 0. Plain-English verdict

AMCOS already contains the *ingredients* of governed self-repair, but only **inside individual domains**:
- AVIC repairs visual defects with causal hypotheses, a dependency-closure budget, isolated re-rendering, independent re-evaluation, regression refusal and parent rollback.
- VNEXUS `immune.py` scans the brand system and offers narrow, reversible, opt-in repairs.
- CARS fingerprints capabilities and environments.
- The code sandbox validates Python patches in a read-only, network-less namespace.
- The durable FSM provides fenced, audited state transitions.

There is **no framework-level repair owner**: no incident model, no repair plane, no trust plane separating proposer from verifier, and no delivery adapter. Two safety primitives an FRRE would need are **dormant**: the ASI10 shared halt (`security/distributed.check_any_halt`) and `ToolExecutionPolicy`, which have zero non-test callers.

On GitHub, the `master` ruleset requires a PR but **0 approvals and an empty required-status-check list**, so nothing structurally forces independent review or green CI before merge.

**Maturity today:**

| Level | Status | Basis |
|---|---|---|
| L0 | VERIFIED | External coding with human approval, demonstrated in this session |
| L1 | IMPLEMENTED | Utilities exist |
| L2 | IMPLEMENTED | Diagnostics exist |
| L3 | PARTIAL | Domain repair is reachable for AVIC and VNEXUS only |
| L4 | ABSENT in inspected scope | No autonomous framework repair found |
| L5 | ABSENT in inspected scope | No production self-healing found |

FRRE is therefore a **new governed subsystem that reuses existing owners**, not a rename of something that exists.

**Terminal state: `COMPLETE_WITH_LIMITATIONS`.** The specification is complete. Implementation is blocked on owner decisions (§14).

---

## 1. Baseline reconciliation (G0)

| Fact | Status | Evidence |
|---|---|---|
| PR #303 is **merged**, not an open draft | VERIFIED | GitHub API: `merged:true`, `merged_at 2026-11-24T21:17:34Z`, merged by the owner. This supersedes the brief's "open draft/unmerged". |
| New baseline is `master = c1e4d0a041a946523d237e3b392cc129abfb2411` | VERIFIED | `git fetch` plus `rev-parse` |
| Squash commit `c1e4d0a` has the **identical tree** to PR head `20d47e5` (`b94a494…`) | VERIFIED | `git rev-parse <sha>^{tree}`; `git diff --quiet` exits 0 |
| PR-head CI (13/13 green on `20d47e5`, run 45442322204) | VERIFIED for `20d47e5` only | Commit-bound. Not transferred to `c1e4d0a`, despite the identical tree. |
| Master CI on `c1e4d0a` (run 45489613981; CodeQL run 45489612085) | **UNVERIFIED (in progress at read time)** | Actions API: `status: in_progress` |
| Ruleset 20371074 (active, target: default branch) | VERIFIED | Public API read. Rules: deletion, non_fast_forward, pull_request (`required_approving_review_count: 0`, `required_review_thread_resolution: true`, merge methods squash/rebase), required_linear_history, required_status_checks (`required_status_checks: []`, strict false). Bypass actors: none. |
| The six #303 mutation detections | VERIFIED **in-session, locally, on pre-merge content** (not CI) | Earlier in this session, each mutation failed `framing-parity.test.ts` and was restored, with diff-verified restoration. Not re-run on `c1e4d0a`. |
| Unicode 14.0.0 fixture provenance | VERIFIED | Generated under Python 3.11.18 (`unidata 14.0.0`); the TS suite asserts the version match |

---

## 2. Owner reuse map (W0)

Reuse labels:
- **REUSE**: use the owner as is.
- **EXTEND**: add to the existing owner.
- **NEW**: no owner exists.
- **DEFER**: not in this wave.

| Concern | Existing owner (verified at `c1e4d0a`) | Reachability evidence | Decision | Rationale |
|---|---|---|---|---|
| Domain repair loop pattern | `agency/avic/repair.py` (271 lines): `detect`, `propose`, `apply`, `divergence`, `repair`, `dependency_closure`, `MAX_ATTEMPTS=3` | Imported by `avic/run.py:21` and `avic/service.py:35` | **REUSE as reference pattern**; do not generalise its SVG code | It is the closest proven implementation of mechanisms C, F, H, plus rollback, but its IR is visual |
| Narrow reversible remediation | `agency/vnexus/immune.py` | VNEXUS service | **REUSE pattern** | Deterministic, reversible, explicit opt-in, new artifact revision |
| Patch isolation | `agency/execution_fabric/adapters/code_sandbox.py`: `unshare -rmn`, read-only root, scrubbed env, rlimits, Python-only, `py_compile`-equivalent allowlist, ≤50 files, fail closed | Callers: `visual/renderers.py`, `execution_fabric/skills.py`; 5 test files | **EXTEND (protected)** | Running test suites needs a new allowlisted command class. That widens a security control, so it requires independent review (§7, T6). |
| Run/state machine | `agency/durable/fsm.py` (`amc-run-fsm/v2`, `TRANSITIONS`, `assert_transition`, `reachable`) plus `ticks.py` (fenced, logged to `durable_transitions`) | Durable runtime | **REUSE pattern → NEW incident FSM** | Run states ≠ incident states. Mirror the pure-FSM-plus-guarded-tick split. |
| Jobs, leases, retries | `runtime/worker.py` (`claim_job`, `renew_job_lease`, `expire_stale_leases`, cancellation fence, crash-recovery re-checks of release guards) | Live worker | **REUSE** | FRRE stages run as jobs |
| Idempotency, outbox | `persistence/idempotency.py`, `agency/reliability/outbox.py` | Used by the worker | **REUSE** | E03, E08 |
| Approvals (single path) | `open_artifact_approval` plus `/approvals/{id}/decide` | 8+ non-test callers | **REUSE (mandatory)** | Cross-cutting rule: one approval path. FRRE adds no approval store. |
| Approval-summary framing (ASI09) | `security/approval_framing.assess` (Python authoritative); TS twin `@amc/pii.assessFraming` (no callers) | `persistence/approvals.py` | **REUSE** | Every FRRE approval summary is scored. HIGH requires acknowledgment. |
| Artifacts, proof capsules | `foundry.studio.store` (N4 `agency_artifacts`, `depends_on`) | Project OS | **REUSE (mandatory)** | Cross-cutting rule: one artifact store. Capsules are artifacts, with short digest names ≤64 characters. |
| Event log, replay | `persistence/events.py` (`record_event`, `list_events_for_run`, per-run sequence) | Live | **EXTEND** | Incident timeline. Events are currently run-keyed, so an incident key is needed. |
| Capability and environment diagnostics | `agency/capability_assurance.py` (CARS: probes, env fingerprint, remediation hints) | Live | **REUSE** | OBSERVE plane; separates environment from code causes (E05) |
| CI failure parsing | `.github/scripts/annotate-junit-failures.py`, `annotate-playwright-junit.py` | CI `failure()` steps | **REUSE logic** in the ingestion adapter | Already tolerant of missing or unparsable reports |
| Kill switch | `security/distributed.py`: `set_halt` / `check_any_halt` (scopes global→tenant→agent→job→tool, DB-backed); `ToolExecutionPolicy` | **Dormant: 0 non-test callers** | **EXTEND (activate, protected)** | Wiring is an activation of a security control. It needs review and a test proving the halt blocks FRRE effects. |
| Council session halt and anomaly strike | `agency/council/gateway.py` (`SESSION_HALTED` → 423) | Live in the council | **REUSE pattern** | Precedent for a per-session halt |
| Generic execution node | `graph/nodes/execution.py` | Reachable from `graph/build.py` (the generic graph, not Layer-1 `graph/agency`) | **DO NOT REUSE** | Placeholder that prints and returns a canned "Generated the requested artifacts" message. It is misleading-success risk and should be flagged, not built on. |
| Agent roster | `AGENTS.md` (Orchestrator, Execution/Codex, Validation, Governance) | Documentation only; CLAUDE.md states these are not runtime components | **DO NOT TREAT AS RUNTIME** | Documented ≠ registered |
| Fail-closed external integration pattern | `integrations/publication.py`, `paid_media.py`, `zo.py` (mode env defaults to `disabled`, enforced by `verify_production_readiness.py`) | Live | **REUSE pattern** for the GitHub delivery adapter | A PR is an external effect |
| Web build, QA | UCPO (`sandbox.py`, `qa.py`, `build.py`); IntentLinker lives in `ucpo/service.py`, not `ucpo/intent_linker.py` (which does not exist) | Live | **REUSE** for frontend-repair validation | Corrects the brief's path |
| Integrity pinning | `manifest.json` (`amc-integrity/v2`, git-blob SHAs) plus `verify_manifest.py` | CI gate | **EXTEND** | FRRE authority files must be pinned |

Limitations: discovery used grep-based caller tracing. Dynamic dispatch, string-based imports and route registration through decorators are static-analysis gaps, and could hide callers of the "dormant" owners. Before activation, confirm with a runtime import-graph or coverage run.

---

## 3. Architecture: four planes, separate identities

```
 OBSERVE (read-only)          REPAIR (proposer)                 TRUST (independent)               DELIVERY (separately authorized)
 ─────────────────            ─────────────────                 ───────────────────               ───────────────────────────────
 CI junit/annotations   ──►   Incident (dedup, fingerprint) ─►  Policy + scope check              Draft-PR adapter
 CARS probes/fingerprint      Diagnosis (hypotheses, repro)     Plan digest sealing               (mode: disabled|dry_run|
 Runtime events/health        RepairPlan (closure budget)       Sealed-candidate verifier          draft_pr; default disabled)
 Dependency audit             Candidate in code_sandbox ext.    Acceptance fixtures in ESCROW     Release observation
                              (writes ONLY to scratch)          Negative controls / counterfactual Recovery runbook
                                                                Verdict + proof capsule
           all transitions: frre FSM ─ fenced tick ─ frre_transitions (tenant_id, RLS) ─ events
           all approvals:   open_artifact_approval → /approvals/{id}/decide  (framing-scored)
           all artifacts:   foundry.studio.store (capsule, plan, candidate patch, verdict)
           kill switch:     check_any_halt(tool="frre", tenant, job) consulted before EVERY effect
```

Separation rules (mechanism E, the independent jury):
- The REPAIR identity can write only to `frre/*` scratch workspaces and to its own artifacts.
- The REPAIR identity cannot read trust-plane signing material, cannot write acceptance fixtures, policies, validators, `scripts/verify_*`, `manifest.json`, `.github/**`, `security/**` or `agency/kernel/**`, and cannot call `/approvals/{id}/decide`.
- The TRUST verifier runs from a commit-pinned copy of the validators taken from the **baseline**, never from the candidate. A candidate that edits a validator is rejected outright (E09).
- The DELIVERY adapter accepts only a capsule whose verdict is signed by TRUST and whose approval receipt matches the capsule digest.

---

## 4. Incident FSM (design; model-checked)

Main path:

OBSERVED → DEDUPLICATED → TRIAGED → REPRODUCTION_AUTHORIZED → REPRODUCED → DIAGNOSED → PLANNED → MUTATION_AUTHORIZED → SANDBOXED → PATCHED → CANDIDATE_SEALED → VALIDATION_AUTHORIZED → VALIDATED → REVIEW_READY → RELEASE_APPROVED → RELEASED → POST_RELEASE_OBSERVED → RESOLVED

Alternative edges:
- Any pre-effect state may move to BLOCKED, ESCALATED, REJECTED or NO_ACTION.
- Candidate-bearing states (SANDBOXED through VALIDATED) may move to QUARANTINED.
- RELEASED → RECOVERY_REQUIRED or ESCALATED; POST_RELEASE_OBSERVED → RECOVERY_REQUIRED.
- RECOVERY_REQUIRED → ROLLED_BACK or ESCALATED; ROLLED_BACK → POST_RELEASE_OBSERVED.
- BLOCKED → TRIAGED or ESCALATED. Re-entry is only through re-triage, which means fresh authorization (E01).
- ESCALATED → TRIAGED, REJECTED or NO_ACTION.
- QUARANTINED → PLANNED, REJECTED or ESCALATED. Replanning requires a changed hypothesis (mechanism H).

Terminal states: RESOLVED, REJECTED, NO_ACTION.

Deterministic model check (Python graph search; Wolfram TOOL_UNAVAILABLE in this session); script at `scratchpad/frre/fsm_check.py`:
- **25 states, 96 edges.**
- **Unreachable states: none.**
- **Non-terminal dead ends: none.**
- **States that cannot reach a terminal: none.**
- **Effect stages entered without their permit state: none.**
- RELEASED is reachable only from RELEASE_APPROVED.

Caveat: the cycle ROLLED_BACK → POST_RELEASE_OBSERVED → RECOVERY_REQUIRED → ROLLED_BACK is real. It must be bounded by `Budget.attempts` and end in ESCALATED. This is a model of the design, not proof of an implementation.

Server enforcement:
- `frre/fsm.py` is pure, mirroring `durable/fsm.py`.
- `frre/ticks.py` is the only mover. It checks CAS `expected_version`, the fencing token from the job lease, the idempotency key and the permit, and appends a `Transition` row plus an event.

---

## 5. Contracts (W1; Pydantic `extra="forbid"`, each with a Zod twin and a recorded fixture)

Rules for every contract:
- `schema_version` is a literal.
- `tenant_id` and `project_id` are required on every persisted record.
- Digests match `^sha256:[0-9a-f]{64}$`.
- Times are UTC ISO-8601.
- Enums are closed.
- Defaults are pessimistic: `verdict` has no default, `state` starts at `OBSERVED`, `enabled` defaults to False.
- Unknown fields are rejected.

The brief's field lists are adopted verbatim, with these refinements:
- **Incident.** `fingerprint` = sha256 over the normalised failure signature (job name, step, first failing test id, error class; timestamps and run ids stripped). `failure_class` ∈ {`CI_GATE`, `CI_TEST`, `DEPENDENCY`, `BUILD`, `RUNTIME_HEALTH`, `MIGRATION`, `API_CONTRACT`, `SECURITY`, `ENVIRONMENT`}. `evidence` is a list of `Witness`.
- **Diagnosis.** Each hypothesis carries a `classification` ∈ {CODE, CONFIG, DEPENDENCY, ENVIRONMENT, FLAKY, AUTHORIZATION, STALE_CHECK, OUTAGE, UNKNOWN}. `selected_cause` is null unless `reproduction.status == REPRODUCED`; an unreproduced cause can only feed an ESCALATED proposal (§06 rule).
- **RepairPlan.** `allowed_paths` and `protected_paths` are glob lists. The validator rejects any overlap, and rejects any `allowed_paths` entry matching the **built-in protected floor**: `scripts/verify_*`, `manifest.json`, `.github/**`, `services/langgraph/security/**`, `services/langgraph/agency/kernel/**`, `supabase/migrations/**`, `**/tests/fixtures/**` (escrow), and `services/langgraph/agency/frre/policy/**`. `acceptance` and `negative_controls` are content digests of escrowed fixtures.
- **Permit.** `stage` ∈ {READ, REPRODUCE, MUTATE, VALIDATE, RELEASE}. `candidate_digest` is required iff stage ∈ {VALIDATE, RELEASE} (a nonexistent hash is never demanded before generation). A permit is invalid if `now ≥ expires_at`, its `revocation_ref` is set, `baseline` ≠ the current HEAD of the target, or `policy_digest` ≠ the current policy digest (E01).
- **Candidate.** `patch_digest` is computed over the unified diff. The digest of `semantic_diff` (an AST diff, reusing `ast_structural_diff`) is part of the capsule.
- **Validation.** `verdict` ∈ {PASS, FAIL, BLOCKED}. Any mandatory check in `skipped` or `unknown` forces BLOCKED (mechanism F; UNKNOWN ≠ PASS).
- **Transition, Budget, Capability, Outcome.** As in the brief. `Capability.maturity` uses the eight-stage ladder (DOCUMENTED → OPERATIONALLY_VERIFIED), with an evidence ref required per stage.

Persistence:
- One new table family `amc.frre_*` (incidents, transitions, permits, quarantine), each with `tenant_id` and the `amc_tenant_isolation` RLS policy. `test_tenant_rls.py` will fail otherwise, which is correct.
- Capsules, plans, candidates and verdicts go to the **existing** artifact store, not new tables.

---

## 6. Advanced mechanisms → concrete binding

| Mechanism | Bound to | Notes |
|---|---|---|
| A. Proof-carrying capsule | Artifact `frre-cap-<12hex>` with `depends_on` = [incident, plan, candidate, verdict, approval receipt] | Approval binds to the capsule digest. Any content change means a new capsule and fresh approval, the AVIC precedent. |
| B. Counterfactual replay | TRUST runs the acceptance set on baseline (must FAIL on target) and on candidate (must PASS) | A test that passes on both is non-discriminating, and the run is BLOCKED |
| C. Closure budget | `RepairPlan.allowed_paths` plus the import-graph closure of the touched symbols | Same idea as `avic.repair.dependency_closure`. Divergence outside the closure means REJECTED. |
| D. Immune memory | Fingerprint → {remedy capsule, verdict, environment fingerprint from CARS}, tenant-scoped and redacted | Never stores authority, only outcomes |
| E. Independent jury | Separate identities per plane (§3) | Disagreement means ESCALATED |
| F. Regression monotonicity | The baseline pass set must be ⊆ the candidate pass set; pre-existing failures are listed explicitly | The #303 session showed why this matters: 34 pre-existing environment failures had to be proven identical on base |
| G. Semantic intent | AST and contract diff (Zod/Pydantic fixtures, `verify_ontology_parity`) | Any unspecified contract change means REJECTED |
| H. Quarantine ledger | `amc.frre_quarantine` keyed by (fingerprint, patch_digest) | The identical patch can't be retried |
| I. Lease/drift sentinel | Permit fields plus the job lease fencing token | |
| J. Shadow mode | W2–W4 run with `delivery_mode=disabled`; outputs are compared with the human-made fix | Example: incident 7ac18f8 → #301 |
| K. Evidence promotion | Per-`failure_class` capability rows; promotion needs an owner approval artifact | |
| + Evidence-dependency invalidation | Each Witness carries `sha`; a baseline move invalidates only the witnesses whose path is in the changed set | |
| + Counterexample escrow | Acceptance fixtures are stored as artifacts, digest-referenced, outside `allowed_paths` | |
| + Delta ledger | Each hunk is mapped to {requirement, symbol, test, permit} in the capsule | |
| + Confidence separation | Diagnosis confidence (qualitative until calibrated), evidence completeness (ratio), authorization (boolean) are separate fields, never combined | |

These are design proposals, not claims of novelty.

---

## 7. Threat model (STRIDE; OWASP agentic references where applicable)

| # | Threat | Control | Gate |
|---|---|---|---|
| T1 | Prompt or log injection steers the repair (poisoned CI output, PR comments) | Ingested text is typed data, never instruction; the parser extracts fixed fields; tool arguments come from the plan schema, not from text | G4 |
| T2 | Repair actor edits validators or tests to get green | Protected floor in the RepairPlan validator; TRUST runs baseline-pinned validators; escrowed fixtures | G7 |
| T3 | Self-approval | REPAIR identity has no decide permission; approval only via the existing route by a human principal; framing score on the summary | G7 |
| T4 | Stale or replayed permit | Expiry, revocation, baseline and policy digest checks; JTI-style permit ids (reuses the `check_and_record_jti` pattern) | G4 |
| T5 | Cross-tenant leakage via immune memory | Tenant-keyed rows plus RLS; redaction before storage | G4 |
| T6 | Sandbox escape when the allowlist is widened to run tests | Widening `code_sandbox` is a protected-control change: independent review, seccomp gap noted, network-less namespace kept; runs test commands from a closed list only | G5 |
| T7 | Unknown external effect after a crash (PR half-created) | Outbox plus idempotency key; reconcile by reading the remote back before any retry | G8 |
| T8 | Runaway loop or cost | Budget per incident; `max_attempts=3`; kill switch (`check_any_halt`); quarantine on non-convergence | G8/E11 |
| T9 | Misleading success (placeholder nodes, skipped checks) | UNKNOWN/SKIPPED mandatory evidence forces BLOCKED; `graph/nodes/execution.py`-style placeholders flagged by a capability probe | G6 |

---

## 8. Edge cases E01–E11 → enforcement point

| Edge case | Enforcement point |
|---|---|
| E01 drift | Permit validation on every tick (§5) |
| E02 flaky tests | Matched re-runs plus held-out escrow fixtures; FLAKY is a classification, never a root cause; at most one re-run |
| E03 duplicates or concurrency | Fingerprint dedup, CAS version, `concurrency_per_workspace=1`, lease fencing |
| E04 injection | T1 controls |
| E05 missing tool | CARS probe forces BLOCKED_ENVIRONMENT. This session's example: the Playwright CDN was blocked. |
| E06 Unicode or version mismatch | Pinned interpreter per fixture owner. This session's example: Unicode 14 vs Node's Unicode 17. |
| E07 protected mutation | Protected floor; refusal plus proposal artifact |
| E08 crash | Outbox and read-back reconciliation |
| E09 validator tampering | T2 controls |
| E10 irreversible effects | RELEASE permit requires a staging plus backup evidence witness, otherwise BLOCKED; migrations are never auto-applied |
| E11 non-convergence | Budget, quarantine, kill switch, human escalation with a reproducible capsule |

---

## 9. Implementation waves (all PLANNED; none authorized)

| Wave | Objective | Files (new unless noted) | Authority needed | Effects | Acceptance |
|---|---|---|---|---|---|
| W1 | Contracts, FSM, threat model | `agency/frre/{contracts,fsm,policy/floor}.py`, `packages/shared/src/schemas/frre.ts`, fixture plus parity test, `agency/frre/CLAUDE.md` | Local implementation permit | REVERSIBLE (code only) | Zod/Pydantic parity; FSM model test in CI; `verify_ontology_parity` green |
| W2 | Observe and shadow | `agency/frre/ingest.py` (reuses junit-annotate parsing and CARS), `amc.frre_incidents` plus RLS migration | Migration approval (protected) | COMPENSATABLE | Dedup fixtures; RLS test |
| W3 | Diagnose | `agency/frre/diagnose.py` (hypotheses, reproduction via the existing worker job) | Reproduce permit | READ_ONLY plus sandbox | Reproduces a known failure (G2/G3) |
| W4 | Propose | `agency/frre/plan.py`, capsule writer via `foundry.studio.store` | Mutate permit | Scratch only | Closure budget enforced; capsule digest stable |
| W5 | Validate | `code_sandbox` extension (**protected**), `agency/frre/verify.py` (trust identity) | Independent review of the sandbox change | Sandbox | Counterfactual plus negative controls; a corrupt candidate fails (G6) |
| W6 | Review | Approval wiring through `open_artifact_approval`; GitHub draft-PR adapter (mode default `disabled`; `verify_production_readiness` extension, **protected**) | Delivery approval | EXTERNAL (draft PR) | Adapter refuses without capsule, verdict and receipt |
| W7 | Recover | Post-release observer; immune memory | Release permit | COMPENSATABLE | Observed recovery (G10) |
| W8 | Operate | Disabled-by-default trigger; activate the `check_any_halt` kill switch (**protected**); budgets | Activation approval | — | Halt blocks every effect (test) |
| W9 | Verify | Failure injection, concurrency, crash, stale-refusal suites | — | — | G4–G10 |

Serialise W1 → W2 (schema/migration) and W5/W6/W8 (protected controls). W3 and W4 can run in parallel after W2.

UX (W6+): reuse existing approval and Project OS views. The incident inbox → evidence → diagnosis → scope diff → validation → approve/reject flow uses existing tokens and Motion rules. The framing score is shown verbatim, and pause/kill is reachable by keyboard. There is no visual work until W6 is authorized.

---

## 10. Validation gates G0–G10 (status at `c1e4d0a`)

| Gate | Status | Evidence / blocker |
|---|---|---|
| G0 Baseline and scope reconciled | **PASS** | §1. Caveat: master CI in progress at read time. |
| G1 Contracts, transitions, parity | **PASS (design only)** | FSM model check (§4); no code contracts exist yet |
| G2–G10 | **NOT_RUN** | No FRRE implementation exists or was authorized. G9 and G10 additionally require activation evidence. |

Repository gates on `c1e4d0a`: **NOT_RUN in this pass** (read-only). They passed on the identical tree `20d47e5` earlier in this session, which is reference only, not transferred.

---

## 11. Metrics

All FRRE metrics (MTTD, diagnosis latency, validated-repair rate, false positives, regression, rejection, repeat rate, recovery time, evidence coverage, refusal accuracy, cost, tokens) are **NOT_MEASURED**. No FRRE runtime exists, so every denominator is 0 and every ratio is N/A.

The first measurable sample is shadow mode on historical incidents. One real case is recorded in this session: incident 7ac18f8 (Dependabot pin drift) → human-merged fix #301. Across this session the time from detection to a verified fix was about 9 hours, but that was human-directed, not FRRE.

**Confidence: UNKNOWN.** Nothing has been calibrated, so a human must review.

---

## 12. Governance

| Area | Verdict | Notes |
|---|---|---|
| LEG (rights, privacy, consent) | PASS_WITH_NOTES | Immune memory must redact PII before storage (reuse `@amc/pii` / `security/pii.py`) |
| ETH (truthful oversight) | PASS | Framing scoring of approval summaries; UNKNOWN ≠ PASS |
| SEC (isolation, least privilege, injection) | **ESCALATE** | The ruleset has no required checks or reviewers. A self-repair system on top of that lacks an external trust anchor. |
| RG (cost, latency, maintenance, access) | PASS_WITH_NOTES | Budgets defined; actual cost unmeasured |

---

## 13. Operator, recovery and activation runbook (for when waves are authorized)

1. Activation order: W1 → W2 in shadow (delivery `disabled`) → owner reviews shadow capsules → per-failure-class promotion artifact → W6 `dry_run` → W6 `draft_pr`.
2. Kill switch: `set_halt(scope="tool", scope_key="frre", reason=..., issuer=<human>)`. Every FRRE tick checks `check_any_halt` first. Verify with `check_any_halt(tool="frre")` returning a record.
3. Recovery: a draft PR is the only external effect. Close it and delete the branch, which is COMPENSATABLE. FRRE never merges, deploys or migrates.
4. Read-back before retrying an uncertain effect: list PRs by head branch. If one exists, adopt it; never create a second.

---

## 14. Owner actions and blockers (BLOCKED_OWNER_DECISION items)

1. **Authorize W1** (contracts plus FSM, code only, reversible) on a feature branch, or keep FRRE as a specification only.
2. **Ruleset hardening** (I proposed it and have not applied it): add `required_status_checks` with the CI job names that passed on #303:
   - Backend (compile + invariants + pytest)
   - Backend on PostgreSQL (migrations + pytest)
   - Frontend (contracts + typecheck + test + build)
   - Browser E2E (local degraded HITL)
   - UCPO sandboxed build + browser QA (must not skip)
   - Dependency audit
   - CodeQL

   Set `strict_required_status_checks_policy: true`. Note the trade-off: with a single maintainer, `required_approving_review_count ≥ 1` would block your own PRs, because GitHub forbids self-approval. Independent review would need a second human reviewer or a CODEOWNERS-backed reviewer.
3. **Protected-control decisions** needed before W5, W6 and W8:
   - widening the `code_sandbox` allowlist to run tests;
   - adding an `AMC_FRRE_DELIVERY_MODE` gate to `verify_production_readiness.py`;
   - activating the dormant ASI10 halt.
4. **Housekeeping found during discovery** (not fixed, out of scope):
   - `graph/nodes/execution.py` returns canned success text;
   - `scripts/qa/provision-qa-chromium.sh` pins `playwright-core@1.65.0` while the lockfile has 1.65.1.
5. Confirm when master CI run 45489613981 on `c1e4d0a` finishes.

---

## 15. Schema-locked report (§14 of the brief)

```json
{
  "baseline": {"repo": "eyeszik/agent-mission-control-os", "master": "c1e4d0a041a946523d237e3b392cc129abfb2411",
               "tree": "b94a49432d5955f24cde9636f9a25212d438a17c", "pr_303": "MERGED 2026-11-24T21:17:34Z",
               "master_ci": "IN_PROGRESS (run 45489613981)"},
  "verified_facts": ["PR #303 merged", "c1e4d0a tree == 20d47e5 tree", "ruleset: 0 approvals, required_status_checks=[]",
                     "ASI10 check_any_halt and ToolExecutionPolicy have 0 non-test callers",
                     "graph/nodes/execution.py is a canned-success placeholder reachable from graph/build.py",
                     "ucpo/intent_linker.py does not exist; IntentLinker is in ucpo/service.py",
                     "avic/repair.py reachable via avic/run.py and avic/service.py; MAX_ATTEMPTS=3",
                     "code_sandbox: unshare -rmn, read-only root, py-compile-only allowlist, fail closed"],
  "reported_claims": ["13/13 CI on 20d47e5 (verified then, commit-bound, not transferred)"],
  "assumptions": ["grep-based caller tracing is complete enough to call owners dormant (static-analysis gap noted)"],
  "capability_matrix": "see §2",
  "maturity_by_failure_class": {"visual_defect": "L3", "brand_drift": "L3 (narrow)", "CI_GATE": "L0", "CI_TEST": "L0",
                                "DEPENDENCY": "L0", "BUILD": "L0", "RUNTIME_HEALTH": "L2 (CARS diagnose only)",
                                "MIGRATION": "L0", "SECURITY": "L0"},
  "dependency_graph": "see §2 reachability column and §3",
  "owner_reuse_map": "see §2",
  "architecture": "see §3",
  "threat_model": "see §7",
  "contracts": "see §5",
  "edge_cases": "see §8",
  "implementation_waves": "see §9 (all PLANNED)",
  "changed_files": [],
  "validation_gates": {"G0": "PASS", "G1": "PASS_DESIGN_ONLY", "G2-G10": "NOT_RUN"},
  "evidence": "see §1 and §4",
  "metrics": "NOT_MEASURED",
  "authorization": {"granted": ["read-only analysis"],
                    "not_granted": ["isolated execution", "mutation", "PR", "merge", "deploy", "migration", "rule changes", "activation"]},
  "governance": {"LEG": "PASS_WITH_NOTES", "ETH": "PASS", "SEC": "ESCALATE", "RG": "PASS_WITH_NOTES"},
  "unresolved_gaps": ["no framework repair owner", "dormant kill switch", "no required checks/reviewers on master",
                      "master CI on c1e4d0a pending", "no calibration data"],
  "owner_actions": "see §14",
  "terminal_state": "COMPLETE_WITH_LIMITATIONS"
}
```

Work ledger:
- **EXECUTED:** baseline and ruleset reads, owner discovery, tree comparison, FSM model check.
- **PLANNED:** W1–W9.
- **SKIPPED:** repository gates on `c1e4d0a` (read-only pass).
- **BLOCKED:** all implementation, pending owner authorization.

Review-ready ≠ merged ≠ deployed ≠ operationally verified. No autonomous capability is claimed.
