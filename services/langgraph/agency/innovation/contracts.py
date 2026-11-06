"""Feature-local UNBOUND contracts. Simulation never supplies release authority."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

PROMPT_VERSION = "unbound-h02/simulation-v1"
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Mode = Literal["AUTO", "GENERAL", "VENTURE", "HYBRID"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class InnovationBrief(Contract):
    objective: str = Field(min_length=10, max_length=4000)
    mode: Mode = "AUTO"
    provider: Literal["simulated", "live"] = "simulated"
    constraints: list[Text] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def nonblank(self):
        if len(self.objective.strip()) < 10:
            raise ValueError("objective requires ten non-whitespace characters")
        return self


class CommercialFields(Contract):
    buyer: str
    purchased_outcome: str
    payment_model: str
    differentiation_hypothesis: str


class Concept(Contract):
    concept_id: str
    generation: Literal["raw", "hybrid", "meta"]
    title: str
    mechanism: str
    lens_tags: list[str] = Field(min_length=1, max_length=12)
    assumptions: list[str]
    speculative: Literal[True] = True
    provenance: Literal["SIMULATED_OFFLINE_FIXTURE"] = "SIMULATED_OFFLINE_FIXTURE"
    parent_ids: list[str] = Field(default_factory=list, max_length=5)
    commercial_fields: CommercialFields | None = None
    version: Literal[1] = 1
    content_hash: str


class Wildcard(Contract):
    concept_id: str
    broken_assumption: str
    mechanism: str
    insight: str


class LineageEdge(Contract):
    parent_id: str
    child_id: str
    source_version: Literal[1] = 1
    transformation: Literal["FIRST_ORDER_SYNTHESIS", "SECOND_ORDER_SYNTHESIS"]
    rationale: str


class Evaluation(Contract):
    concept_id: str
    rubric_version: Literal["GENERAL/v1", "VENTURE/v1"]
    criterion_scores: dict[str, float]
    composite: float = Field(ge=0, le=5)
    evidence_status: Literal["SIMULATED"] = "SIMULATED"
    reviewer_notes: str


class Experiment(Contract):
    experiment_id: str
    concept_id: str
    hypothesis: str
    assumptions: list[str]
    falsification_criteria: str
    method: str
    measurements: list[str] = Field(min_length=1)
    success_rule: str
    stop_conditions: list[str] = Field(min_length=1)
    required_integrations: list[str]
    execution_class: Literal["RETRY_SAFE"] = "RETRY_SAFE"
    execution_state: Literal["NOT_RUN"] = "NOT_RUN"
    approval_state: Literal["NOT_REQUESTED"] = "NOT_REQUESTED"
    resource_budget: dict[str, int]
    evidence_refs: list[str] = Field(default_factory=list, max_length=0)
    decision: None = None
    learning: None = None
    version: Literal[1] = 1
    content_hash: str


class RunResult(Contract):
    run_id: str
    objective: str
    mode: Literal["GENERAL", "VENTURE", "HYBRID"]
    status: Literal["COMPLETED", "BLOCKED", "CANCELLED", "PAUSED", "RECEIVED"]
    phase: Literal["RECEIVED", "COMPLETED", "PROVIDER_GAP", "RETRY_EXHAUSTED", "PAUSED", "CANCELLED"]
    simulation: bool
    prompt_version: Literal["unbound-h02/simulation-v1"] = PROMPT_VERSION
    ideas: list[Concept] = Field(default_factory=list, max_length=35)
    wildcards: list[Wildcard] = Field(default_factory=list, max_length=5)
    hybrids: list[Concept] = Field(default_factory=list, max_length=4)
    meta_hybrids: list[Concept] = Field(default_factory=list, max_length=2)
    lineage: list[LineageEdge] = Field(default_factory=list, max_length=30)
    shortlist: list[str] = Field(default_factory=list, max_length=5)
    evaluations: list[Evaluation] = Field(default_factory=list, max_length=41)
    experiments: list[Experiment] = Field(default_factory=list, max_length=5)
    evidence: list[dict] = Field(default_factory=list, max_length=0)
    limitations: list[str]
    usage: None = None

    @model_validator(mode="after")
    def integrity(self):
        validate_result(self)
        return self


def _hash_fields(model: Contract) -> str:
    return canonical_hash(model.model_dump(mode="json", exclude={"content_hash"}))


def validate_result(run: RunResult) -> None:
    concepts = [*run.ideas, *run.hybrids, *run.meta_hybrids]
    if run.status != "COMPLETED" and any((concepts, run.evaluations, run.experiments, run.wildcards, run.shortlist, run.lineage)):
        raise ValueError("preterminal and provider-blocked states cannot contain scored or completed output")
    allowed_phases = {"PROVIDER_GAP", "RETRY_EXHAUSTED"} if run.status == "BLOCKED" else {run.status}
    if run.phase not in allowed_phases:
        raise ValueError("status and phase disagree")
    by_id = {c.concept_id: c for c in concepts}
    if len(by_id) != len(concepts):
        raise ValueError("duplicate concept ID")
    mechanisms = [" ".join(c.mechanism.casefold().split()) for c in concepts]
    if len(set(mechanisms)) != len(mechanisms):
        raise ValueError("duplicate mechanism")
    if any(c.generation != kind for group, kind in ((run.ideas, "raw"), (run.hybrids, "hybrid"), (run.meta_hybrids, "meta")) for c in group):
        raise ValueError("concept is in the wrong generation collection")
    if len({e.concept_id for e in run.evaluations}) != len(run.evaluations):
        raise ValueError("duplicate evaluation")
    if len({e.experiment_id for e in run.experiments}) != len(run.experiments):
        raise ValueError("duplicate experiment ID")
    _validate_concepts(concepts, by_id, run.mode)
    _validate_edges(run, by_id)
    if len(set(run.shortlist)) != len(run.shortlist) or not set(run.shortlist) <= by_id.keys():
        raise ValueError("invalid shortlist references")
    for exp in run.experiments:
        bounds = {"max_cases": 10, "max_seconds": 60, "max_retries": 0, "max_external_calls": 0}
        if set(exp.resource_budget) != set(bounds) or any(
            not 0 <= value <= bounds[key] for key, value in exp.resource_budget.items()
        ):
            raise ValueError("experiment resource budget exceeds the supported offline bounds")
        if exp.concept_id not in run.shortlist or exp.content_hash != _hash_fields(exp):
            raise ValueError("invalid experiment reference or hash")
    for evaluation in run.evaluations:
        if evaluation.concept_id not in by_id:
            raise ValueError("invalid evaluation reference")
        from .compiler import RUBRICS
        weights = RUBRICS[evaluation.rubric_version]
        if set(weights) != set(evaluation.criterion_scores) or any(
            not 0 <= s <= 5 for s in evaluation.criterion_scores.values()
        ):
            raise ValueError("invalid criterion scores")
        expected = round(sum(weights[k] * evaluation.criterion_scores[k] for k in weights), 4)
        if expected != evaluation.composite:
            raise ValueError("invalid composite")
    if run.status == "COMPLETED":
        _validate_completed(run)


def _validate_concepts(concepts, by_id, mode):
    for concept in concepts:
        if concept.content_hash != _hash_fields(concept):
            raise ValueError("concept hash mismatch")
        if not set(concept.lens_tags) <= {f"L{i}" for i in range(1, 13)}:
            raise ValueError("unknown innovation lens")
        if mode == "VENTURE" and concept.commercial_fields is None:
            raise ValueError("venture concept requires commercial hypotheses")
        if concept.generation == "raw" and concept.parent_ids:
            raise ValueError("raw concept cannot have parents")
        if len(set(concept.parent_ids)) != len(concept.parent_ids):
            raise ValueError("duplicate parent reference")
        required = "raw" if concept.generation == "hybrid" else "hybrid"
        for parent in concept.parent_ids:
            if parent not in by_id or by_id[parent].generation != required:
                raise ValueError("dangling, cyclic or wrong-generation lineage")
        if concept.generation != "raw" and len(concept.parent_ids) < 2:
            raise ValueError("synthesis requires multiple parents")


def _validate_edges(run, by_id):
    expected = {(p, c.concept_id) for c in by_id.values() for p in c.parent_ids}
    edges = [(e.parent_id, e.child_id) for e in run.lineage]
    if len(edges) != len(set(edges)) or set(edges) != expected:
        raise ValueError("lineage must exactly record every parent-child edge")
    for edge in run.lineage:
        kind = "FIRST_ORDER_SYNTHESIS" if by_id[edge.child_id].generation == "hybrid" else "SECOND_ORDER_SYNTHESIS"
        if edge.transformation != kind:
            raise ValueError("lineage transformation mismatch")
    for wildcard in run.wildcards:
        if wildcard.concept_id not in {c.concept_id for c in run.ideas}:
            raise ValueError("wildcard must reference a raw idea")
        if wildcard.mechanism != by_id[wildcard.concept_id].mechanism:
            raise ValueError("wildcard mechanism mismatch")


def _validate_completed(run):
    counts = (len(run.ideas), len(run.wildcards), len(run.hybrids), len(run.meta_hybrids), len(run.shortlist), len(run.experiments))
    if counts != (35, 5, 4, 2, 5, 5):
        raise ValueError("completed simulation requires complete bounded cohort")
    if not run.simulation or run.phase != "COMPLETED":
        raise ValueError("only simulated completion is implemented")
    if set(t for c in run.ideas for t in c.lens_tags) != {f"L{i}" for i in range(1, 13)}:
        raise ValueError("all twelve innovation lenses are required")
    if len({w.concept_id for w in run.wildcards}) != 5:
        raise ValueError("wildcards must be distinct")
    if {e.concept_id for e in run.experiments} != set(run.shortlist):
        raise ValueError("each shortlisted candidate needs an experiment")
    if {e.concept_id for e in run.evaluations} != {c.concept_id for c in [*run.ideas, *run.hybrids, *run.meta_hybrids]}:
        raise ValueError("evaluate each concept after synthesis")
