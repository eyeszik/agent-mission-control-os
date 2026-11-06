"""Typed contracts for reusable prompt families (source spec §11, §26, §29).

A prompt family is the *repeatable* unit of creative production: invariants
that hold across a series, variation axes each instance draws from, a concept
ledger that prevents repetition, and a campaign anchor every derivative
inherits. Instances compile through the existing prompt compiler, so every
family output still terminates at ``PROMPT_PACKAGE_READY`` and inherits its
claim, evidence and exact-text gates.

Nothing in this package executes: it generates no media, creates no ads or
products, publishes nothing and spends nothing.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from services.langgraph.agency.artifacts.brand import BrandCore
from services.langgraph.agency.prompt_compiler import (
    ClaimSeed,
    ComputationEvidence,
    ProductionSpec,
    PromptCompilerResult,
    PromptFamily,
    ProviderCapability,
    ReferenceSpec,
    SourceEvidence,
)

FAMILY_ENGINE_VERSION = "amc-prompt-families/v1"
EXECUTION_STATEMENT = (
    "Compiles prompt packages only: generates no media, creates no ads, creates no products, "
    "publishes nothing, spends nothing."
)
_STRICT = {"extra": "forbid"}


class VariationAxis(str, Enum):
    """Declared in priority order: high-level concept variables first."""

    concept_metaphor = "concept_metaphor"
    subject = "subject"
    environment = "environment"
    composition = "composition"
    perspective = "perspective"
    scale = "scale"
    crop = "crop"
    graphic_device = "graphic_device"
    type_treatment = "type_treatment"
    lighting = "lighting"
    material = "material"
    narrative_beat = "narrative_beat"
    motion_pattern = "motion_pattern"


AXIS_PRIORITY: tuple[VariationAxis, ...] = tuple(VariationAxis)
# The concept-level variables whose repetition makes two outputs "the same
# idea" (source spec DUPLICATE_RULE): metaphor + composition + subject + device.
SIGNATURE_AXES: tuple[VariationAxis, ...] = (
    VariationAxis.concept_metaphor,
    VariationAxis.composition,
    VariationAxis.subject,
    VariationAxis.graphic_device,
)


class InvariantSet(BaseModel):
    """What every instance in the series holds fixed."""

    brand_voice: str | None = None
    visual_thesis: str | None = None
    palette_behavior: str | None = None
    type_behavior: str | None = None
    layout_grammar: str | None = None
    signature_devices: list[str] = Field(default_factory=list)
    image_treatment: str | None = None
    material_language: str | None = None
    motion_behavior: str | None = None
    claim_limits: list[str] = Field(default_factory=list)
    logo_rules: str | None = None
    accessibility: list[str] = Field(default_factory=list)

    model_config = _STRICT

    def lines(self) -> list[str]:
        out: list[str] = []
        for name in (
            "brand_voice",
            "visual_thesis",
            "palette_behavior",
            "type_behavior",
            "layout_grammar",
            "image_treatment",
            "material_language",
            "motion_behavior",
            "logo_rules",
        ):
            value = getattr(self, name)
            if value:
                out.append(f"{name}: {value}")
        out += [f"signature_device: {item}" for item in self.signature_devices]
        out += [f"claim_limit: {item}" for item in self.claim_limits]
        out += [f"accessibility: {item}" for item in self.accessibility]
        return out


class CampaignAnchor(BaseModel):
    """Campaign truth every derivative inherits before channel adaptation."""

    campaign_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    insight: str | None = None
    promise: str | None = None
    proof: list[str] = Field(default_factory=list)
    creative_territory: str | None = None
    visual_thesis: str | None = None
    verbal_thesis: str | None = None
    signature_device: str | None = None
    cta: str | None = None
    channels: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    legal: list[str] = Field(default_factory=list)
    measurement: str | None = None

    model_config = _STRICT


class ProductionMedium(str, Enum):
    digital = "DIGITAL"
    print = "PRINT"
    signage = "SIGNAGE"
    merch = "MERCH"


class ArtworkBackground(str, Enum):
    transparent = "TRANSPARENT"
    solid = "SOLID"
    unspecified = "UNSPECIFIED"


UNKNOWN = "UNKNOWN"
# Fields a physical medium needs from the printer/vendor; absent values stay
# UNKNOWN instead of being filled with a "typical" default.
_VENDOR_CONTROLLED = ("color_space", "resolution", "format", "bleed", "safe_area")


class ProductionTarget(BaseModel):
    """EDITABLE_MASTER and PRODUCTION_EXPORT are always distinct (source spec §19)."""

    medium: ProductionMedium = ProductionMedium.digital
    editable_master: str = "Layered editable master: live type, vector marks, linked assets, documented construction."
    export: ProductionSpec = Field(default_factory=ProductionSpec)
    vendor_profile: str | None = None
    print_method: str | None = None
    background: ArtworkBackground = ArtworkBackground.unspecified

    model_config = _STRICT

    def unknown_vendor_fields(self) -> list[str]:
        if self.medium is ProductionMedium.digital:
            return []
        missing = [name for name in _VENDOR_CONTROLLED if getattr(self.export, name) is None]
        if self.vendor_profile is None:
            missing.append("vendor_profile")
        if self.medium is ProductionMedium.merch and self.print_method is None:
            missing.append("print_method")
        return missing


class PromptFamilySpec(BaseModel):
    family_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: str = Field(min_length=1)
    niche: str | None = None
    business_objective: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    surface_family: PromptFamily
    asset_type: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    campaign: CampaignAnchor | None = None
    invariants: InvariantSet = Field(default_factory=InvariantSet)
    variation_axes: dict[VariationAxis, list[str]] = Field(min_length=1)
    emotional_function: str | None = None
    content_requirements: list[str] = Field(default_factory=list)
    exact_text: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    references: list[ReferenceSpec] = Field(default_factory=list)
    production: ProductionTarget = Field(default_factory=ProductionTarget)
    instance_count: int = Field(default=3, ge=1, le=24)
    # Advisory configuration from the source spec, not probabilities.
    series_consistency: float = Field(default=0.70, ge=0.0, le=1.0)
    novelty_budget: float = Field(default=0.30, ge=0.0, le=1.0)

    model_config = _STRICT

    @model_validator(mode="after")
    def _axes_are_usable(self) -> "PromptFamilySpec":
        for axis, options in self.variation_axes.items():
            if not options or any(not item.strip() for item in options):
                raise ValueError(f"variation axis {axis.value} needs non-empty options")
            if len(set(options)) != len(options):
                raise ValueError(f"variation axis {axis.value} has duplicate options")
        if not math.isclose(self.series_consistency + self.novelty_budget, 1.0, abs_tol=1e-9):
            raise ValueError("series_consistency and novelty_budget must sum to 1.0")
        return self


class ConceptSignature(BaseModel):
    primary_metaphor: str = ""
    composition: str = ""
    subject: str = ""
    graphic_device: str = ""
    signature_hash: str

    model_config = _STRICT

    def fields(self) -> tuple[str, str, str, str]:
        return (self.primary_metaphor, self.composition, self.subject, self.graphic_device)


class LedgerStatus(str, Enum):
    accepted = "ACCEPTED"
    rejected_duplicate = "REJECTED_DUPLICATE"


class ConceptLedgerEntry(BaseModel):
    family_id: str
    instance_id: str
    signature: ConceptSignature
    status: LedgerStatus
    variation: dict[str, str] = Field(default_factory=dict)

    model_config = _STRICT


class ConceptLedger(BaseModel):
    """Append-only record of concepts already used by a family or campaign."""

    entries: list[ConceptLedgerEntry] = Field(default_factory=list)
    rejected_patterns: list[str] = Field(default_factory=list)

    model_config = _STRICT

    def accepted(self) -> list[ConceptLedgerEntry]:
        return [entry for entry in self.entries if entry.status is LedgerStatus.accepted]


class PromptFamilyInstance(BaseModel):
    family_id: str
    instance_id: str
    concept_thesis: str
    variation: dict[str, str]
    signature: ConceptSignature
    status: LedgerStatus
    repairs: list[str] = Field(default_factory=list)

    model_config = _STRICT


# ---------------------------------------------------------------------------
# Attention / hook testing (evidence-gated lifecycle, source directive phase 16)
# ---------------------------------------------------------------------------


class HookStatus(str, Enum):
    candidate = "CANDIDATE"
    approved_for_test = "APPROVED_FOR_TEST"
    measured = "MEASURED"
    winner_by_metric = "WINNER_BY_METRIC"
    saturated = "SATURATED"
    retired = "RETIRED"


class PerformanceObservation(BaseModel):
    metric: str = Field(min_length=1)
    value: float
    window_start: str = Field(min_length=1)
    window_end: str = Field(min_length=1)
    sample_size: int | None = Field(default=None, ge=0)
    source: str = Field(min_length=1)

    model_config = _STRICT


class HookCandidate(BaseModel):
    """A hook's creative score is never observed performance."""

    hook_id: str = Field(min_length=1)
    territory: str = Field(min_length=1)
    text: str = Field(min_length=1)
    status: HookStatus = HookStatus.candidate
    creative_score: float | None = Field(default=None, ge=0.0, le=1.0)
    approval_ref: str | None = None
    winner_metric: str | None = None
    observations: list[PerformanceObservation] = Field(default_factory=list)

    model_config = _STRICT

    @model_validator(mode="after")
    def _status_requires_evidence(self) -> "HookCandidate":
        tested = {HookStatus.approved_for_test, HookStatus.measured, HookStatus.winner_by_metric}
        if self.status in tested and not self.approval_ref:
            raise ValueError(f"{self.status.value} requires a human approval_ref for testing")
        if self.status in {HookStatus.measured, HookStatus.winner_by_metric} and not self.observations:
            raise ValueError(f"{self.status.value} requires at least one performance observation")
        if self.status is HookStatus.winner_by_metric:
            if not self.winner_metric:
                raise ValueError("WINNER_BY_METRIC requires the comparison metric")
            if self.winner_metric not in {item.metric for item in self.observations}:
                raise ValueError("WINNER_BY_METRIC requires an observation of the declared metric")
        return self


