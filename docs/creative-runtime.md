# Creative Search Runtime

`services/langgraph/agency/creative/` is a bounded, receipted, human-gated runtime for creative missions. It turns a brief into one or more candidate artifacts. It searches only when the mission justifies it, filters candidates through a hard constraint gate and blind critics, and stops for a human. Delivery then needs an approval bound to the exact artifact hash.

It is **deterministic and local**. It makes no model call, no network call, no publication and no spend. Capabilities that need a model (image, video, social copy, brand identity) are `provider_gap`, and their plans are `BLOCKED`. They are never simulated.

```
brief ─▶ MissionIR ─▶ ExecutionPlan (T0–T4) ─▶ context portfolio (rights-safe, budgeted)
      ─▶ candidate(s) ─▶ hard gate (FEASIBLE/INFEASIBLE/UNKNOWN) ─▶ blind critics ─▶ Pareto front
      ─▶ HUMAN: SELECT | REQUEST_VARIATION | REJECT_ALL | RETURN_TO_BRIEF
      ─▶ ≤1 correction ─▶ TriDiff ─▶ existing approval (subject_hash = artifact hash) ─▶ delivery gate
```

CLI: `python3 orchestrate_brand_pipeline.py creative-run --input sample_creative_mission.json [--compare] [--output DIR] [--json]` (or `make creative-run`). Exit 0 means `READY_FOR_HUMAN_REVIEW`.

## Modules

