"""Bounded offline fixtures for exercising H02; no model, research or experiment execution.

Every generated concept and score is explicitly simulated. Distinct text and lens
coverage are structural checks, not proof of novelty, feasibility or demand.
"""
from __future__ import annotations

from .contracts import (
    CommercialFields, Concept, Evaluation, Experiment, InnovationBrief, LineageEdge,
    PROMPT_VERSION, RunResult, Wildcard,
)
from services.langgraph.agency.execution.canonical import canonical_hash

RUBRICS = {
    "GENERAL/v1": {"Novelty": .30, "Impact": .25, "Coherence": .20, "Adaptability": .15, "Readiness": .10},
    "VENTURE/v1": {"Novelty": .25, "Profit": .25, "Automation": .15, "Defensibility": .15, "Market": .10, "Readiness": .10},
}
# Authored fixtures, not discoveries. Each entry specifies a different causal mechanism.
MECHANISMS = (
    ("L1", "Substitute ownership", "Replace one-time asset ownership with time-bounded access entitlements."),
    ("L1", "Combine feedback loops", "Pair action logs with reversible checkpoints to make feedback replayable."),
    ("L1", "Invert delivery order", "Deliver a removable prototype before committing to its supporting infrastructure."),
    ("L2", "Remove coordination tolls", "Remove per-interaction negotiations by publishing fixed interface commitments."),
    ("L2", "Serve nonparticipants", "Offer a read-only rehearsal route to people excluded by setup requirements."),
    ("L2", "Unbundle expertise", "Separate specialist diagnosis from implementation procurement decisions."),
    ("L3", "Separate conflicting modes", "Resolve precision-versus-speed tension with separate exploration and confirmation paths."),
    ("L3", "Localize complexity", "Confine expensive customization to replaceable boundary modules."),
    ("L3", "Precondition bottlenecks", "Precompute constraint checks before scarce specialist time is reserved."),
    ("L4", "Immune-style quarantine", "Quarantine anomalous inputs and require independent corroboration before reuse."),
    ("L4", "Mycelial routing", "Route a request across redundant local paths according to observed availability."),
    ("L4", "Dormant resource pools", "Keep infrequently needed capabilities dormant until a measured trigger activates them."),
    ("L5", "Rehearsal quests", "Break a high-stakes task into reversible practice challenges with explicit completion evidence."),
    ("L5", "Asymmetric collaboration", "Give collaborators complementary information so joint reconciliation creates the result."),
    ("L5", "Failure budget play", "Allocate a fixed number of safe failed trials before escalation to human review."),
    ("L6", "Recovery concierge", "Preserve context after a failure and offer the smallest recoverable next action."),
    ("L6", "Reciprocal continuity", "Exchange voluntary continuity preferences for fewer repeated setup decisions."),
    ("L6", "Quiet service lane", "Reserve an interruption-free path with deferred nonessential notifications."),
    ("L7", "Trigger-bound assistance", "Activate assistance at the observable moment an unmet job appears."),
    ("L7", "Outcome escrow", "Hold completion claims until the recipient checks the purchased outcome."),
    ("L7", "Switching rehearsal", "Let people test migration with disposable copies before changing their actual workflow."),
    ("L8", "Ratchet commitments", "Advance through one-way documented commitments only after a reversible rehearsal."),
    ("L8", "Flywheel batching", "Accumulate small compatible requests and discharge them as one bounded batch."),
    ("L8", "Mechanical fuse", "Interrupt a process automatically when independently measured load crosses a limit."),
    ("L9", "No central catalogue", "Discover available capacity from expiring local declarations instead of a global catalogue."),
    ("L9", "Unadvertised demand", "Collect opt-in problem diaries before describing possible offerings."),
    ("L9", "Deliberate subtraction", "Remove the most popular feature in a reversible sandbox to expose hidden dependencies."),
    ("L10", "Interoperability dividends", "Return reusable compatibility fixes to participants who expose shared integration failures."),
    ("L10", "Congestion feedback", "Reduce admission as shared congestion rises rather than maximizing concurrent requests."),
    ("L10", "Mutual audit rings", "Rotate independent reviewers across isolated projects without transferring private inputs."),
    ("L11", "Executable uncertainty", "Attach machine-readable unknowns to proposals so later evidence can invalidate them."),
    ("L11", "Counterexample memory", "Retrieve previous disconfirmations before proposing another similar solution."),
    ("L11", "Evidence compilation", "Compile source-bound claims into a draft that refuses unsupported release statements."),
    ("L12", "Lift setup constraint", "Replace mandatory installation with a disposable local demonstration."),
    ("L12", "Lift simultaneity", "Replace synchronous attendance with versioned contributions and explicit reconciliation."),
)
LIMITATIONS = [
    "SIMULATED: authored offline fixtures, not live model generation or verified innovations.",
    "No research was performed; claims remain unverified and originality is not established.",
    "Scores are subjective simulated decision aids, not probabilities or measured market outcomes.",
    "Experiments are unapproved drafts with NOT_RUN execution; no observations or learning are fabricated.",
    "HYBRID uses GENERAL/v1; AUTO conservatively defaults to GENERAL without inferring commercial intent.",
    "Semantic novelty, independent reviewer relevance and commercial demand require human validation.",
    "External execution is disabled; real providers require a separately authorized integration.",
]


