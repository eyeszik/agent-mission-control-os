# Method routing and delegation

Source spec: `AMC_METHOD_ROUTER_INSTALLER_v2_COMPACT` (SHA-256 `673dd821cbb9ebce886dc603ab5b1bc4f9088acf9cf69d0e9001ec3e85a2f50c`), built on `feat/unified-contract-method-router-9bf9d7f8@60c58d7c`.

The method layer is a deterministic decision and delegation **compiler**, not another orchestration system. It turns an objective into the smallest justified stack of established methods and a bounded DAG of delegation envelopes. It then hands that DAG to the canonical RoleOS work-order compiler.

```
ObjectiveRequest
 → normalize → ProblemSignature (multi-label, evidence-gated)
 → MethodRouter → MethodStack (six slots, counterfactually minimal) + MinimalityCertificates
 → MethodPlan (hash-addressed) → DelegationEnvelope DAG (proof-carrying)
 → mission payload + explicit phase_map
 → role_os.MissionWorkOrderAdapter → role_os.WorkOrderCompiler → RoleResolver
 → compiled.backchain CausalWorkGraph → compiled.execution cells + schedule_waves
 → EXECUTOR_GAP (no generic executor exists)
```

## Integration decision

| Concern | Owner |
| --- | --- |
| Objective → methods | new: `agency/compiled/method_router.py` (pure) |
| Models | new: `agency/compiled/method_models.py` (strict, frozen) |
| Catalog | new: `agency/compiled/data/method_catalog.v1.json` + `method_catalog.py` (loader, validator, predicates) |
| Delegation boundary | new: `agency/compiled/method_mission.py` |
| Work-order identity, specialist resolution, execution readiness | **reused:** `MissionWorkOrderAdapter`, `WorkOrderCompiler`, `RoleResolver` |
| Cells and waves | **reused:** `CausalWorkGraph`, `build_cell`, `schedule_waves` |
| Hashing | **reused:** compiled-agency `semantic_hash` |
| Approval and separation of duties | **reused:** `security.approval_authority.assert_may_decide` (named by every human gate) |
| Idempotency | **reused:** `WorkOrderCompiler` `logical_operation_id` and `persistence.idempotency` conflict detection |

Rejected duplicates:

- a second work-order compiler;
- a role scorer that replaces `RoleResolver`;
- a new scheduler;
- an executor;
- a method event stream (the layer is pure and emits nothing).

## ProblemSignature and routing

`ObjectiveRequest` carries the objective plus structured, tri-state facts, where `None` means unknown and never false. Examples:

- `items_to_rank`, `options`;
- `problem_recurs`, `variation_observed`, `throughput_constrained`;
- `customer_needs_unknown`, `change_adoption_required`;
- `consequence`, `reversibility`, `externality`.

**Normalization.** Text is whitespace-collapsed. Set-like fields are deduplicated and sorted, and domains are lowercased. Equivalent requests therefore share a `request_hash` and a `plan_hash`.

**Classification is multi-label and evidence-gated.** Each family lists structural `signals`, such as "two or more options", or "a recurring problem with unknown cause". A family is selected only when a signal fires. Family `lexical_cues` (words in the objective) corroborate but never select on their own. Keyword-only families produce at most three `CLARIFICATION` gates. A request with no structural evidence yields an empty plan and `NO_STRUCTURAL_EVIDENCE`.

The `ProblemSignature` contains the specified fields plus one addition, `observations`: the structural facts that fired, which method applicability can cite.

## Six-slot stack compilation

**Needs.** Each selected family declares needs, each tagged with a slot:

| Slot | Example needs |
| --- | --- |
| MACRO | `macro:structured_cycle` |
| DIAGNOSE | `output:root_cause_identified` |
| DECIDE | `decision:option_selected` |
| EXECUTE | `execute:corrective_action_implemented` |
| CONTROL | `control:sustain_fix` |
| LEARN | `learn:lessons_captured` |

Signature-driven needs are added on top:

- a high-consequence decision needs `validation:decision_robustness`;
- uncertain strategy needs `output:scenarios_explored`;
- strategy execution without targets needs `output:goals_specified`.

