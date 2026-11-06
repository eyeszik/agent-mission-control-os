# Unified delivery: contract, critic and the release handshake

Source: `AMC_UNIFIED_DELIVERY_METHOD_COMPILER_v5_PATCH` (spec SHA-256 `8248570f7f7f0e53e8ec178141847be2788d0238268c2ad46267fa856764c984`), applied to `master@9bf9d7f8`. The v4 base specification it patches was not available; see [Not implemented](#not-implemented-v4-only-clauses).

## ADR-0001: a delivery contract that adds proof, not authority

**Context.** Release was gated by N2 guards, a human approval bound to a hash of the run output, and the compile/invalidation gate. Nothing stated what "done" meant for a particular run, and the approval subject was the raw output rather than an exact, versioned release payload.

**Decision.**

1. A run may carry a `DeliveryContract`. A deterministic critic checks it. Only deterministic checks can produce PASS.
2. Before a reviewer decides, the API seals a `ReleaseCandidateManifest` naming the exact artifact versions, the contract and its result, the policy version and a dependency snapshot. In `enforce` mode, the existing approval record's `subject_hash` is bound to that candidate.
3. Release requires every conjunct of the release predicate (below). Afterwards a `ReleaseReceipt` records what was actually released.
4. The graph topology is pinned per run (`workflow_version`) and is never re-read from the environment on resume.
5. No new authority store is created. Every new object is either a contract, which defines success and grants nothing, or a derived, hash-linked proof.

**Consequences.**

- `AMC_CONTRACT_MODE=off` (the default) is the existing behaviour. New runs are pinned to `agency/v1-legacy`, and the response shape is unchanged.
- `shadow` runs `agency/v2-contract` and records verdicts. The approval still binds the legacy subject, so the release path is unchanged.
- `enforce` blocks release on the predicate.
- Runs created before pinning existed, or in any earlier mode, resume exactly as created.

## Owner map

| Concern | Owner | This change |
| --- | --- | --- |
| WHAT success means | `agency/delivery/contract.py` (`DeliveryContract`) | new; grants nothing |
| HOW work is organized | the live LangGraph pipeline (`graph/agency/build.py`) | unchanged; topology now defined in `agency/delivery/workflow.py` |
| WHO is eligible | N3 `roles.py`, RoleOS `RoleResolver` | unchanged |
| WHETHER release is permitted | N2 `lifecycle.py`, `approval_authority.py`, the approval record | unchanged; read by the predicate |
| Artifact and dependency state, invalidation | ProjectOS/N4 (`persistence/agency_kernel.py`, `projects.py`) | unchanged decisions; now also return a certificate |
| Execution | `graph.stream` in `api/routes/agency.py` | unchanged |
| Deterministic satisfaction | `agency/delivery/critic.py` | new |
| Exact pre-approval payload | `ReleaseCandidateManifest` | new, sealed before approval |
| Human authorization | the existing approval record and `assert_may_decide` | reused; `subject_hash` bound to the candidate |
| Proof of release | `ReleaseReceipt` (`ReleaseWitness` is an alias) | new evidence; never an authority |
| CRG, blast radius, lineage | `crg.py`, `blast_radius.py`, `execution_lineage_hash` | derived read models, no store |
| Canonical hashing | AMC-CANON-1 `canonical_hash()` | reused; not RFC 8785 |
| Idempotency | `persistence/idempotency.py`, trust-kernel claims | reused unchanged |

## Workflow version pinning (§2)

`agency/delivery/workflow.py` defines both topologies. `build_agency_workflow(version)` compiles from that same definition:

- `agency/v1-legacy`: the nine stages, interrupting before `delivery`.
- `agency/v2-contract`: adds `contract_check` between `brand_safety_qa` and `hitl_gate`. The static `interrupt_before=["delivery"]` is unchanged. No dynamic `interrupt()` is used.

At creation, the run's `metadata.workflow` records the following:

- `workflow_version`;
- `contract_mode`;
- `graph_fingerprint`, which is `canonical_hash({workflow_version, node_ids, edges, interrupt_points})`.

GET, resume and the contract view rebuild the graph from that pin. A run without a pin is `agency/v1-legacy`. If the code's topology for a version changes, its fingerprint changes too. A paused run pinned to the old fingerprint is then refused with a 409 rather than replayed through a different graph. Changing `AMC_CONTRACT_MODE` affects new runs only.

## Contract and critic (§8, §9)

```jsonc
{
  "schema_version": "amc-delivery-contract/v1",
  "contract_id": "launch-q4",
  "requirements": [
    {"requirement_id": "no-guarantees", "kind": "PHRASE_FORBIDDEN", "phrases": ["guaranteed returns"]},
    {"requirement_id": "ship", "kind": "FACT_PRESENT", "must_appear_verbatim": true,
     "fact": {"fact_id": "f1", "statement": "Ships in 2 days", "verification_ref": "<agency_evidence id>",
              "evidence_hash": "<evidence_record_hash>", "verified_at": "2026-10-01T00:00:00Z", "valid_until": null}},
    {"requirement_id": "legal", "kind": "HUMAN_REVIEW", "description": "Legal sign-off"}
  ]
}
```

| Kind | Rule |
| --- | --- |
| `FACT_PRESENT`, verbatim | NFC plus whitespace collapse, case-sensitive containment: PASS or FAIL. |
| `FACT_PRESENT`, non-verbatim | PASS or FAIL only with `equivalence: "normalized_text"`; otherwise NOT_MEASURED. |
| `PHRASE_FORBIDDEN` | Text is normalized: NFKC, then casefold, then Unicode punctuation and separators become spaces, format characters are removed, and whitespace is collapsed. The phrase must then match on token boundaries. |
| `PATTERN` | No linear-time engine is pinned, so a contract with a PATTERN requirement is rejected at intake with `REJECTED_PATTERN_ENGINE_UNAVAILABLE`. The critic never falls back to a backtracking regex. |
| `HUMAN_REVIEW` | Always NOT_MEASURED. The release approval, whose subject binds the contract hash, is the authorized decision. |

**Evidence freshness.** A fact is a claim-evidence relation. Its `verification_ref` resolves to an `agency_evidence` row in the run's own tenant and project.

The fact becomes `STALE_EVIDENCE` and NOT_MEASURED in any of these cases:

- the evidence is missing;
- it belongs to another scope;
- it is past its own freshness window;
- it is past the fact's `valid_until`;
- it was verified in the future;
- its current hash differs from `evidence_hash`.

**Definition of done (`dod`).** The values, in order of precedence:

| `dod` | Meaning |
| --- | --- |
| `FAIL` | A blocking check failed. |
| `ESCALATE` | A blocking check is NOT_MEASURED for a reason other than human review. |
| `NEEDS_HUMAN` | The only open blocking items are human reviews. |
| `PASS` | Every blocking check passed. |

Non-blocking results are advisory. An LLM cannot produce PASS.

**When the critic runs.** The critic runs three times:

1. in the `contract_check` node, where the verdict goes on the node's event;
2. again on the stored package when the candidate is sealed, after workspace export and artifact binding;
3. again by the release gate.

So a result computed for different content, or evidence that has since gone stale, cannot release.

## Two-phase release handshake (§3, §4)

1. **Candidate** (`amc-release-candidate/v1`). It names `run_id` and `project_id`, plus:
   - `contract_hash`;
   - `artifact_refs` (each `artifact_id`, `version_ref` and `content_hash`, sorted), covering the workspace-export artifacts and the protected run artifact;
   - `contract_result_refs`;
   - `policy_version` (`amc-release/v1`);
   - `dependency_snapshot_hash`, covering every dependency edge touching those artifacts together with the upstream versions.

   The schema forbids unknown fields. An approval decision, override, timestamp, receipt or `method_plan_hash` cannot be embedded.
2. **Approval subject.** The subject is `canonical_hash({candidate_manifest_hash, contract_hash, policy_version})`. It is bound to the run's pending approval before the API returns. If the approval was already decided at sealing time, it is marked stale, because that decision did not see this candidate. A plan-only change does not touch the subject (U20).
3. **Release predicate** (`evaluate_release_predicate`). Release requires every one of these:
   - `N2_PASS`;
   - `CONTRACT_DOD_PASS` (where `NEEDS_HUMAN` counts as passing only when the approval is an approve decision);
   - `APPROVAL_APPROVED_AND_NON_STALE`;
   - the approval's `subject_hash` equals the subject recomputed from current state;
   - `CURRENT_ARTIFACTS_MATCH`;
   - `CURRENT_DEPENDENCIES_MATCH`;
   - `COMPILE_INVALIDATION_GATE_PASS`.

   If the candidate drifted (artifacts, dependencies, contract result or subject), the approval is staled.
4. **Receipt** (`amc-release-receipt/v1`). It is sealed after delivery and before the run is marked completed. The protected run artifact's released hash is taken from the final payload, so delivery that altered the approved payload is caught. The run is then failed with an `OBSERVATION_MISMATCH` recovery case instead of completing (U16).

## API

- `POST /agency/runs` accepts an optional `delivery_contract`:
  - It is rejected with 422 when the mode is `off`.
  - It is required in `enforce`, otherwise 422.
  - An invalid `AMC_CONTRACT_MODE` returns 503.
  - Contract-pinned runs return these additional fields: `workflow`, `contract_evaluation`, `release_candidate` and `release_receipt`.
- `GET /agency/runs/{id}` and `POST /agency/runs/{id}/resume` use the run's pin.
- `GET /agency/runs/{id}/contract` is a read-only view. It returns the contract, evaluation, candidate, receipt and the CRG.
- `POST /projects/{id}/artifacts/{artifact}/revise`: its `blast_radius` now includes `certificate`.

## Derived read models (§6, §7)

**CRG** (`crg.py`). The graph is built from the contract, the result, the candidate, the live stage-to-role bindings and ProjectOS edges:

`Requirement → AcceptanceTest → (MethodPlanNode) → WorkOrder → ArtifactVersion → CheckResult`

- No MethodPlan exists, so plan nodes are empty and `plan_hash` is `null`.
- Live stages count as work orders justified by the repository invariant `AGENCY_PIPELINE_STAGES`. A work order without a justification is rejected.
- A blocking machine-checkable requirement with no artifact path makes the graph `PLAN_INCOMPLETE`.
- Inconsistent inputs raise `CRGInconsistency` (409). No edge is ever invented.

**BlastRadiusCertificate** (`blast_radius.py`). It is built inside `record_artifact_revision` from the decision ProjectOS just made, and contains:

- `before_hash` and `after_hash`;
- `changed_paths`;
- `affected_nodes`;
- `preserved_nodes`, which is always empty because ProjectOS preserves nothing on semantic grounds;
- `staled_approval_ids`;
- `reason_edges`;
- `projectos_decision_refs`.

The certificate cannot change what was invalidated. A test asserts that both modules import no persistence (U17).

## Observability (§13)

No exporter is added. Correctness does not depend on telemetry.

| Observation | Recorded as |
| --- | --- |
| `contract_check` | the existing `node_complete` event for that node |
| `release.gate` | a `node_complete` event with `node_id=release_gate` |

The gate event's outcome is one of `PERMITTED`, `BLOCKED`, `SHADOW_VERDICT`, `RELEASED` or `RECEIPT_MISMATCH`, and it carries the block codes and a failure class. Failure classes are `routing`, `contract`, `tool`, `authority`, `dependency`, `provider`, `evaluator` and `runtime`.

Payloads are built through `safe_attributes`. It refuses any attribute outside the safe set: identifiers, hashes, verdicts and counts. Prompts, contract text, matched phrases, PII and secrets never enter events. `execution_lineage_hash` hashes the run's ordered event chain into the receipt.

## Not implemented: v4-only clauses

The v5 patch states that unmentioned v4 clauses remain in force. The v4 text was not provided, so these are `VOID_DETECTED`, not invented:

- MethodRouter, the method catalog, ProblemSignature, MethodStack, MethodPlan and DelegationEnvelope;
- the four-layer router compiler (§11 A–D), MinimalityCertificate and ProofOfNonAuthority over router nodes;
- the routing weights `[.24,.18,.16,.14,.10,.08,.06,.04]`;
- planner provenance and `PLAN_VARIANCE` (§5) and mutant U14;
- the mission adapter and WorkOrderCompiler integration (M4, M5);
- the bounded repair loop (D4 repair);
- mutants D1–D11, M1–M11 and U1–U11, whose definitions are in v4;
- an OTel/Datadog adapter, which is optional and off by default.

Release-critical subjects contain no plan hash, so any future router cannot stale an approval through a method-only change (U20 is tested). Executor integration is `EXECUTOR_GAP`: the existing synchronous `graph.stream` executor is reused and no new external-mutation path is added.

## Activation

1. Run `shadow` and compare its `SHADOW_VERDICT` events against human decisions.
2. Switch to `enforce` for new runs. Paused runs keep their pinned mode.
3. To allow `PATTERN`, pin a linear-time engine (for example `google-re2`) in `services/langgraph` dependencies and set `PINNED_PATTERN_ENGINE`. Add tests.
