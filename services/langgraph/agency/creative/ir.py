"""Canonical creative contracts: MissionIR, ArtifactIR, evidence and findings.

Every model is strict (``extra="forbid"``) and frozen, and every hash uses the
repository's AMC-CANON-1 ``canonical_hash``. MissionIR and ArtifactIR are
provider-neutral: adapters translate them to a provider and back, and a
provider can never redefine their semantics.

Constraint firewall: everything in a ``Constraint`` with ``zone="HARD"`` is
non-compensable; soft objectives only rank candidates that already passed
every hard gate.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

SCHEMA_VERSION = "amc-creative-ir/v1"
_HASH = r"^[a-f0-9]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- constraints


class ConstraintKind(str, Enum):
    REQUIRED_SECTION = "required_section"
    FORBIDDEN_SECTION = "forbidden_section"
    REQUIRED_TEXT = "required_text"
    FORBIDDEN_PHRASE = "forbidden_phrase"
    VERIFIED_CLAIMS_ONLY = "verified_claims_only"
    BRAND_NAME = "brand_name"
    BRAND_PALETTE = "brand_palette"
    WCAG_CONTRAST = "wcag_contrast"
    SEMANTIC_LANDMARKS = "semantic_landmarks"
    IMAGE_ALT = "image_alt"
    MAX_HEADLINE_WORDS = "max_headline_words"
    NO_EXTERNAL_SCRIPTS = "no_external_scripts"
    MAX_HTML_BYTES = "max_html_bytes"
    CTA_TRUTHFUL = "cta_truthful"
    RIGHTS_ABSTRACT_REFERENCES = "rights_abstract_references"
    SECURITY_NO_SECRETS = "security_no_secrets"
    HUMAN_APPROVAL_BEFORE_DELIVERY = "human_approval_before_delivery"


class Constraint(_Strict):
    constraint_id: str = Field(min_length=1, max_length=120)
    zone: Literal["HARD", "SOFT"] = "HARD"
    kind: ConstraintKind
    params: dict[str, Any] = Field(default_factory=dict)
    source: Literal["user", "brand", "accessibility", "implementation", "rights", "security", "approval", "system"]
    description: str = Field(default="", max_length=500)


class Objective(_Strict):
    """A soft, rankable objective. Weights are configured tie-break heuristics,
    never creative truth, and never applied before the hard gate."""

    name: Literal[
        "brand_fidelity", "distinctiveness", "clarity", "accessibility_quality",
        "visual_coherence", "implementation_feasibility", "conversion_clarity", "content_quality",
    ]
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


class Asset(_Strict):
    asset_id: str
    kind: Literal["logo", "image", "copy", "metric", "testimonial", "palette", "font", "other"]
    ref: str = Field(max_length=500)
    verified: bool = False
    rights: Literal["owned", "licensed", "unknown"] = "unknown"


class ExplorationPolicy(_Strict):
    mode: Literal["auto", "single", "explore"] = "auto"
    candidates_requested: Optional[int] = Field(default=None, ge=1, le=4)


class ResourceBudget(_Strict):
    max_candidates: int = Field(default=4, ge=1, le=4)
    max_generations: int = Field(default=2, ge=1, le=2)
    max_model_calls: int = Field(default=0, ge=0, le=64)
    context_token_budget: int = Field(default=2400, ge=0, le=32000)
    max_wall_clock_seconds: float = Field(default=30.0, gt=0, le=600)
    max_corrections: int = Field(default=1, ge=0, le=1)
    max_regenerations_per_candidate: int = Field(default=1, ge=0, le=1)


class ApprovalPolicy(_Strict):
    require_human_selection: bool = True
    # Delivery always needs a human approval; the field exists so the policy is
    # explicit in the hashed IR, and it cannot be switched off.
    require_delivery_approval: Literal[True] = True
    authority_ref: str = "human-review"


class Provenance(_Strict):
    source: Literal["brief"] = "brief"
    brief_hash: str = Field(pattern=_HASH)
    compiler_version: str


ArtifactFamily = Literal["brand", "visual", "interface", "content", "motion", "system"]
ArtifactType = Literal[
    "brand_identity", "logo", "landing_page", "marketing_site", "dashboard", "mobile_ui",
    "social_post", "image", "illustration", "motion", "video", "design_system", "design_handoff",
]


class MissionIR(_Strict):
    schema_version: Literal["amc-creative-ir/v1"] = SCHEMA_VERSION
    mission_id: str
    run_id: str
    business_goal: str = Field(min_length=1, max_length=500)
    user_goal: str = Field(min_length=1, max_length=500)
    audience: str = Field(min_length=1, max_length=300)
    artifact_family: ArtifactFamily
    artifact_type: ArtifactType
    channel: str = Field(min_length=1, max_length=80)
    desired_action: str = Field(min_length=1, max_length=200)
    brand_name: str = Field(min_length=1, max_length=120)
    hard_constraints: tuple[Constraint, ...] = ()
    soft_objectives: tuple[Objective, ...] = ()
    brand_constraints: tuple[Constraint, ...] = ()
    accessibility_constraints: tuple[Constraint, ...] = ()
    implementation_constraints: tuple[Constraint, ...] = ()
    rights_constraints: tuple[Constraint, ...] = ()
    security_constraints: tuple[Constraint, ...] = ()
    available_assets: tuple[Asset, ...] = ()
    approved_sources: tuple[str, ...] = ()
    exploration_policy: ExplorationPolicy = ExplorationPolicy()
    resource_budget: ResourceBudget = ResourceBudget()
    approval_policy: ApprovalPolicy = ApprovalPolicy()
    assumptions: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    provenance: Provenance
    mission_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def _zones(self) -> "MissionIR":
        for group in (self.hard_constraints, self.brand_constraints, self.accessibility_constraints,
                      self.implementation_constraints, self.rights_constraints, self.security_constraints):
            if any(c.zone != "HARD" for c in group):
                raise ValueError("ZONE_A constraint groups may only hold HARD constraints")
        ids = [c.constraint_id for c in self.all_constraints()]
        if len(ids) != len(set(ids)):
            raise ValueError("constraint ids must be unique")
        if self.mission_hash != mission_hash_of(self):
            raise ValueError("mission_hash does not match the mission content")
        return self

    def all_constraints(self) -> tuple[Constraint, ...]:
        return (*self.hard_constraints, *self.brand_constraints, *self.accessibility_constraints,
                *self.implementation_constraints, *self.rights_constraints, *self.security_constraints)


def mission_hash_of(mission: BaseModel | dict) -> str:
    body = mission.model_dump(mode="json") if isinstance(mission, BaseModel) else dict(mission)
    for volatile in ("mission_hash", "mission_id", "run_id"):
        body.pop(volatile, None)
    return canonical_hash(body)


# --------------------------------------------------------------------------- artifact IR


class SectionKind(str, Enum):
    HERO = "hero"
    PROOF = "proof"
    PROBLEM = "problem"
    SOLUTION = "solution"
    FEATURES = "features"
    HOW_IT_WORKS = "how_it_works"
    SECURITY = "security"
    TESTIMONIALS = "testimonials"
    FAQ = "faq"
    CTA = "cta"
    FOOTER = "footer"


class CallToAction(_Strict):
    label: str = Field(min_length=1, max_length=60)
    action: str = Field(min_length=1, max_length=200)
    destination: Optional[str] = None
    integration_status: Literal["verified", "unverified", "unavailable"] = "unavailable"


class Section(_Strict):
    section_id: str
    kind: SectionKind
    heading: str = Field(max_length=200)
    body: str = Field(default="", max_length=2000)
    items: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


class ConceptSpec(_Strict):
    """The soft creative structure a candidate commits to. Mutations change
    these axes; they never touch the mission's hard constraints."""

    narrative: Literal["outcome_first", "problem_first", "proof_first", "story_first"]
    hierarchy: Literal["single_focus", "layered", "modular"]
    composition: Literal["split_hero", "centered", "editorial", "full_bleed"]
    interaction: Literal["single_cta", "guided_demo", "progressive"]
    metaphor: Literal["shield", "lens", "control_room", "pathway", "none"]