# ---------------------------------------------------------------------------
# Paid-media creative (specification only; source directive phase 11)
# ---------------------------------------------------------------------------

# Preconditions any future provider mutation path must satisfy. None of them is
# performed here; the list exists so a reviewer can see what is still missing.
PAID_MEDIA_MUTATION_PRECONDITIONS: tuple[str, ...] = (
    "resolve account",
    "resolve campaign",
    "resolve ad group",
    "resolve creative type",
    "resolve selected artwork",
    "generate and validate platform preview",
    "show the exact proposed mutation",
    "obtain explicit human confirmation",
    "write with an idempotency key",
    "read back the written object",
    "reconcile ambiguous results",
    "preserve successful intermediate ids",
    "retry only safe idempotent operations",
)


class PaidMediaCreativeSpec(BaseModel):
    """Advisory creative package for a paid placement. It cannot create an ad."""

    objective: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    campaign_context: str | None = None
    hook: str | None = None
    title: str | None = None
    body: str | None = None
    cta: str | None = None
    landing_page_alignment: str | None = None
    image_prompt_ref: str | None = None
    exact_artwork_ref: str | None = None
    claims: list[str] = Field(default_factory=list)
    disclosures: list[str] = Field(default_factory=list)
    measurement_intent: str | None = None
    execution: Literal["SPEC_ONLY"] = "SPEC_ONLY"
    platform_mutation: Literal[False] = False

    model_config = _STRICT


