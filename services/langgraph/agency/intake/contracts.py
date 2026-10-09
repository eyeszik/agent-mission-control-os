"""Typed contracts for the governed intake slice.

One vertical path from a user's words to a release decision:

    request -> CompiledIntent -> ProjectResolutionReceipt -> ContextCapsule
            -> MissionContract -> execution fabric -> ArtifactVerification
            -> approval (existing approvals table) -> ReleaseVerdict

Everything here is a record of what was decided and why. None of it is
authority: the principal comes from ``security.auth``, approvals come from the
existing approvals table and route, and execution goes through the existing
execution fabric. Natural-language classification never grants anything.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

INTAKE_VERSION = "amc-intake/v1"
_HASH = r"^[a-f0-9]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExecutionMode(str, Enum):
    """REAL_EXECUTION is the default for a production mission. SIMULATION is opt-in,
    set server-side, and its outputs are never production or release eligible."""

    REAL_EXECUTION = "REAL_EXECUTION"
    SIMULATION = "SIMULATION"


class FactType(str, Enum):
    EXPLICIT = "EXPLICIT"
    PROJECT_CANONICAL = "PROJECT_CANONICAL"
    EVIDENCE_DERIVED = "EVIDENCE_DERIVED"
    WORKING_CONTEXT = "WORKING_CONTEXT"
    SAFE_DEFAULT = "SAFE_DEFAULT"
    AMBIGUOUS_NONCRITICAL = "AMBIGUOUS_NONCRITICAL"
    AMBIGUOUS_CRITICAL = "AMBIGUOUS_CRITICAL"
    FORBIDDEN_TO_INFER = "FORBIDDEN_TO_INFER"


class UtteranceType(str, Enum):
    REQUEST = "REQUEST"
    INSTRUCTION = "INSTRUCTION"
    PREFERENCE = "PREFERENCE"
    FACT_CLAIM = "FACT_CLAIM"
    QUESTION = "QUESTION"
    CORRECTION = "CORRECTION"
    REFERENCE = "REFERENCE"
    APPROVAL_CANDIDATE = "APPROVAL_CANDIDATE"
    REVOCATION_CANDIDATE = "REVOCATION_CANDIDATE"


class Deliverable(str, Enum):
    """Deliverable families this slice can route. Each maps to an N1 artifact type
    and an execution-fabric skill; families with no installed provider stay blocked."""

    VECTOR_MARK = "VECTOR_MARK"            # media_asset via brand_logo_svg (deterministic local SVG)
    RASTER_IMAGE = "RASTER_IMAGE"          # media_asset via t2i_image_generate (no provider installed)
    DESIGN_TOKENS = "DESIGN_TOKENS"        # design_token_set via dtcg_token_compile
    GENERATED_VIDEO = "GENERATED_VIDEO"    # media_asset via ai_video_generate (no provider installed)


class SideEffect(str, Enum):
    PUBLISH = "PUBLISH"
    SPEND = "SPEND"
    SEND = "SEND"


class PredicateState(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BLOCKED = "BLOCKED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    NOT_EXECUTED = "NOT_EXECUTED"


class IntentFact(_Strict):
    kind: str
    value: Any
    fact_type: FactType
    span: Optional[tuple[int, int]] = None  # character offsets into the raw request
    note: str = ""


class CompiledIntent(_Strict):
    intake_version: Literal["amc-intake/v1"] = INTAKE_VERSION
    raw_request: str
    request_hash: str = Field(pattern=_HASH)
    utterance_type: UtteranceType
    deliverable: Optional[Deliverable]
    side_effects: tuple[SideEffect, ...]
    explicit_project_ids: tuple[str, ...]
    mode: ExecutionMode
    facts: tuple[IntentFact, ...]
    clarifications: tuple[str, ...] = Field(default=(), max_length=3)


class ProjectCandidate(_Strict):
    project_id: str
    display_name: str
    basis: tuple[str, ...]  # e.g. EXPLICIT_ID, ACTIVE_CONTEXT, NAME_MATCH, SLUG_MATCH, BRAND_MATCH
    rank: int               # lexicographic tier; lower wins. Not a probability.


class ProjectResolutionReceipt(_Strict):
    status: Literal["BOUND", "AMBIGUOUS", "UNRESOLVED", "DENIED"]
    project_id: Optional[str]
    candidates: tuple[ProjectCandidate, ...]
    # Counts only: an inaccessible project is never named, so the receipt cannot
    # leak another project's existence.
    hard_filtered: dict[str, int]
    reasons: tuple[str, ...]
    needs_confirmation: bool
    tenant_id: str
    resolved_at: str


class MemoryChoice(_Strict):
    subject_key: str
    memory_id: Optional[str]
    authority: Optional[str]
    scope: Optional[str]
    content_hash: Optional[str]
    status: Literal["RESOLVED", "UNRESOLVED", "UNRESOLVED_STALE", "CONFLICT", "BELOW_AUTHORITY_FLOOR", "EXCLUDED_BUDGET"]
    shadowed: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    excluded_other_thread: tuple[str, ...] = ()


class MemoryUseReceipt(_Strict):
    tenant_id: str
    project_id: str
    thread_id: Optional[str]
    as_of: str
    authority_floor: dict[str, str]
    choices: tuple[MemoryChoice, ...]
    context_hash: str = Field(pattern=_HASH)


class ContextCapsule(_Strict):
    """The minimal context a mission needs, with what was left out and why."""

    project_id: str
    project_fingerprint: str = Field(pattern=_HASH)
    memory: dict[str, Any]          # subject_key -> resolved body (only RESOLVED subjects)
    unknowns: tuple[str, ...]       # subjects with no admissible record
    exclusions: dict[str, str]      # memory_id or subject -> reason
    byte_budget: int
    byte_size: int
    capsule_hash: str = Field(pattern=_HASH)


class AcceptancePredicate(_Strict):
    predicate_id: str
    description: str
    state: PredicateState = PredicateState.PENDING
    evidence: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class MissionContract(_Strict):
    intake_version: Literal["amc-intake/v1"] = INTAKE_VERSION
    mission_id: str
    tenant_id: str
    project_id: str
    thread_id: Optional[str]
    requested_by: str
    objective: str
    deliverable: Deliverable
    artifact_type: str
    side_effects: tuple[SideEffect, ...]
    acceptance_predicates: tuple[AcceptancePredicate, ...]
    assumptions: tuple[IntentFact, ...]
    unknowns: tuple[str, ...]
    execution_mode: ExecutionMode
    request_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    created_at: str

    @property
    def contract_hash(self) -> str:
        from services.langgraph.agency.execution.canonical import canonical_hash

        body = self.model_dump(mode="json")
        body.pop("created_at", None)
        body.pop("acceptance_predicates", None)
        return canonical_hash(body)


class ArtifactVerification(_Strict):
    """Independent read-back of persisted bytes. Never trusts the producer's output."""

    artifact_id: str
    version: int
    content_hash: Optional[str]
    status: Literal["PASSED", "FAILED", "INCONCLUSIVE", "NOT_EXECUTED"]
    basis: Literal["DETERMINISTIC", "TOOL_OBSERVED", "MODEL_ASSESSED", "HUMAN_REVIEWED"] = "DETERMINISTIC"
    checks: tuple[dict, ...]
    findings: tuple[str, ...]
    verifier: str
    verified_at: str