A macro need is added only when the work spans at least three distinct slots. It is dropped, rather than reported as a gap, when no lifecycle methodology of the selected families applies.

**Selection** is greedy set cover over methods that are applicable and not contraindicated. A macro method must belong to a selected family. The ordering key is:

1. most uncovered needs;
2. lowest effort;
3. slot order;
4. `method_id`.

**Counterfactual pruning.** Each chosen method is removed in turn. If every need stays covered without it, it is pruned. Every survivor gets a `MinimalityCertificate` (`necessary_for`, `downstream_effect_if_removed`, `redundant: false`).

**Shadow duel.** This happens only during planning. At the first exact tie, the alternative stack is compiled and both are judged by the same rule:

1. fewest uncovered needs;
2. lowest total effort;
3. fewest methods;
4. lexical order.

At most two stacks are compared, and nothing executes for either.

**Conflicts** declared in the catalog are resolved in at most `MAX_ROUTER_PASSES` (3) passes. If they are still unresolved, `METHOD_CONFLICT_UNRESOLVED` is reported.

**Gaps stay gaps.** A need no applicable method covers is reported as `NO_APPLICABLE_METHOD:<need>`. For example, a corrective action with no known process to standardise.

Worked examples (from the tests):

| Request | Stack |
| --- | --- |
| "prioritize tasks" with three items | `impact_effort_matrix` only (short circuit) |
| recurring defect, cause unknown, process exists, no measurement | DMAIC → measurement-plan prerequisite → 5 Whys → Decision Matrix → Standard Work → Run Chart → After Action Review |
| choose among three options, high consequence, high uncertainty | weighted decision matrix + scenario analysis (+ FMEA via the risk family), with material-decision gates |

## Delegation envelopes

There is one envelope per method, plus the E3 prerequisite `prereq:measurement_plan` when measuring methods are needed but no measurement exists.

**Layers.** Envelopes are layered in slot order. The prerequisite sits just before DIAGNOSE (uncertainty first). Each node depends on the previous non-empty layer, so the DAG is acyclic by construction.

**Contents.** Each envelope carries:

- objective, family, method refs, inputs and outputs;
- acceptance criteria per output, and evidence requirements;
- an empty `tool_plan`;
- side-effect class, risk level, and **empty** authority and approval refs;
- idempotency class, retry limit, stop conditions and completion proof;
- `justified_by` (the needs it serves), and mutation targets.

**Proof-carrying context.** `context_hash` binds the envelope's objective, inputs, methods, evidence, acceptance, authority, tools, and each dependency's own context hash. `verify_context_chain` recomputes the chain, so an upstream change marks exactly its causal closure stale (`causal_closure`). A stale node is blocked, and only that closure is recompiled.

**Side effects.**

| Envelopes | Side-effect class | Retry limit |
| --- | --- | --- |
| Analysis and planning | DRAFT | 3 |
| EXECUTE-slot | REVERSIBLE_WRITE | 1 |
| EXECUTE-slot when the work is irreversible *and* external | IRREVERSIBLE_WRITE | 0, plus an exact-approval gate |

## Mission, work orders, waves

`mission_projection` builds the canonical mission payload, which contains capabilities, `task_graph.nodes` and `acceptance_contracts`. It also builds an **explicit `phase_map`**: each node's RoleOS phase comes from its family's catalog policy, never from prose.

Families resolve to existing RoleOS specialists through exact skill names. Some examples:

| Family | Specialist |
| --- | --- |
| Root cause | Business Analyst |
| Variation | Data Scientist |
| Risk | Compliance Manager |
| Change | Transformation Strategist |
| Reliability | Site Reliability Engineer |
| Learning | Learning & Development Manager |

An unresolvable capability raises `CAPABILITY_GAP`. No role is invented.

**Hard gates before ranking.** Gates are evaluated per node, before any ranking:

- capability match;
- schema;
- tool available (no tools are registered);
- permission;
- authority if required;
- approval if required;
- dependencies current;
- policy (irreversible work needs an exact approval).

