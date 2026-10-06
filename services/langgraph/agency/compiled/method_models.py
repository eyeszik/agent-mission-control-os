"""Strict models for method routing and delegation (docs/method-routing-delegation.md).

The method layer is a deterministic decision/delegation *compiler*. It turns an
objective into a minimal, justified stack of established methods and a bounded
DAG of delegation envelopes, then hands that to the canonical
``MissionWorkOrderAdapter`` / ``WorkOrderCompiler``. Nothing here grants
authority: every envelope carries empty authority and approval refs unless an
existing authority supplies them, and routing scores never feed permission.

All models are frozen and reject unknown fields. Hashes use the compiled
agency's canonical ``semantic_hash`` and exclude wall-clock or random data.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

POLICY_VERSION = "amc-method-policy/v1"
PLAN_VERSION = "amc-method-plan/v1"

# Bounds (spec §14). Stricter repository limits win where they exist: the
# WorkOrderCompiler already caps retry_limit at 3.
MAX_ROUTER_PASSES = 3
MAX_RETRIEVAL_PASSES = 5
MAX_TASK_RETRIES = 3
MAX_PLAN_REPAIRS = 3
MAX_DELEGATION_DEPTH = 4
MAX_SPECIALISTS_PER_WAVE = 8
MAX_TOOL_CALLS_PER_NODE = 12
MAX_SHADOW_STACKS = 2

TriState = Optional[bool]
Level = Literal["low", "medium", "high", "unknown"]
Consequence = Literal["low", "medium", "high", "critical", "unknown"]
Reversibility = Literal["reversible", "partially_reversible", "irreversible", "unknown"]
Externality = Literal["internal", "external", "unknown"]
Sensitivity = Literal["public", "internal", "confidential", "regulated", "unknown"]
EvidenceStatus = Literal["verified", "partial", "unverified", "conflicting", "unknown"]
SideEffectClass = Literal["PURE", "DRAFT", "REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"]


class Slot(str, Enum):
    MACRO = "MACRO"
    DIAGNOSE = "DIAGNOSE"
    DECIDE = "DECIDE"
    EXECUTE = "EXECUTE"
    CONTROL = "CONTROL"
    LEARN = "LEARN"


SLOT_ORDER: tuple[Slot, ...] = tuple(Slot)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObjectiveRequest(_Strict):
    """What a caller states. Structured facts are evidence; prose alone is not.

    Every boolean is tri-state: ``None`` means unknown, never "false".
    """

    objective: str = Field(min_length=1, max_length=2000)
    desired_outcome: str = Field(default="", max_length=2000)
    domains: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()
    items_to_rank: tuple[str, ...] = Field(default=(), max_length=500)
    options: tuple[str, ...] = Field(default=(), max_length=50)

    current_state_known: TriState = None
    target_state_known: TriState = None
    process_exists: TriState = None
    root_cause_known: TriState = None
    solution_known: TriState = None
    measurement_available: TriState = None

    problem_recurs: TriState = None
    variation_observed: TriState = None
    waste_observed: TriState = None
    throughput_constrained: TriState = None
    customer_needs_unknown: TriState = None
    deliverable_scope_defined: TriState = None
    strategic_question: TriState = None
    strategy_needs_alignment: TriState = None
    decision_rights_unclear: TriState = None
    change_adoption_required: TriState = None
    feedback_loops_suspected: TriState = None
    live_service: TriState = None
    incidents_recurring: TriState = None
    lessons_to_capture: TriState = None

    uncertainty: Level = "unknown"
    reversibility: Reversibility = "unknown"
    consequence: Consequence = "unknown"
    externality: Externality = "unknown"
    data_sensitivity: Sensitivity = "unknown"
    system_coupling: Level = "unknown"
    time_pressure: Level = "unknown"
    evidence_status: EvidenceStatus = "unknown"


class ProblemSignature(_Strict):
    """Multi-label, evidence-backed description of the problem (the genome).

    ``observations`` is the one addition to the specified field list: the
    structural facts that fired, so method applicability can cite them.
    """

    objective: str
    desired_outcome: str
    problem_families: tuple[str, ...]
    domains: tuple[str, ...]
    current_state_known: TriState
    target_state_known: TriState
    process_exists: TriState
    root_cause_known: TriState
    solution_known: TriState
    measurement_available: TriState
    uncertainty: Level
    reversibility: Reversibility
    consequence: Consequence
    externality: Externality
    data_sensitivity: Sensitivity
    system_coupling: Level
    time_pressure: Level
    change_adoption_required: TriState
    evidence_status: EvidenceStatus
    constraints: tuple[str, ...]
    non_goals: tuple[str, ...]
    observations: tuple[str, ...]


class FamilySpec(_Strict):
    family_id: str
    name: str
    capability_terms: tuple[str, ...] = Field(min_length=1)
    phase_id: str
    needs: dict[str, Slot]
    signals: tuple[str, ...] = Field(min_length=1)
    lexical_cues: tuple[str, ...] = ()


class MethodSpec(_Strict):
    method_id: str
    name: str
    family: str
    secondary_families: tuple[str, ...] = ()
    slot: Slot
    aliases: tuple[str, ...] = ()
    purpose: str
    applicability_predicates: tuple[str, ...] = ()
    contraindications: tuple[str, ...] = ()
    expected_inputs: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = Field(min_length=1)
    evidence_needs: tuple[str, ...] = ()
    composable_with: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    effort: int = Field(ge=1, le=5)
    source_refs: tuple[str, ...] = ()
    provenance_status: Literal["DESCRIPTION_UNVERIFIED", "SOURCE_CITED"]

    @model_validator(mode="after")
    def _provenance(self) -> "MethodSpec":
        if self.provenance_status == "SOURCE_CITED" and not self.source_refs:
            raise ValueError(f"{self.method_id}: SOURCE_CITED requires source_refs")
        return self


class MinimalityCertificate(_Strict):
    method_id: str
    necessary_for: tuple[str, ...] = Field(min_length=1)
    downstream_effect_if_removed: str
    redundant: Literal[False] = False


class ExcludedMethod(_Strict):
    method_id: str
    reason: str


class ShadowDuel(_Strict):
    candidates: tuple[str, ...]
    winner: str
    rule: str


class MethodStack(_Strict):
    macro_methodologies: tuple[str, ...] = ()
    diagnostic_methods: tuple[str, ...] = ()
    decision_methods: tuple[str, ...] = ()
    execution_methods: tuple[str, ...] = ()
    control_methods: tuple[str, ...] = ()
    learning_methods: tuple[str, ...] = ()
    excluded_methods: tuple[ExcludedMethod, ...] = ()
    source_refs: tuple[str, ...] = ()
    selection_confidence: float = Field(ge=0.0, le=1.0)
    stack_hash: str

    def selected(self) -> tuple[str, ...]:
        return (
            *self.macro_methodologies,
            *self.diagnostic_methods,
            *self.decision_methods,
            *self.execution_methods,
            *self.control_methods,
            *self.learning_methods,
        )


class DelegationEnvelope(_Strict):
    node_id: str
    objective: str
    problem_family: str
    method_refs: tuple[str, ...]
    dependencies: tuple[str, ...]
    required_capabilities: tuple[str, ...] = Field(min_length=1)
    inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    evidence_requirements: tuple[str, ...]
    tool_plan: tuple[str, ...] = Field(default=(), max_length=MAX_TOOL_CALLS_PER_NODE)
    side_effect_class: SideEffectClass
    risk_level: Literal["low", "medium", "high", "critical"]
    authority_refs: tuple[str, ...] = ()
    approval_refs: tuple[str, ...] = ()
    idempotency_class: SideEffectClass
    retry_limit: int = Field(ge=0, le=MAX_TASK_RETRIES)
    stop_conditions: tuple[str, ...]
    completion_proof: tuple[str, ...]
    slot: Slot
    justified_by: tuple[str, ...] = Field(min_length=1)
    delegation_depth: int = Field(default=1, ge=1, le=MAX_DELEGATION_DEPTH)
    mutation_targets: tuple[str, ...] = ()
    context_hash: str


class HumanGate(_Strict):
    gate_id: str
    node_id: Optional[str]
    kind: Literal["EXECUTION_AUTHORITY", "MATERIAL_DECISION", "CLARIFICATION"]
    requires: tuple[str, ...]
    separation_of_duties: bool = True
    enforced_by: str


class FamilyEvidence(_Strict):
    family_id: str
    structural_signals: tuple[str, ...]
    lexical_cues: tuple[str, ...]
    selected: bool


class MethodPlan(_Strict):
    version: Literal["amc-method-plan/v1"] = PLAN_VERSION
    policy_version: str = POLICY_VERSION
    catalog_hash: str
    request_hash: str
    problem_signature: ProblemSignature
    classification: tuple[FamilyEvidence, ...]
    method_stack: MethodStack
    minimality_certificates: tuple[MinimalityCertificate, ...]
    shadow_duels: tuple[ShadowDuel, ...] = Field(default=(), max_length=MAX_SHADOW_STACKS)
    delegation_envelopes: tuple[DelegationEnvelope, ...]
    human_gates: tuple[HumanGate, ...]
    unresolved: tuple[str, ...]
    plan_hash: str