class LandingPageIR(_Strict):
    concept: ConceptSpec
    headline: str = Field(min_length=1, max_length=160)
    subheadline: str = Field(default="", max_length=400)
    sections: tuple[Section, ...]
    cta: CallToAction
    palette: dict[str, str]
    heading_font: str
    body_font: str
    locale: str = "en"


class LogoIR(_Strict):
    brand_name: str
    palette: dict[str, str]
    mark: Literal["geometric_initials"] = "geometric_initials"


class DesignSystemIR(_Strict):
    palette: dict[str, str]
    heading_font: str
    body_font: str


class ArtifactIR(_Strict):
    schema_version: Literal["amc-creative-ir/v1"] = SCHEMA_VERSION
    artifact_id: str
    mission_id: str
    artifact_type: ArtifactType
    semantic_intent: str = Field(max_length=500)
    hierarchy: tuple[str, ...]
    content_structure: dict[str, Any] = Field(default_factory=dict)
    brand_bindings: dict[str, Any] = Field(default_factory=dict)
    accessibility_requirements: tuple[str, ...] = ()
    implementation_requirements: tuple[str, ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    landing_page: Optional[LandingPageIR] = None
    logo: Optional[LogoIR] = None
    design_system: Optional[DesignSystemIR] = None
    hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def _one_extension(self, info: ValidationInfo) -> "ArtifactIR":
        extensions = [x for x in (self.landing_page, self.logo, self.design_system) if x is not None]
        if len(extensions) > 1:
            raise ValueError("an ArtifactIR carries at most one typed extension")
        if (info.context or {}).get("_sealing"):
            return self
        if self.hash != artifact_hash_of(self):
            raise ValueError("artifact hash does not match its content")
        return self


def artifact_hash_of(artifact: BaseModel | dict) -> str:
    body = artifact.model_dump(mode="json") if isinstance(artifact, BaseModel) else dict(artifact)
    body.pop("hash", None)
    return canonical_hash(body)


def seal_artifact(**fields: Any) -> ArtifactIR:
    body = dict(fields)
    body["hash"] = "0" * 64
    draft = ArtifactIR.model_validate(body, context={"_sealing": True})
    body["hash"] = artifact_hash_of(draft)
    return ArtifactIR.model_validate(body)


# --------------------------------------------------------------------------- evidence and findings


class EvidenceEnvelope(_Strict):
    mission_hash: str = Field(pattern=_HASH)
    plan_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    corpus_version: Optional[str]
    capability_versions: tuple[str, ...]
    source_refs: tuple[str, ...]
    provider_config_ref: str
    seed: Optional[int] = None
    parent_candidate_id: Optional[str] = None
    mutation_spec: Optional[dict[str, Any]] = None
    evaluator_versions: tuple[str, ...]
    validation_refs: tuple[str, ...]
    approval_state: Literal["not_requested", "pending", "approved", "rejected", "stale"]
    artifact_hash: str = Field(pattern=_HASH)


MANDATORY_PROVENANCE = ("mission_hash", "plan_hash", "context_hash", "provider_config_ref", "artifact_hash")


class Finding(_Strict):
    code: str
    severity: Literal["critical", "major", "minor", "info"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ref: str
    repair_scope: Optional[str] = None


__all__ = [
    "ApprovalPolicy",
    "ArtifactIR",
    "Asset",
    "CallToAction",
    "ConceptSpec",
    "Constraint",
    "ConstraintKind",
    "DesignSystemIR",
    "EvidenceEnvelope",
    "ExplorationPolicy",
    "Finding",
    "LandingPageIR",
    "LogoIR",
    "MANDATORY_PROVENANCE",
    "MissionIR",
    "Objective",
    "Provenance",
    "ResourceBudget",
    "SCHEMA_VERSION",
    "Section",
    "SectionKind",
    "artifact_hash_of",
    "mission_hash_of",
    "seal_artifact",
]