RoleResolver's ranking only orders already-matched roles. A `ProofOfNonAuthority` per node checks that the work order holds no authority or approval refs beyond the envelope's. The required `authority_delta` is `0`; anything else raises `ROUTER_AUTHORITY_ESCALATION`. The tests inflate the routing score to 10⁹ and show that it changes nothing.

**Compatibility note.** The adapter knows two side-effect classes. It maps consequential nodes (`execution_mode: HUMAN`) to high-risk `REVERSIBLE_WRITE`, which requires authority and approval, and everything else to `PURE`. Envelopes keep the finer class (`DRAFT`, `IRREVERSIBLE_WRITE`) and their own gates. The mapping is never less restrictive than the envelope.

**Scheduling.** Cells and waves come from the existing scheduler:

- consequential and colliding work is serialized;
- gated work and its descendants are held with reasons;
- waves are capped at `MAX_SPECIALISTS_PER_WAVE` (8).

## Execution boundary: EXECUTOR_GAP

No generic executor consumes compiled work orders or mission cells in this codebase. `schedule_waves` and `advance_cell` are planning-time only. Every compiled mission therefore reports `executor_status: EXECUTOR_GAP`. The plan, work orders and waves are complete and callable:

- `compile_method_plan`;
- `compile_method_mission`;
- `orchestrate_brand_pipeline.py method-plan`.

No executor was added to fake completeness. The execution fabric ([`execution-fabric.md`](execution-fabric.md)) now consumes these waves without changing this module: method cells hold no N3 role contract and need an authored-text provider, so it reports them as `BLOCKED_AUTHORITY` (with `PROVIDER_GAP:llm_drafting` among the reasons) rather than executing them.

## Bounded control

`next_step(envelope, attempts)` decides what follows an attempt history. Every path is bounded:

| Condition | Outcome |
| --- | --- |
| Success | `DONE` |
| Same failure fingerprint twice | `CIRCUIT_BREAKER` → human |
| Retries exceed the envelope's limit (≤3) | escalate |
| Irreversible work | no automatic retry |
| Acceptance failure | `REPAIR` (≤3, smallest causal producer) |
| Three attempts without measurable progress | `RECLASSIFY_PROBLEM` (method drift) |
| Two retrieval passes with no new evidence, or 5 passes | escalate |
| Stale dependency | `INVALIDATE_AND_RECOMPILE` (closure only) |
| Missing authority or tool | escalate |

`mutation_key` derives a mutation identity from tenant, project, mission, node, operation and input hash, never from time or randomness. Reusing a key with a different payload conflicts in the existing idempotency store.

## Edge cases

| Case | Handling |
| --- | --- |
| E1 multi-problem | Families are unioned; shared needs are covered once. |
| E2 ambiguous outcome | At most 3 clarification gates, only for cue-only families. |
| E3 no measurable target | Measurement-plan prerequisite, recorded as an assumption. |
| E4 unmodeled output | Outputs are planning refs (`node#need`), never new N1 artifact types. |
| E5 no specialist | `CAPABILITY_GAP`. |
| E6 high score, no authority | Planning proceeds; execution is blocked. |
| E7 evidence gap | Unknown facts never satisfy predicates; gaps stay in `unresolved`. |
| E8 tool unavailable | `TOOL_UNAVAILABLE` blocker. |
| E9 repeated failure | Circuit breaker, then human. |
| E10 cycle or collision | Cycles raise `BackchainCycleError`; collisions serialize. |
| E11 change | Context-hash chain plus causal closure. |

## Not implemented, and why

- **CAPABILITY_SHADOW** (advisory-only participation by unauthorized specialists): no repository policy defines advisory participation, so none is added.
- **Policy weights** (`.24/.18/.16/.14/.10/.08/.06/.04`): RoleResolver's deterministic ranking (lexical tie-break) is reused as the spec prefers. No secondary ranking was needed.
- **API route, Zod twin and UI**: not justified yet. The CLI and Python entry points expose the layer.
- **Telemetry**: the layer is pure and emits nothing, so there is no runtime to instrument.
- **Method provenance**: every catalog entry is `DESCRIPTION_UNVERIFIED` with no `source_refs`. Descriptions are general summaries; no citation was verified in this change, and none is invented.
