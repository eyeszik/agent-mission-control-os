"""Typed records for the creative-direction pipeline (PROPOSED definitions; the original board spec was not supplied).

Every record binds tenant/project/brand, the artifact versions and hashes it was computed from, the genome version,
and the compiler/rubric versions. Server-observed facts (``observed``) are kept apart from author-reported metadata
(``reported``); evidence class is kept apart from provenance and from approval state. Nothing here is authority:
the approved genome is, and approvals are decided only on ``/approvals/{id}/decide``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import Field

from services.langgraph.agency.execution.canonical import canonical_hash

from ..genome import _Strict

SCHEMA = "amc-vnexus-directions/v1"
RUBRIC_VERSION = "amc-vnexus-review-rubric/1.0.0"
INTENT_COMPILER_VERSION = "amc-vnexus-intent/1.0.0"
NONE = "@none"


class AssetRole(str, Enum):
    LOGO_MARK = "LOGO_MARK"
    WORDMARK = "WORDMARK"
    LOCKUP = "LOCKUP"
    ICON = "ICON"
    ILLUSTRATION = "ILLUSTRATION"
    HERO_IMAGE = "HERO_IMAGE"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    TEXTURE = "TEXTURE"


VECTOR_REQUIRED = frozenset({AssetRole.LOGO_MARK, AssetRole.WORDMARK, AssetRole.LOCKUP, AssetRole.ICON})
RASTER_NATIVE = frozenset({AssetRole.PHOTOGRAPHY, AssetRole.TEXTURE})
LOGO_ROLES = frozenset({AssetRole.LOGO_MARK, AssetRole.WORDMARK, AssetRole.LOCKUP})


class VectorNeed(str, Enum):
    REQUIRED = "REQUIRED"          # editable paths are needed for this role
    OPTIONAL = "OPTIONAL"          # only on explicit request
    KEEP_RASTER = "KEEP_RASTER"    # photography/texture: vectorization adds no value


def vector_need(role: AssetRole) -> VectorNeed:
    if role in VECTOR_REQUIRED:
        return VectorNeed.REQUIRED
    return VectorNeed.KEEP_RASTER if role in RASTER_NATIVE else VectorNeed.OPTIONAL


class EvidenceClass(str, Enum):
    OBSERVED = "OBSERVED"    # directly inspected pixels, geometry or supplied source (evidence_source says which)
    INFERRED = "INFERRED"    # interpretation or predicted response
    PROPOSED = "PROPOSED"    # creative recommendation
    UNKNOWN = "UNKNOWN"      # unavailable or unresolved


class EvidenceSource(str, Enum):
    PIXELS = "PIXELS"
    GEOMETRY = "GEOMETRY"
    SUPPLIED_SOURCE = "SUPPLIED_SOURCE"
    BRIEF = "BRIEF"
    NONE = "NONE"


class ProvenanceClass(str, Enum):
    RECORDED = "RECORDED"            # bytes produced by an adapter this server ran; parameters and receipts recorded
    USER_REPORTED = "USER_REPORTED"  # manual import; provider/model/seed/cost are the importer's statement, unverified
    SIMULATED = "SIMULATED"          # test stand-in; never an asset, never selectable, never a master


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    NOTE = "NOTE"


class ReviewMode(str, Enum):
    QUICK = "QUICK"
    FULL = "FULL"
    COMPARE = "COMPARE"
    REFINE = "REFINE"
    VECTOR = "VECTOR"
    RELEASE = "RELEASE"


class Verdict(str, Enum):
    BLOCKED = "BLOCKED"
    REVISE = "REVISE"
    RECOMMENDED_DIRECTION = "RECOMMENDED_DIRECTION"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    INCONCLUSIVE = "INCONCLUSIVE"


class Gate(str, Enum):
    EXACT_IDENTITY_TEXT = "EXACT_IDENTITY_TEXT"
    ACCESSIBILITY = "ACCESSIBILITY"
    SAFETY_PRIVACY_RIGHTS = "SAFETY_PRIVACY_RIGHTS"
    CANONICAL_INTEGRITY = "CANONICAL_INTEGRITY"
    OUTPUT_PROVENANCE = "OUTPUT_PROVENANCE"


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssessorKind(str, Enum):
    LOCAL_MEASUREMENT = "LOCAL_MEASUREMENT"   # deterministic checks on stored bytes; never a creative score
    HUMAN = "HUMAN"
    MODEL = "MODEL"                           # no vision route is enabled; kept for the contract only


class Assessor(_Strict):
    kind: AssessorKind
    id: str = Field(min_length=1, max_length=200)
    version: Optional[str] = Field(default=None, max_length=120)


# --------------------------------------------------------------------------- intake / intent


class ReferenceIn(_Strict):
    ref_id: str = Field(min_length=1, max_length=200)
    role: Literal["principle_only", "approved_asset"] = "principle_only"
    rights: Literal["owned", "licensed", "unknown"] = "unknown"


Decided = Union[Literal["@none"], str, None]


class DirectionBrief(_Strict):
    """Intake. ``None`` means not supplied (UNKNOWN); ``"@none"`` is an intentional NONE decision."""

    asset_role: AssetRole
    objective: str = Field(min_length=1, max_length=1000)
    audience: Decided = Field(default=None, max_length=300)
    category: Decided = Field(default=None, max_length=200)
    exact_text: Union[Literal["@none"], list[str], None] = None
    references: list[ReferenceIn] = Field(default_factory=list, max_length=12)
    rights_constraints: Decided = Field(default=None, max_length=1000)
    privacy_constraints: Decided = Field(default=None, max_length=1000)
    applications: Union[Literal["@none"], list[str], None] = None
    emotional_targets: list[str] = Field(default_factory=list, max_length=6)
    directions: list[str] = Field(default_factory=list, max_length=4)
    candidate_count: int = Field(default=3, ge=1, le=4)
    budget_minor: int = Field(default=0, ge=0, le=10_000_000)
    width: int = Field(default=1024, ge=64, le=4096)
    height: int = Field(default=1024, ge=64, le=4096)


class FieldDecision(_Strict):
    field: str
    status: Literal["VALUE", "NONE", "UNKNOWN"]
    consequence: str = ""


class SlotInstruction(_Strict):
    slot: int
    direction: str
    prompt: str
    negative_prompt: str
    parameters: dict[str, Any]
    prompt_hash: str
    compose_mark: Optional[str] = None   # local.foundry_compose: the deterministic mark id for this slot


class CreativeIntent(_Strict):
    schema_version: str = SCHEMA
    compiler_version: str = INTENT_COMPILER_VERSION
    intent_id: str
    tenant_id: str
    project_id: str
    brand_id: str
    scope: str
    scope_ref: str
    genome_ref: str
    resolution_hash: str
    asset_role: AssetRole
    vector_need: VectorNeed
    brief: DirectionBrief
    brief_hash: str
    field_decisions: tuple[FieldDecision, ...]
    prohibited: tuple[str, ...] = ()
    status: Literal["READY", "BLOCKED_INPUT"]
    blockers: tuple[str, ...] = ()
    shared: dict[str, Any]
    prompt_compiler: dict[str, Any]
    image_instructions: tuple[SlotInstruction, ...]
    vector_instructions: dict[str, Any]
    dependency_hash: str


# --------------------------------------------------------------------------- candidates


class CandidateObserved(_Strict):
    sha256: str
    readback_sha256: str
    mime: str
    bytes: int
    width: Optional[int] = None
    height: Optional[int] = None
    stored_at: str
    artifact_id: Optional[str] = None        # None only for SIMULATED output, which is kept out of the project's deliverables
    artifact_version: Optional[int] = None
    storage_uri: Optional[str] = None
    format_class: Literal["VECTOR", "RASTER_IN_SVG", "RASTER"]


class CandidateReported(_Strict):
    """What the importer (or a recorded adapter) states. For USER_REPORTED candidates nothing here is verified."""

    provider: Optional[str] = Field(default=None, max_length=120)
    model: Optional[str] = Field(default=None, max_length=200)
    model_version: Optional[str] = Field(default=None, max_length=120)
    seed: Optional[int] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    generated_at: Optional[str] = Field(default=None, max_length=40)
    job_ref: Optional[str] = Field(default=None, max_length=200)
    receipt_ref: Optional[str] = Field(default=None, max_length=200)
    cost_minor: Optional[int] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, max_length=8)
    rights_basis: Optional[str] = Field(default=None, max_length=500)
    reference_ids: list[str] = Field(default_factory=list, max_length=12)
    prompt_used: Optional[str] = Field(default=None, max_length=8000)


class GenerationCandidate(_Strict):
    candidate_id: str
    intent_id: str
    slot: int
    direction: str
    prompt_hash: str
    genome_ref: str
    intent_dependency_hash: str
    route_id: str
    provenance: ProvenanceClass
    observed: CandidateObserved
    reported: CandidateReported
    cost_measured_minor: Optional[int] = None   # only when an adapter measured it; never copied from a report
    near_duplicate_of: Optional[str] = None
    derived_from: Optional[str] = None          # a reconstruction's source candidate
    reconstruction_id: Optional[str] = None
    perceptual_hash: Optional[str] = None
    created_by: str
    created_at: str


# --------------------------------------------------------------------------- review


class FindingIn(_Strict):
    """A reviewer-supplied finding. ``candidate`` is the blinded label (COMPARE) or candidate id."""

    candidate: str = Field(min_length=1, max_length=120)
    criterion: str = Field(min_length=1, max_length=80)
    seat: str = Field(pattern=r"^(0[1-9]|1[0-4])$")
    region_or_element: str = Field(default="whole asset", max_length=200)
    evidence_class: EvidenceClass
    evidence_source: EvidenceSource = EvidenceSource.PIXELS
    observation: str = Field(min_length=1, max_length=2000)
    severity: Severity = Severity.NOTE
    rationale: str = Field(default="", max_length=2000)
    proposed_change: Optional[str] = Field(default=None, max_length=2000)
    acceptance_check: Optional[str] = Field(default=None, max_length=1000)
    uncertainty: str = Field(default="", max_length=500)
    score: Optional[int] = Field(default=None, ge=0, le=10)
    gate: Optional[Gate] = None
    gate_status: Optional[Literal["PASS", "FAIL"]] = None
    trait: Optional[str] = Field(default=None, max_length=80)        # emotional map: target trait
    cue: Optional[str] = Field(default=None, max_length=300)         # emotional map: visible cue


class ReviewFinding(_Strict):
    finding_id: str
    candidate_id: str
    criterion: str
    seat: str
    asset_hash: str
    region_or_element: str
    evidence_class: EvidenceClass
    evidence_source: EvidenceSource
    observation: str
    severity: Severity
    rationale: str
    proposed_change: Optional[str]
    acceptance_check: Optional[str]
    uncertainty: str
    actionable: bool
    assessor: Assessor
    measurement: Optional[dict[str, Any]] = None


class CriterionAssessment(_Strict):
    candidate_id: str
    criterion: str
    seat: str
    score: Optional[int] = None          # null = unassessed, never zero
    status: Literal["ASSESSED", "NOT_REVIEWED", "NOT_APPLICABLE"]
    reason: str = ""
    finding_ids: tuple[str, ...] = ()
    assessors: tuple[Assessor, ...] = ()


class GateResult(_Strict):
    candidate_id: str
    gate: Gate
    status: GateStatus
    evidence: str
    evidence_class: EvidenceClass
    finding_ids: tuple[str, ...] = ()


class RevisionWorkOrder(_Strict):
    work_order_id: str
    candidate_id: str
    asset_hash: str
    change: str
    why: str
    protected_invariants: tuple[str, ...]
    dependencies: dict[str, Any]
    verification: str
    finding_ids: tuple[str, ...]
    authority: Literal["PROPOSAL_ONLY"] = "PROPOSAL_ONLY"
    execution: str = ("a separate authorized generation/import or reconstruction must act on this; it rechecks identity, "
                      "permissions, budget and current versions. Changes outside approved rules go to genome review.")


class DirectionRecommendation(_Strict):
    verdict: Verdict
    candidate_id: Optional[str] = None
    label: Optional[str] = None
    reasons: tuple[str, ...]
    aggregate: Optional[dict[str, Any]] = None
    note: str = "a recommendation is not an approval; human selection uses the existing approval route"


class CandidateOutcome(_Strict):
    candidate_id: str
    label: str
    asset_hash: str
    verdict: Verdict
    reasons: tuple[str, ...]


class ReviewSession(_Strict):
    schema_version: str = SCHEMA
    rubric_version: str = RUBRIC_VERSION
    session_id: str
    intent_id: str
    tenant_id: str
    project_id: str
    brand_id: str
    genome_ref: str
    mode: ReviewMode
    blinded: bool
    labels: dict[str, str]                   # label -> candidate_id
    candidates: dict[str, str]               # candidate_id -> asset sha256
    lenses_active: tuple[str, ...]
    lenses_required_missing: tuple[str, ...]
    routes: dict[str, str]                   # route_id -> health at review time
    findings: tuple[ReviewFinding, ...]
    assessments: tuple[CriterionAssessment, ...]
    gates: tuple[GateResult, ...]
    outcomes: tuple[CandidateOutcome, ...]
    recommendation: DirectionRecommendation
    work_orders: tuple[RevisionWorkOrder, ...]
    emotional_map: dict[str, Any]
    brand_memory: dict[str, Any]
    regressions: tuple[dict[str, Any], ...] = ()
    measurements: dict[str, dict[str, Any]] = Field(default_factory=dict)
    base_session_id: Optional[str] = None
    correlation_note: str = ("seats sharing one assessor are correlated perspectives, not independent corroboration; "
                             "local measurements are not creative judgments")
    effects: dict[str, bool] = Field(default_factory=lambda: {"regenerated": False, "spent": False, "approved": False,
                                                               "mutated_master": False, "published": False})
    created_by: str
    created_at: str


# --------------------------------------------------------------------------- reconstruction / binding


class VectorReconstruction(_Strict):
    reconstruction_id: str
    intent_id: str
    candidate_id: str
    candidate_sha256: str
    selection_approval_id: str
    need: VectorNeed
    method: Literal["controlled_trace", "native_path_import"]
    artifact_id: Optional[str] = None
    artifact_version: Optional[int] = None
    sha256: Optional[str] = None
    classification: Literal["VECTOR", "RASTER_IN_SVG", "REJECTED"]
    checks: tuple[dict[str, Any], ...]
    fidelity: dict[str, Any]
    status: Literal["PASSED", "FAILED", "NOT_VERIFIED"]
    reasons: tuple[str, ...] = ()
    text_handling: str
    created_by: str
    created_at: str


class ApprovalBinding(_Strict):
    binding_id: str
    kind: Literal["SELECTION", "MASTER"]
    intent_id: str
    subject_artifact_id: str
    subject_version: int
    subject_sha256: str
    approval_id: Optional[str] = None
    genome_version_id: Optional[str] = None
    genome_keys: dict[str, str] = Field(default_factory=dict)
    status: str
    created_by: str
    created_at: str


def record_id(prefix: str, payload: Any) -> str:
    return f"{prefix}-{canonical_hash(payload)[:16]}"


__all__ = ["ApprovalBinding", "AssessorKind", "Assessor", "AssetRole", "CandidateObserved", "CandidateOutcome", "CandidateReported",
           "CreativeIntent", "CriterionAssessment", "DirectionBrief", "DirectionRecommendation", "EvidenceClass", "EvidenceSource",
           "FieldDecision", "FindingIn", "Gate", "GateResult", "GateStatus", "GenerationCandidate", "INTENT_COMPILER_VERSION",
           "LOGO_ROLES", "NONE", "ProvenanceClass", "RASTER_NATIVE", "RUBRIC_VERSION", "ReferenceIn", "ReviewFinding", "ReviewMode",
           "ReviewSession", "RevisionWorkOrder", "SCHEMA", "Severity", "SlotInstruction", "VECTOR_REQUIRED", "Verdict",
           "VectorNeed", "VectorReconstruction", "record_id", "vector_need"]