| Module | Responsibility |
|---|---|
| `ir.py` | `MissionIR`, `ArtifactIR` (core plus at most one typed extension: `LandingPageIR`, `LogoIR`, `DesignSystemIR`), `EvidenceEnvelope`, `Finding`. Strict, frozen and hash-sealed with AMC-CANON-1. |
| `mission.py` | Brief → `MissionCompilation`, with `READY`, `HITL_REQUIRED` (critical unknowns plus the questions to ask) or `CONTRADICTORY_CONSTRAINTS`. Noncritical unknowns become recorded assumptions. It adds the standing hard constraints: contrast, landmarks, alternatives, truthful CTA, verified claims only, abstract-only references, no secrets, and approval before delivery. |
| `capabilities.py` | Loads `knowledge/creative-capabilities/registry.json`, which records dispositions, guide hashes, dependency closure, conflicts and duplicates (the immune system's first line). |
| `organization.py` | Mission + registry → `ExecutionPlan`: the smallest topology (T0–T4), a validated DAG that ends at the HUMAN approval node, finite budgets and a degradation policy. |
| `context.py` | A rights-safe context portfolio selected by utility under a token budget, with receipts. `derive_requirements` turns the owned accessibility contract into renderer requirements. |
| `landing.py`, `generators.py` | Deterministic generators. Landing pages compose supplied, verified content only. The logo reuses `agency.assets.render_logo_svg`, and the design system reuses the fabric's `design_system_spec`. Palette CSS is compiled by `design_tokens.compile_css`, the only DTCG compiler. |
| `search.py` | Concept seeds (farthest-point over five axes, seeded by the mission hash), fingerprints, collapse detection, single-axis `MutationSpec`, novelty reservoir, and the Pareto front with uncertainty. |
| `critics.py` | `ConstraintValidator` (the hard gate) and the Accessibility, Brand, Artifact (design), Implementation and Content critics. All of them see only a `BlindView`. |
| `tridiff.py` | D1 mission, D2 artifact and D3 render diffs around a correction. |
| `recorder.py` | Hash-chained flight recorder that holds references only, plus Trace→Test fixtures. |
| `runtime.py` | The state machine, human actions, correction, approval, delivery gate and `MissionReceipt`. |
| `champion.py` | The Champion/Challenger benchmark. |

## Topology selection

| Topology | When | Shape |
|---|---|---|
| T0 | `design_system` | deterministic token → spec transform |
| T1 | dashboard, mobile UI (`compile_uiux` spec); image, illustration, motion, video, social, brand identity, handoff (blocked: provider gap or guidance only) | single generator/compiler |
| T2 | `logo`; a landing page without exploration cues | one candidate plus independent critics |
| T3 | `marketing_site` without exploration cues | landing generator composed with the design-system specialist |
| T4 | landing page or marketing site whose brief asks for distinctiveness or exploration (`premium`, `distinctive`, `explore`, `concepts`, `options`, `variations`, `bold`, `differentiat…`, explicit `exploration.mode=explore` or `candidates>1`), **and** `max_candidates>1`, **and** the search capabilities are usable | bounded search |

Search caps are part of the schema: population ≤ 4, generations ≤ 2, regenerations ≤ 1 per collapsed candidate, corrections ≤ 1, and a diversity floor of 0.35. A larger value fails validation; nothing clamps it silently.

The acceptance mission, "Create a premium cybersecurity SaaS landing page" (`sample_creative_mission.json`), selects T4 with a population of 4. The same brief without exploration cues selects T2, and with `max_candidates=1` it selects T2 and says why.

## Context portfolio

The context portfolio draws on two sources:

- **The design corpus**, loaded through the validated loader. Owned standards give a bounded excerpt. Reference-only entries give their category plus generic principle names, never the source's name, copy, palette or typeface. Unknown-rights entries are excluded as `RIGHTS_BLOCKED`.
- **Workflow guides** for the active capabilities, which contribute only their "Core constraint:" line.

Any integrity failure means no corpus units and a `DEGRADED` status. No guidance is invented to replace them.

Selection then works in three steps:

1. **Filter.** Injection-flagged units are quarantined (`QUARANTINE_SOURCE`, then `RETRIEVE_AGAIN` refills from the rest). Irrelevant units are dropped.
2. **Mandatory units first.** Contract 04 always goes in; Contract 02 also goes in for interface work. A mandatory unit that does not fit the budget stops the run with `BUDGET_EXHAUSTED`.
3. **Greedy fill** by `U = 0.35R + 0.15A + 0.20D + 0.15I + 0.15N − 0.20·redundancy − 0.10·tokens − 0.25·conflict`, with deterministic tie-breaks. Identical abstract principles are deduplicated.

The weights are configuration heuristics. Every selection and exclusion is receipted.

## Evaluator firebreak

- **The hard gate is non-compensable.** `INFEASIBLE` candidates leave the pool with their violations receipted. `UNKNOWN` means a constraint cannot be judged on this artifact, for example landmarks on a spec; such candidates stay, flagged for the human.
- **Critics are blind.** They receive artifact content plus rendering plus mission, with no id, parent, mutation, generator or other critic's score. Identical artifacts with different lineage evaluate identically, and a test proves it.
- **Every evaluation is traceable.** It records `evaluator_id`, `rubric_version`, confidence, per-objective uncertainty, evidence and `not_verified`.
- **Disagreement is kept, not hidden.** When critics disagree on an objective, the spread raises that objective's uncertainty. It is never averaged away.
- **The front is never collapsed to a weighted sum.** `a` dominates `b` only if `a`'s lower bound beats `b`'s upper bound on at least one objective and is no worse on all of them. Close calls stay on the front and go to the human.

## HITL — no new topology, no new persistence

The LangGraph agency graph is unchanged. Approval reuses the existing `approvals` table:

- the request is `create_approval_request(subject_type="CREATIVE_ARTIFACT", subject_hash=<ArtifactIR hash>, policy_version="amc-creative-approval/v1")`;
- the run row is an ordinary `runs` record (pipeline `creative-runtime/v1`, `metadata.initiated_by` for separation of duties).

Re-submitting the same hash is idempotent. A new hash marks the older pending approval `stale`.

`delivery_gate` fails closed. It allows delivery only when:

- the approval is resolved and approved;
- the approval is not stale;
- the approval's `subject_hash` equals the final artifact hash;
- the rendering still matches its sealed hash;
- the evidence envelope is complete.

The gate performs no delivery: `external_effects` is always `"none"`.

## Correction and TriDiff

After SELECT, the runtime applies at most one correction. It is built from the selected candidate's own findings, within a declared repair scope:

- `style` adds renderer requirements: reduced motion, focus-visible, 24 px targets;
- `structure` drops one optional section from a diluted single-focus hierarchy.

The corrected artifact keeps its id and bumps its version. TriDiff then checks three things:

- **D1:** no hard constraint that held before may fail after.
- **D2:** no IR change outside the declared scopes.
- **D3:** no render change that D2 or `style` does not explain.

A failed TriDiff or a score regression rejects the correction, and the original goes to approval.

## Immune system and degradation

| Signal | Action |
|---|---|
| Guide hash mismatch or missing guide | `DEGRADE_CAPABILITY` (`CORPUS_INVALID`), propagated to dependants (`DEPENDENCY_VOID`) |
| Injection in a guide or context unit | `QUARANTINE_SOURCE` (+ `RETRIEVE_AGAIN` for context) |
| Duplicate capability id | whole registry `DEGRADED`; identical re-registration is a no-op, a different one raises |
| Provider unavailable (declared or a generator exception) | `DEGRADE_CAPABILITY` + `BLOCK_STAGE`; no simulated output |
| Mandatory context over budget, or wall clock exceeded | `BUDGET_EXHAUSTED` → terminal `PARTIAL`, validated work retained |
| Critical unknowns or contradictions | `HITL_REQUIRED` / `CONTRADICTORY_CONSTRAINTS` |

## Receipts and replay

`mission_receipt(run)` holds hashes, decisions, budgets, immune actions and the event-chain head. Its `receipt_hash` is deterministic. Wall-clock timing is reported beside it but never hashed. Replaying a brief reproduces the receipt hash.

`recorder.trace_to_test(run)` freezes a run into a regression fixture, and `replay_matches` diffs a replay against it. The flight recorder refuses free text and secret-shaped values, so traces carry no brief content.

## Champion / Challenger

`champion.compare(brief)` runs two configurations:

- **Champion:** the context-free T2 baseline.
- **Challenger:** the full runtime.

Both are scored by the same critics and hard gate on first-pass output. On the acceptance mission:

- the challenger is better on `accessibility_quality` (1.0 vs 0.7, beyond the declared ±0.05);
- it is worse on nothing;
- it explores 4 materially different concepts;
- it costs 969 context tokens and 0 model calls.

This is a structural rubric result. It is not a human-preference, conversion or model-quality claim.

## Limits

- **No model-backed generation.** Copy comes only from verified assets and mission fields; sections without supplied content are omitted and listed.
- **No browser rendering.** The headless DOM audit lists what it could not verify: cascade, media-query reflow, focus order and keyboard operability.
- **Distinctiveness is a structural distance**, not perceived novelty.
- **Deterministic generators.** `seed` is `null` and `provider_config_ref` names the deterministic configuration.
- **Rollback is a revert.** The runtime adds no migration and changes no graph topology; reverting the commit restores the previous corpus (old archive SHA in `test_design_corpus.py`).
