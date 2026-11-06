# Memory, KnowledgeOps and governed self-improvement

## Memory scopes

| Scope | Holds | Allowed authority |
| --- | --- | --- |
| M0_AGENCY | tenant-wide reusable workflows, templates, benchmarks | WORKING_CONTEXT |
| M1_BRAND_CANON | approved brand truth (must cite its source, e.g. a `brand_core` version) | BRAND_CANON |
| M2_PROJECT | requirements, decisions, open questions | APPROVED_PROJECT_DECISION, WORKING_CONTEXT |
| M3_CONVERSATION | thread-scoped instructions and references | WORKING_CONTEXT |
| M4_EVIDENCE | sources, claims, freshness, rights | VERIFIED_EVIDENCE, WORKING_CONTEXT |
| M5_PERFORMANCE | observed measurements | VERIFIED_EVIDENCE, WORKING_CONTEXT |
| M6_LEARNING | quarantined learning signals | LEARNING_SIGNAL |

Authority order: **BRAND_CANON > APPROVED_PROJECT_DECISION > VERIFIED_EVIDENCE > WORKING_CONTEXT > LEARNING_SIGNAL**.

- A scope can only hold the authority classes listed for it. A conversation can never mint brand canon.
- A write with *lower* authority than the active record for the same subject is **QUARANTINED**, never applied silently.
- A write with the same or higher authority supersedes the previous record.
- Resolution (`GET /projects/{id}/memory/resolve`) returns the highest-authority fresh record. It also reports every shadowed and stale alternative.
- At equal authority, project memory beats tenant-wide M0 memory. M0 only fills gaps.
- Writing BRAND_CANON or APPROVED_PROJECT_DECISION, promoting memory, and writing agency-wide M0 memory all require an approver role.
- **Isolation:** M1–M5 are never visible outside their project. Portfolio views carry counts only.

## KnowledgeOps

```
DISCOVER → FETCH → SANITIZE → INJECTION_SCAN → RIGHTS_CLASSIFY → CLAIM_EXTRACT
→ DATE/FRESHNESS → DEDUPE → TRIANGULATE → CONTRADICTION_CHECK → EVIDENCE_SCORE
→ CAPSULE → REVIEW → PROMOTE
```

`POST /projects/{id}/knowledge` runs the stages from SANITIZE through REVIEW on text the caller has already fetched. **Fetching is NOT_AVAILABLE** inside AMC: it is an external action and has no adapter.

- **Injection scan:** prompt-injection patterns reject the source outright.
- **Rights:** open licences and licensed sources keep short claims. A source with unknown rights is kept as `SUMMARY_ONLY` (claims only). For a source whose rights prohibit copying (`PROPRIETARY_NO_COPY`), no text is kept at all. The source body is never stored; at most 20 claims of up to 280 characters each are. This is the design corpus's provenance rule applied to research.
- **Freshness windows** by domain: provider cost 30 days, models 60, social 90, search 120, and so on.
- **Triangulation and contradiction** compare claims against the tenant's existing knowledge, using token similarity plus a negation check.
- **Evidence score** is deterministic, in the range 0–1:
  - +0.2 base;
  - +0.2 if rights are known;
  - +0.2 if fresh;
  - up to +0.3 for corroboration;
  - −0.3 if any claim is contradicted.
- **REVIEW → PROMOTE** is a human decision by an approver. A promoted item becomes M4 evidence memory: VERIFIED_EVIDENCE only when the score is at least 0.6, otherwise WORKING_CONTEXT.

## Governed self-improvement

The compiled-agency `LearningLedger` is now persisted (`learning_signals`). Each tenant's hash chain is replayed from the database, and every append goes through `LearningLedger.append`. The quarantine rules are therefore exactly the ones the planner already enforced:

- Signals may target only the permitted heuristic categories: routing ranking, context requirements, dependency templates, validator selection, estimation hints, tool-reliability recommendations and validated templates.
- A signal aimed at a protected class becomes a `GOVERNANCE_PROPOSAL`. The protected classes are: permissions, N1 ownership, N2 lifecycle, N3 authority, approval requirements, security, privacy, legal, provider permissions, secrets and governance thresholds.
- A signal without evidence is `REJECTED`.

Promotion flow (`/learning/promotions`):

```
SIGNAL → QUARANTINE → DATASET → BASELINE → SHADOW_TEST → DIGITAL_TWIN
→ REGRESSION_COMPARISON → GOVERNANCE_PROPOSAL → HUMAN_APPROVAL
→ VERSIONED_PROMOTION → MONITOR (→ ROLLBACK)
```

- Every stage needs evidence.
- A failed shadow test, digital-twin check or regression comparison ends the promotion.
- HUMAN_APPROVAL requires an approver.
- Protected targets can never enter the flow.
- A promotion is a *recorded, versioned decision*. Applying the tuned heuristic is still an operator action. Nothing in the flow mutates runtime policy.

`GET /projects/{id}/learning/post-mortem` is the AutomatedPostMortem. It reports measured operational facts:

- event counts;
- revisions per artifact;
- approval rate;
- QA blocks;
- publication attempts;
- job outcomes.

Campaign performance stays `UNKNOWN_NO_OBSERVED_METRICS` until real measurements exist.

## Growth experiments

`GrowthExperiment` records the hypothesis, target metric, segment, intervention, assets and sample requirement. When an experiment is concluded:

- An *observed* result with an `evidence_ref` is required.
- Below the sample requirement the decision is `INCONCLUSIVE`, whatever the reported lift.
- The conclusion appends a quarantined learning signal.
- Observed performance is kept separate from creative scores.