def received_run(brief: InnovationBrief, run_id: str) -> RunResult:
    return RunResult(run_id=run_id, objective=brief.objective, mode="GENERAL" if brief.mode == "AUTO" else brief.mode,
                     status="RECEIVED", phase="RECEIVED", simulation=brief.provider == "simulated",
                     limitations=LIMITATIONS.copy())


def _seal(model_type, **fields):
    return model_type(**fields, content_hash=canonical_hash(fields))


def _concept(run_id, index, generation, title, mechanism, lenses, mode, objective, parent_ids=()):
    fields = dict(concept_id=f"{run_id}-c{index:02d}", generation=generation, title=title, mechanism=mechanism,
                  lens_tags=list(lenses), assumptions=["Fixture mechanism is applicable to the brief; this is unverified."],
                  speculative=True, provenance="SIMULATED_OFFLINE_FIXTURE", parent_ids=list(parent_ids),
                  commercial_fields=None, version=1)
    if mode == "VENTURE":
        commercial = CommercialFields(buyer="Hypothetical operator; validate through consented interviews",
            purchased_outcome=objective[:240], payment_model="Hypothetical fixed-fee pilot; willingness to pay unverified",
            differentiation_hypothesis=f"Test whether '{title}' changes the observed outcome versus current practice.")
        fields["commercial_fields"] = commercial.model_dump(mode="json")
    return _seal(Concept, **fields)


def _synthesize(run, parents, index, title, mechanism, generation):
    return _concept(run.run_id, index, generation, title, mechanism,
                    sorted({tag for p in parents for tag in p.lens_tags}), run.mode, run.objective,
                    tuple(p.concept_id for p in parents))


def _hybrids(run, ideas):
    plans = (
        ((1, 9), "Replayable quarantine", "Quarantine a suspect action, rehearse its recorded inverse, and use replay differences as corroboration."),
        ((6, 23), "Precision circuit breaker", "Switch exploration to confirmation mode at a measured load threshold before a scarce-resource queue saturates."),
        ((15, 31), "Counterexample concierge", "Recover a failed task by retrieving a matched disconfirmation and proposing a reversible context-preserving trial."),
        ((19, 29), "Independent outcome escrow", "Withhold completion credit until a rotating independent reviewer checks the recipient's outcome evidence."),
    )
    return [_synthesize(run, [ideas[a], ideas[b]], 36 + i, title, mechanism, "hybrid")
            for i, ((a, b), title, mechanism) in enumerate(plans)]


def _meta(run, hybrids):
    plans = (
        ("Evidence-clearing coordination", "Coordinate quarantined reversals through independent outcome escrow; only corroborated recovery evidence unlocks the next participant."),
        ("Adaptive recovery architecture", "Use load-triggered precision lanes to schedule counterexample-guided recovery, recycling trial failures as future admission constraints."),
    )
    return [_synthesize(run, [hybrids[i], hybrids[3-i]], 40 + i, title, mechanism, "meta")
            for i, (title, mechanism) in enumerate(plans)]