class NonActionReceipt(_Strict):
    """A denied external effect. States only what this process can observe."""

    effect: SideEffect
    policy_gate: str
    dispatched: Literal[False] = False
    observation: str
    observed_counts_before: dict[str, int]
    observed_counts_after: dict[str, int]
    limits: str = (
        "Covers dispatch paths inside this AMC process and the project's own publication and job tables. "
        "It does not prove that no other system acted."
    )


class ReleaseVerdict(_Strict):
    allowed: bool
    reasons: tuple[str, ...]
    artifact_id: Optional[str]
    artifact_version: Optional[int]
    artifact_hash: Optional[str]
    approval_id: Optional[str]
    external_effects: Literal["none"] = "none"


class MissionOutcome(_Strict):
    status: Literal["AWAITING_APPROVAL", "BLOCKED", "NEEDS_CLARIFICATION", "SIMULATED", "FAILED"]
    intent: CompiledIntent
    resolution: ProjectResolutionReceipt
    memory: Optional[MemoryUseReceipt] = None
    context: Optional[ContextCapsule] = None
    mission: Optional[MissionContract] = None
    execution: Optional[dict] = None          # MissionExecutionReport, as JSON
    verification: Optional[ArtifactVerification] = None
    approval: Optional[dict] = None
    non_actions: tuple[NonActionReceipt, ...] = ()
    simulation: bool = False
    production_eligible: bool = False
    release_eligible: bool = False
    reasons: tuple[str, ...] = ()


__all__ = [
    "AcceptancePredicate",
    "ArtifactVerification",
    "CompiledIntent",
    "ContextCapsule",
    "Deliverable",
    "ExecutionMode",
    "FactType",
    "INTAKE_VERSION",
    "IntentFact",
    "MemoryChoice",
    "MemoryUseReceipt",
    "MissionContract",
    "MissionOutcome",
    "NonActionReceipt",
    "PredicateState",
    "ProjectCandidate",
    "ProjectResolutionReceipt",
    "ReleaseVerdict",
    "SideEffect",
    "UtteranceType",
]