class PromptFamilyRequest(BaseModel):
    project_name: str = Field(min_length=1)
    family: PromptFamilySpec
    brand_core: BrandCore
    ledger: ConceptLedger = Field(default_factory=ConceptLedger)
    content: str = ""
    claims: list[ClaimSeed] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    computations: list[ComputationEvidence] = Field(default_factory=list)
    providers: list[ProviderCapability] = Field(default_factory=list)
    hooks: list[HookCandidate] = Field(default_factory=list)
    paid_media: list[PaidMediaCreativeSpec] = Field(default_factory=list)

    model_config = _STRICT


class PromptFamilyEvaluation(BaseModel):
    invariants_held: bool
    exact_text_preserved: bool
    accepted_instances: int
    rejected_duplicates: int
    repairs: int
    # Advisory: share of declared axes that change between consecutive accepted
    # instances, reported next to the configured novelty budget. Not a gate.
    varied_axis_fraction: float
    novelty_budget: float
    series_consistency: float
    hard_failures: list[str] = Field(default_factory=list)
    advisory_notes: list[str] = Field(default_factory=list)

    model_config = _STRICT


class PromptFamilyResult(BaseModel):
    engine_version: str = FAMILY_ENGINE_VERSION
    family_id: str
    family_version: str
    family_hash: str
    instances: list[PromptFamilyInstance]
    ledger: ConceptLedger
    compiler_result: PromptCompilerResult
    evaluation: PromptFamilyEvaluation
    responsible_functional_roles: list[str]
    hooks: list[HookCandidate] = Field(default_factory=list)
    paid_media: list[PaidMediaCreativeSpec] = Field(default_factory=list)
    terminal_state: Literal["PROMPT_PACKAGE_READY", "BLOCKED"]
    blocked_reasons: list[str] = Field(default_factory=list)
    execution_statement: str = EXECUTION_STATEMENT

    model_config = _STRICT