def _evaluate(concepts, mode):
    rubric = "VENTURE/v1" if mode == "VENTURE" else "GENERAL/v1"
    evaluations = []
    for i, concept in enumerate(concepts):
        scores = {key: float(2 + ((i + j) % 4)) for j, key in enumerate(RUBRICS[rubric])}
        composite = round(sum(weight * scores[key] for key, weight in RUBRICS[rubric].items()), 4)
        evaluations.append(Evaluation(concept_id=concept.concept_id, rubric_version=rubric,
            criterion_scores=scores, composite=composite,
            reviewer_notes="SIMULATED ordinal fixture scores assigned only after synthesis; no independent reviewer."))
    return evaluations


def _experiment(concept, index, constraints):
    fields = dict(experiment_id=f"{concept.concept_id}-e{index}", concept_id=concept.concept_id,
        hypothesis=f"In a local synthetic rehearsal, '{concept.title}' reduces failed constraint checks versus an unchanged baseline.",
        assumptions=[*concept.assumptions, *constraints],
        falsification_criteria="Disconfirm if candidate failures are equal to or greater than baseline, or any hard safety check fails.",
        method=f"Prepare 10 matched synthetic cases; compare baseline with this mechanism: {concept.mechanism} Record both outcomes without external effects.",
        measurements=["failed_constraint_checks / evaluated_cases", "hard_safety_failure_count", "elapsed_seconds"],
        success_rule="Candidate has fewer failed checks and zero hard safety failures; this tests rehearsal behavior only.",
        stop_conditions=["Stop at 10 cases or 60 seconds", "Stop on unexpected external effect or private data"],
        required_integrations=["A separately reviewed local experiment executor (not implemented in this slice)"],
        execution_class="RETRY_SAFE", execution_state="NOT_RUN", approval_state="NOT_REQUESTED",
        resource_budget={"max_cases": 10, "max_seconds": 60, "max_retries": 0, "max_external_calls": 0},
        evidence_refs=[], decision=None, learning=None, version=1)
    return _seal(Experiment, **fields)


def compile_run(brief: InnovationBrief, run_id: str) -> RunResult:
    """Compile one bounded offline cohort. This function performs no I/O or effects."""
    run = received_run(brief, run_id)
    if brief.provider == "live":
        return run.model_copy(update={"status": "BLOCKED", "phase": "PROVIDER_GAP",
            "limitations": ["PROVIDER_GAP: no operation-specific live generation authorization or adapter is configured."]})
    ideas = [_concept(run_id, i + 1, "raw", title, mechanism, [lens], run.mode, brief.objective)
             for i, (lens, title, mechanism) in enumerate(MECHANISMS)]
    hybrids = _hybrids(run, ideas)
    meta = _meta(run, hybrids)
    concepts = [*ideas, *hybrids, *meta]
    evaluations = _evaluate(concepts, run.mode)  # Explicit generation/synthesis barrier.
    ranking = sorted(evaluations, key=lambda e: (-e.composite, e.concept_id))
    shortlist = [e.concept_id for e in ranking[:4]]
    unconventional = ideas[26].concept_id
    shortlist.append(unconventional if unconventional not in shortlist else ranking[4].concept_id)
    by_id = {c.concept_id: c for c in concepts}
    return RunResult(**run.model_dump(exclude={"status", "phase", "ideas", "hybrids", "meta_hybrids", "evaluations", "shortlist", "wildcards", "lineage", "experiments"}),
        status="COMPLETED", phase="COMPLETED", ideas=ideas, hybrids=hybrids, meta_hybrids=meta,
        evaluations=evaluations, shortlist=shortlist,
        wildcards=[Wildcard(concept_id=c.concept_id, broken_assumption="The current coordination pattern is mandatory.",
            mechanism=c.mechanism, insight="SIMULATED: rehearse removal of this assumption before investing.") for c in ideas[24:29]],
        lineage=[LineageEdge(parent_id=p, child_id=c.concept_id,
            transformation="FIRST_ORDER_SYNTHESIS" if c.generation == "hybrid" else "SECOND_ORDER_SYNTHESIS",
            rationale="SIMULATED causal combination; inspect emergent mechanism and validate experimentally.")
            for c in [*hybrids, *meta] for p in c.parent_ids],
        experiments=[_experiment(by_id[cid], i + 1, brief.constraints) for i, cid in enumerate(shortlist)])
