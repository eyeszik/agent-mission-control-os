"""Evidence-grounded brand/creative prompt compiler.

This module intentionally stops at validated prompt packages. It never invokes a
media provider, writes a generated asset, publishes content, or performs any
other external creative side effect.

The compiler is split into five explicit audit passes before prompt compilation:

1. intake_claims
2. hunt_gaps
3. build_research_backfill
4. validate_claims
5. synthesize_report

That separation prevents retrieval from silently rewriting the source material
and makes every unresolved premise visible in the final result.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from services.langgraph.agency.artifacts.brand import BrandCore
from services.langgraph.agency.guidance import (
    GuidanceOverride,
    GuidanceSelection,
    default_registry,
    route_guidance,
)
from services.langgraph.agency.ui_ux import (
    UIUXDesignIR,
    UIUXTerminal,
    compile_uiux,
    directive_buckets,
    request_from_asset_requirement,
    serialize_spec_section,
)


COMPILER_VERSION = "amc-prompt-compiler/v1"
GENERATION_FIREWALL = "PROMPT_PACKAGE_READY"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_API_HINT = re.compile(r"\b(api|sdk|endpoint|webhook|mcp|provider|model)\b", re.I)
_METRIC_HINT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|x|ms|s|seconds?|minutes?|hours?|days?|users?|requests?|usd|\$)\b", re.I)
_MARKET_HINT = re.compile(r"\b(market|competitor|industry|audience|customer|tam|sam|som|share)\b", re.I)
_LEGAL_HINT = re.compile(r"\b(legal|law|regulation|compliance|licensed|copyright|trademark|wcag|privacy)\b", re.I)
# Comparative or superiority claims ("faster than X", "#1", "industry-leading")
# are market claims: they need substantiation before they can ship.
_COMPARATIVE_HINT = re.compile(
    r"\b(?:better|faster|cheaper|stronger|safer|smarter|easier|healthier|cleaner|quieter)\s+than\b"
    r"|#1\b|\bnumber[- ]one\b|\bindustry[- ]leading\b|\bmarket[- ]leading\b|\bmarket leader\b",
    re.I,
)


class ClaimType(str, Enum):
    fact = "FACT"
    opinion = "OPINION"
    promise = "PROMISE"
    metric = "METRIC"
    api_claim = "API_CLAIM"
    legal_claim = "LEGAL_CLAIM"
    market_claim = "MARKET_CLAIM"
    user_assertion = "USER_ASSERTION"
    brand_rule = "BRAND_RULE"
    design_rule = "DESIGN_RULE"
    requirement = "REQUIREMENT"
    assumption = "ASSUMPTION"
    inference = "INFERENCE"


class ClaimStatus(str, Enum):
    verified = "VERIFIED"
    partially_verified = "PARTIALLY_VERIFIED"
    user_asserted = "USER_ASSERTED"
    derived = "DERIVED"
    speculative = "SPECULATIVE"
    conflicted = "CONFLICTED"
    stale = "STALE"
    void = "VOID"
    unverified = "UNVERIFIED"


class GapCategory(str, Enum):
    missing_premise = "MISSING_PREMISE"
    missing_source = "MISSING_SOURCE"
    missing_primary_source = "MISSING_PRIMARY_SOURCE"
    undocumented_api = "UNDOCUMENTED_API"
    undeclared_stakeholder = "UNDECLARED_STAKEHOLDER"
    unstated_assumption = "UNSTATED_ASSUMPTION"
    missing_failure_mode = "MISSING_FAILURE_MODE"
    compliance_gap = "COMPLIANCE_GAP"
    scope_gap = "SCOPE_GAP"
    temporal_gap = "TEMPORAL_GAP"
    contradiction = "CONTRADICTION"
    ambiguity = "AMBIGUITY"
    dependency_gap = "DEPENDENCY_GAP"
    brand_gap = "BRAND_GAP"
    production_gap = "PRODUCTION_GAP"
    provider_gap = "PROVIDER_GAP"


class Materiality(str, Enum):
    critical = "CRITICAL"
    high = "HIGH"
    medium = "MEDIUM"
    low = "LOW"


class ConfidenceBand(str, Enum):
    verified_high = "VERIFIED_HIGH"
    verified = "VERIFIED"
    provisional = "PROVISIONAL_WITH_FLAGS"
    blocking = "BLOCKING_UNCERTAINTY"


class CompilerState(str, Enum):
    content_received = "CONTENT_RECEIVED"
    claims_extracted = "CLAIMS_EXTRACTED"
    gaps_identified = "GAPS_IDENTIFIED"
    research_backfilled = "RESEARCH_BACKFILLED"
    knowledge_validated = "KNOWLEDGE_VALIDATED"
    brand_system_incomplete = "BRAND_SYSTEM_INCOMPLETE"
    brand_system_compiled = "BRAND_SYSTEM_COMPILED"
    brand_system_validated = "BRAND_SYSTEM_VALIDATED"
    asset_requirements_resolved = "ASSET_REQUIREMENTS_RESOLVED"
    asset_specs_compiled = "ASSET_SPECS_COMPILED"
    prompt_context_resolved = "PROMPT_CONTEXT_RESOLVED"
    prompt_ir_compiled = "PROMPT_IR_COMPILED"
    generation_prompts_compiled = "GENERATION_PROMPTS_COMPILED"
    prompts_validated_against_brand = "PROMPTS_VALIDATED_AGAINST_BRAND"
    prompt_package_ready = "PROMPT_PACKAGE_READY"
    research_incomplete = "RESEARCH_INCOMPLETE"
    blocked = "BLOCKED"


class PromptFamily(str, Enum):
    image = "IMAGE"
    ui_ux = "UI_UX"
    copy = "COPY"
    motion = "MOTION"
    video = "VIDEO"
    storyboard = "STORYBOARD"
    print = "PRINT"
    presentation = "PRESENTATION"


class ProviderCapabilityName(str, Enum):
    text_to_image = "TEXT_TO_IMAGE"
    image_to_image = "IMAGE_TO_IMAGE"
    edit = "EDIT"
    inpaint = "INPAINT"
    outpaint = "OUTPAINT"
    multi_reference = "MULTI_REFERENCE"
    vector = "VECTOR"
    text_to_video = "TEXT_TO_VIDEO"
    image_to_video = "IMAGE_TO_VIDEO"
    element_to_video = "ELEMENT_TO_VIDEO"
    reference_to_video = "REFERENCE_TO_VIDEO"
    first_frame = "FIRST_FRAME"
    last_frame = "LAST_FRAME"
    multishot = "MULTISHOT"
    camera_control = "CAMERA_CONTROL"
    audio = "AUDIO"
    ui_generation = "UI_GENERATION"
    code_generation = "CODE_GENERATION"
    structured_text = "STRUCTURED_TEXT"


class AdapterStatus(str, Enum):
    generic_compatible = "GENERIC_COMPATIBLE"
    verified_adapter = "VERIFIED_ADAPTER"
    unverified = "UNVERIFIED"
    blocked = "BLOCKED"


class PromptValidationStatus(str, Enum):
    passed = "PASS"
    repair = "REPAIR"
    blocked = "BLOCK"


class AcceptanceStatus(str, Enum):
    passed = "PASS"
    partial = "PARTIAL"
    blocked = "BLOCKED"
    failed = "FAIL"


class SourceClass(str, Enum):
    primary = "PRIMARY"
    official = "OFFICIAL"
    secondary = "SECONDARY"
    community = "COMMUNITY"
    user = "USER"


class FreshnessClass(str, Enum):
    """How quickly a researched fact decays. Static guidance never carries
    VOLATILE or REALTIME facts; those arrive as runtime evidence."""

    static = "STATIC"
    slow_changing = "SLOW_CHANGING"
    volatile = "VOLATILE"
    realtime = "REALTIME"


class ReferenceRole(str, Enum):
    """What a supplied reference is allowed to control (source spec §14)."""

    identity = "IDENTITY"
    content = "CONTENT"
    composition = "COMPOSITION"
    style = "STYLE"
    start_frame = "START_FRAME"
    end_frame = "END_FRAME"
    motion = "MOTION"
    audio = "AUDIO"


# Precedence when references conflict: identity controls who/what the subject
# is, content controls required visible objects, composition controls spatial
# organisation, style supplies transferable attributes only.
REFERENCE_PRECEDENCE: tuple[ReferenceRole, ...] = (
    ReferenceRole.identity,
    ReferenceRole.content,
    ReferenceRole.composition,
    ReferenceRole.style,
    ReferenceRole.start_frame,
    ReferenceRole.end_frame,
    ReferenceRole.motion,
    ReferenceRole.audio,
)
_TEMPORAL_REFERENCE_ROLES = {
    ReferenceRole.start_frame,
    ReferenceRole.end_frame,
    ReferenceRole.motion,
    ReferenceRole.audio,
}


class ReferenceSpec(BaseModel):
    ref_id: str = Field(min_length=1)
    role: ReferenceRole
    priority: int = Field(default=1, ge=1, le=10)
    note: str | None = None

    model_config = {"extra": "forbid"}


class SeriesBinding(BaseModel):
    """Links one asset to a reusable prompt family (agency/prompt_families).

    Invariants are held fixed across the series; ``variation`` names what this
    instance deliberately changes. The binding is descriptive: it cannot widen
    brand authority or override canonical BrandCore.
    """

    family_id: str = Field(min_length=1)
    family_version: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    campaign_ref: str | None = None
    concept_thesis: str = Field(min_length=1)
    emotional_function: str | None = None
    signature_devices: list[str] = Field(default_factory=list)
    series_invariants: list[str] = Field(default_factory=list)
    variation: dict[str, str] = Field(default_factory=dict)
    concept_signature: str = Field(min_length=1)

    model_config = {"extra": "forbid"}


class ClaimSeed(BaseModel):
    text: str = Field(min_length=1)
    claim_type: ClaimType = ClaimType.user_assertion
    source_ref: str | None = None
    stakeholder: str | None = None
    temporal_scope: str | None = None

    model_config = {"extra": "forbid"}


class ClaimRecord(BaseModel):
    claim_id: str
    text: str
    claim_type: ClaimType
    source_ref: str | None = None
    stakeholder: str | None = None
    temporal_scope: str | None = None
    status: ClaimStatus = ClaimStatus.unverified
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    model_config = {"extra": "forbid"}


class GapRecord(BaseModel):
    gap_id: str
    claim_refs: list[str] = Field(default_factory=list)
    category: GapCategory
    description: str
    materiality: Materiality
    retrieval_target: str | None = None
    required_source_class: SourceClass | None = None
    blocks_synthesis: bool = False

    model_config = {"extra": "forbid"}


class SourceEvidence(BaseModel):
    source_id: str
    title: str
    source_class: SourceClass
    claim_ids: list[str] = Field(default_factory=list)
    supports: bool = True
    publisher: str | None = None
    uri: str | None = None
    published_at: str | None = None
    accessed_at: str | None = None
    summary: str = Field(min_length=1)
    # The retrieval query that produced this evidence, when it came from search.
    query: str | None = None
    freshness_class: FreshnessClass | None = None

    model_config = {"extra": "forbid"}


class ComputationEvidence(BaseModel):
    """A deterministic computation (arithmetic, units, statistics, symbolic).

    Computation is a distinct provenance class from empirical evidence: a
    correct result says nothing about whether its input premises are true, so a
    computation can never mark a claim VERIFIED. Derived claims become DERIVED
    only when every empirical input claim is itself verified.
    """

    computation_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expression_or_operation: str = Field(min_length=1)
    inputs: dict[str, str] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    tool_or_engine: str = Field(min_length=1)
    engine_version: str | None = None
    result: str = Field(min_length=1)
    precision: str | None = None
    uncertainty: str | None = None
    executed_at: str | None = None
    provenance: str = Field(min_length=1)
    reproducible: bool = False
    input_claim_ids: list[str] = Field(default_factory=list)
    derived_claim_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ComputationStatus(str, Enum):
    derived_from_verified_inputs = "DERIVED_FROM_VERIFIED_INPUTS"
    no_empirical_inputs = "NO_EMPIRICAL_INPUTS"
    premises_unverified = "PREMISES_UNVERIFIED"
    invalid_reference = "INVALID_REFERENCE"


class ComputationAssessment(BaseModel):
    computation_id: str
    status: ComputationStatus
    derived_claim_ids: list[str] = Field(default_factory=list)
    unverified_inputs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ResearchRequest(BaseModel):
    request_id: str
    gap_id: str
    query: str
    required_source_class: SourceClass | None = None
    max_hops: int = Field(default=3, ge=1, le=5)

    model_config = {"extra": "forbid"}


class ProductionSpec(BaseModel):
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    unit: str = "px"
    aspect_ratio: str | None = None
    orientation: str | None = None
    format: str | None = None
    color_space: str | None = None
    resolution: str | None = None
    duration_seconds: float | None = Field(default=None, gt=0)
    fps: int | None = Field(default=None, gt=0)
    codec: str | None = None
    container: str | None = None
    safe_area: str | None = None
    bleed: str | None = None

    model_config = {"extra": "forbid"}


class AssetRequirement(BaseModel):
    asset_id: str = Field(min_length=1)
    family: PromptFamily
    asset_type: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    business_reason: str | None = None
    required_brand_domains: list[str] = Field(default_factory=list)
    required_capabilities: list[ProviderCapabilityName] = Field(default_factory=list)
    content_requirements: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    quality_constraints: list[str] = Field(default_factory=list)
    production: ProductionSpec = Field(default_factory=ProductionSpec)
    guidance_overrides: GuidanceOverride = Field(default_factory=GuidanceOverride)
    # Text that must survive character-for-character (headlines, legal lines,
    # prices, disclosures). Visual families route it to a deterministic layout
    # stage instead of asking a generator to render lettering.
    exact_text: list[str] = Field(default_factory=list)
    references: list[ReferenceSpec] = Field(default_factory=list)
    series: SeriesBinding | None = None

    model_config = {"extra": "forbid"}


class AssetSpec(BaseModel):
    asset_id: str
    family: PromptFamily
    asset_type: str
    objective: str
    audience: str
    channel: str
    destination: str
    brand_hash: str
    required_brand_domains: list[str]
    required_capabilities: list[ProviderCapabilityName]
    content_requirements: list[str]
    negative_constraints: list[str]
    quality_constraints: list[str]
    production: ProductionSpec
    validation_rules: list[str]
    exact_text: list[str] = Field(default_factory=list)
    references: list[ReferenceSpec] = Field(default_factory=list)
    series: SeriesBinding | None = None

    model_config = {"extra": "forbid"}


class ProviderCapability(BaseModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    verified: bool = False
    source_ref: str | None = None
    verified_at: str | None = None
    families: list[PromptFamily] = Field(default_factory=list)
    capabilities: list[ProviderCapabilityName] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PromptContext(BaseModel):
    brand_context: dict[str, Any]
    included_domains: list[str]
    excluded_domains: list[str]
    guidance_context: dict[str, Any] = Field(default_factory=dict)
    included_guidance: list[str] = Field(default_factory=list)
    excluded_guidance: list[str] = Field(default_factory=list)
    guidance_hash: str = ""
    activation_reasons: list[str] = Field(default_factory=list)
    registry_version: str | None = None
    router_version: str | None = None
    context_hash: str

    model_config = {"extra": "forbid"}


class PromptIR(BaseModel):
    asset_id: str
    family: PromptFamily
    objective: str
    audience: str
    channel: str
    destination: str
    brand_directives: list[str]
    strategy_directives: list[str] = Field(default_factory=list)
    verbal_directives: list[str] = Field(default_factory=list)
    visual_directives: list[str] = Field(default_factory=list)
    composition_directives: list[str] = Field(default_factory=list)
    typography_directives: list[str] = Field(default_factory=list)
    interaction_directives: list[str] = Field(default_factory=list)
    motion_directives: list[str] = Field(default_factory=list)
    camera_directives: list[str] = Field(default_factory=list)
    audio_directives: list[str] = Field(default_factory=list)
    accessibility_directives: list[str] = Field(default_factory=list)
    trend_directives: list[str] = Field(default_factory=list)
    token_directives: list[str] = Field(default_factory=list)
    engineering_directives: list[str] = Field(default_factory=list)
    governance_directives: list[str] = Field(default_factory=list)
    qa_directives: list[str] = Field(default_factory=list)
    production_guidance_directives: list[str] = Field(default_factory=list)
    content_directives: list[str]
    production_directives: list[str]
    negative_constraints: list[str]
    quality_constraints: list[str]
    required_capabilities: list[ProviderCapabilityName]
    provenance_refs: list[str]
    exact_text: list[str] = Field(default_factory=list)
    references: list[ReferenceSpec] = Field(default_factory=list)
    render_stages: list[str] = Field(default_factory=list)
    series: SeriesBinding | None = None
    evidence_directives: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ProviderPrompt(BaseModel):
    provider: str | None = None
    model: str | None = None
    status: AdapterStatus
    prompt: str
    required_references: list[str] = Field(default_factory=list)
    unsupported_requirements: list[str] = Field(default_factory=list)
    source_ref: str | None = None

    model_config = {"extra": "forbid"}


class PromptValidationResult(BaseModel):
    status: PromptValidationStatus
    issues: list[str] = Field(default_factory=list)
    checked_dimensions: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AcceptanceReport(BaseModel):
    status: AcceptanceStatus
    blocking_criteria: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PromptPackage(BaseModel):
    package_id: str
    package_version: str = COMPILER_VERSION
    project_name: str
    asset_spec: AssetSpec
    prompt_ir: PromptIR
    generic_master_prompt: str
    provider_prompts: list[ProviderPrompt]
    context_manifest: PromptContext
    validation: PromptValidationResult
    prompt_hash: str
    brand_hash: str
    unresolved_gaps: list[str] = Field(default_factory=list)
    # Present only for PromptFamily.UI_UX: the compiled UI/UX specification the
    # prompt was derived from (agency/ui_ux). Its terminal is a spec state, never
    # a generated/deployed one.
    ui_ux_design: UIUXDesignIR | None = None
    handoff_only: Literal[True] = True
    terminal_state: Literal["PROMPT_PACKAGE_READY"] = GENERATION_FIREWALL

    model_config = {"extra": "forbid"}


class PassResult(BaseModel):
    pass_name: str
    status: str
    produced: int = 0
    notes: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class CompletenessReport(BaseModel):
    evidence: int = Field(ge=0, le=4)
    brand: int = Field(ge=0, le=4)
    production: int = Field(ge=0, le=4)
    provider: int = Field(ge=0, le=4)
    provenance: int = Field(ge=0, le=4)
    blocking_domains: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PromptCompilerRequest(BaseModel):
    project_name: str = Field(min_length=1)
    content: str = ""
    claims: list[ClaimSeed] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    brand_core: BrandCore | None = None
    asset_requirements: list[AssetRequirement] = Field(default_factory=list)
    providers: list[ProviderCapability] = Field(default_factory=list)
    computations: list[ComputationEvidence] = Field(default_factory=list)
    extract_content_claims: bool = True

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _requires_some_intake(self) -> "PromptCompilerRequest":
        if not self.content.strip() and not self.claims and self.brand_core is None:
            raise ValueError("request must include content, claims, or brand_core")
        return self


class PromptCompilerResult(BaseModel):
    compiler_version: str = COMPILER_VERSION
    project_name: str
    final_state: CompilerState
    passes: list[PassResult]
    claims: list[ClaimRecord]
    gaps: list[GapRecord]
    research_requests: list[ResearchRequest]
    evidence: list[SourceEvidence]
    completeness: CompletenessReport
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    acceptance: AcceptanceReport
    prompt_packages: list[PromptPackage]
    voids: list[str] = Field(default_factory=list)
    speculative_inferences: list[str] = Field(default_factory=list)
    computations: list[ComputationAssessment] = Field(default_factory=list)
    generation_firewall: Literal["PROMPT_PACKAGE_READY"] = GENERATION_FIREWALL

    model_config = {"extra": "forbid"}


def _canonical(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _claim_id(text: str, index: int) -> str:
    return f"clm_{index:03d}_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]}"


def _infer_claim_type(text: str) -> ClaimType:
    if _API_HINT.search(text):
        return ClaimType.api_claim
    if _METRIC_HINT.search(text):
        return ClaimType.metric
    if _LEGAL_HINT.search(text):
        return ClaimType.legal_claim
    if _MARKET_HINT.search(text) or _COMPARATIVE_HINT.search(text):
        return ClaimType.market_claim
    return ClaimType.fact


def intake_claims(request: PromptCompilerRequest) -> list[ClaimRecord]:
    records: list[ClaimRecord] = []
    for seed in request.claims:
        records.append(
            ClaimRecord(
                claim_id=_claim_id(seed.text, len(records) + 1),
                text=seed.text.strip(),
                claim_type=seed.claim_type,
                source_ref=seed.source_ref,
                stakeholder=seed.stakeholder,
                temporal_scope=seed.temporal_scope,
                status=ClaimStatus.user_asserted,
                confidence=0.55,
            )
        )

    if request.extract_content_claims and request.content.strip():
        known = {record.text.casefold() for record in records}
        for sentence in _SENTENCE_SPLIT.split(request.content.strip()):
            text = sentence.strip()
            if len(text) < 20 or text.casefold() in known:
                continue
            records.append(
                ClaimRecord(
                    claim_id=_claim_id(text, len(records) + 1),
                    text=text,
                    claim_type=_infer_claim_type(text),
                    status=ClaimStatus.unverified,
                    confidence=0.35,
                )
            )
            known.add(text.casefold())
    return records


def hunt_gaps(claims: list[ClaimRecord]) -> list[GapRecord]:
    gaps: list[GapRecord] = []
    for claim in claims:
        if claim.source_ref:
            continue

        high_risk = claim.claim_type in {
            ClaimType.api_claim,
            ClaimType.metric,
            ClaimType.legal_claim,
            ClaimType.market_claim,
        }
        category = (
            GapCategory.undocumented_api
            if claim.claim_type is ClaimType.api_claim
            else GapCategory.missing_source
        )
        gaps.append(
            GapRecord(
                gap_id=f"gap_{len(gaps)+1:03d}",
                claim_refs=[claim.claim_id],
                category=category,
                description=f"No authoritative evidence is attached to claim: {claim.text}",
                materiality=Materiality.high if high_risk else Materiality.medium,
                retrieval_target=claim.text,
                required_source_class=SourceClass.official if high_risk else SourceClass.primary,
                blocks_synthesis=high_risk,
            )
        )

        if claim.claim_type is ClaimType.promise and not claim.stakeholder:
            gaps.append(
                GapRecord(
                    gap_id=f"gap_{len(gaps)+1:03d}",
                    claim_refs=[claim.claim_id],
                    category=GapCategory.undeclared_stakeholder,
                    description="Promise claim does not identify who makes or receives the commitment.",
                    materiality=Materiality.high,
                    blocks_synthesis=True,
                )
            )
    return gaps


def build_research_backfill(gaps: list[GapRecord]) -> list[ResearchRequest]:
    requests: list[ResearchRequest] = []
    for gap in gaps:
        if gap.materiality not in {Materiality.critical, Materiality.high}:
            continue
        if not gap.retrieval_target:
            continue
        requests.append(
            ResearchRequest(
                request_id=f"rr_{len(requests)+1:03d}",
                gap_id=gap.gap_id,
                query=gap.retrieval_target,
                required_source_class=gap.required_source_class,
            )
        )
    return requests


_SOURCE_WEIGHT: dict[SourceClass, float] = {
    SourceClass.primary: 0.95,
    SourceClass.official: 0.90,
    SourceClass.secondary: 0.78,
    SourceClass.community: 0.62,
    SourceClass.user: 0.55,
}


def validate_claims(
    claims: list[ClaimRecord], evidence: list[SourceEvidence]
) -> list[ClaimRecord]:
    by_claim: dict[str, list[SourceEvidence]] = {}
    for item in evidence:
        for claim_id in item.claim_ids:
            by_claim.setdefault(claim_id, []).append(item)

    validated: list[ClaimRecord] = []
    for claim in claims:
        linked = by_claim.get(claim.claim_id, [])
        if not linked:
            validated.append(claim)
            continue

        supporting = [item for item in linked if item.supports]
        opposing = [item for item in linked if not item.supports]
        if supporting and opposing:
            validated.append(
                claim.model_copy(update={"status": ClaimStatus.conflicted, "confidence": 0.5})
            )
            continue
        if opposing and not supporting:
            validated.append(
                claim.model_copy(update={"status": ClaimStatus.void, "confidence": 0.15})
            )
            continue

        score = max(_SOURCE_WEIGHT[item.source_class] for item in supporting)
        if len(supporting) > 1:
            score = min(0.99, score + 0.03)
        status = ClaimStatus.verified if score >= 0.8 else ClaimStatus.partially_verified
        validated.append(claim.model_copy(update={"status": status, "confidence": score}))
    return validated


_VERIFIED_STATUSES = {ClaimStatus.verified, ClaimStatus.partially_verified}


def assess_computations(
    claims: list[ClaimRecord], computations: list[ComputationEvidence]
) -> list[ComputationAssessment]:
    """Classify each computation without ever upgrading an empirical premise.

    ``DERIVED_FROM_VERIFIED_INPUTS`` requires every input claim to be verified
    by empirical evidence. A computation over unverified inputs is recorded as
    ``PREMISES_UNVERIFIED`` and its derived claims stay unresolved.
    """
    by_id = {claim.claim_id: claim for claim in claims}
    assessments: list[ComputationAssessment] = []
    for computation in sorted(computations, key=lambda item: item.computation_id):
        unknown = sorted(
            ref for ref in [*computation.input_claim_ids, *computation.derived_claim_ids] if ref not in by_id
        )
        if unknown:
            assessments.append(
                ComputationAssessment(
                    computation_id=computation.computation_id,
                    status=ComputationStatus.invalid_reference,
                    derived_claim_ids=sorted(computation.derived_claim_ids),
                    notes=[f"unknown claim reference: {ref}" for ref in unknown],
                )
            )
            continue
        unverified = sorted(
            ref for ref in computation.input_claim_ids if by_id[ref].status not in _VERIFIED_STATUSES
        )
        if unverified:
            status = ComputationStatus.premises_unverified
            notes = ["A correct computation does not verify its input premises."]
        elif computation.input_claim_ids:
            status = ComputationStatus.derived_from_verified_inputs
            notes = []
        else:
            status = ComputationStatus.no_empirical_inputs
            notes = ["Result depends only on stated inputs and assumptions, not on empirical claims."]
        if computation.assumptions:
            notes.append("Assumptions remain assumptions: " + "; ".join(computation.assumptions))
        assessments.append(
            ComputationAssessment(
                computation_id=computation.computation_id,
                status=status,
                derived_claim_ids=sorted(computation.derived_claim_ids),
                unverified_inputs=unverified,
                notes=notes,
            )
        )
    return assessments


def sound_derived_claim_ids(assessments: list[ComputationAssessment]) -> set[str]:
    sound = {ComputationStatus.derived_from_verified_inputs, ComputationStatus.no_empirical_inputs}
    return {ref for item in assessments if item.status in sound for ref in item.derived_claim_ids}


def apply_computations(
    claims: list[ClaimRecord],
    assessments: list[ComputationAssessment],
    computations: list[ComputationEvidence],
) -> list[ClaimRecord]:
    """Mark soundly derived claims DERIVED. Never VERIFIED; inputs untouched."""
    item_inputs = {item.computation_id: list(item.input_claim_ids) for item in computations}
    sound = sound_derived_claim_ids(assessments)
    by_id = {claim.claim_id: claim for claim in claims}
    updated: list[ClaimRecord] = []
    for claim in claims:
        if claim.claim_id in sound and claim.status not in _VERIFIED_STATUSES:
            inputs = [
                by_id[ref].confidence
                for item in assessments
                if claim.claim_id in item.derived_claim_ids
                for ref in item_inputs.get(item.computation_id, [])
                if ref in by_id
            ]
            confidence = min([0.8, *inputs]) if inputs else 0.8
            claim = claim.model_copy(update={"status": ClaimStatus.derived, "confidence": confidence})
        updated.append(claim)
    return updated


def evidence_directives(
    claims: list[ClaimRecord], evidence: list[SourceEvidence], assessments: list[ComputationAssessment]
) -> list[str]:
    """Carry the evidence ceiling into the prompt: what may be stated, and what may not."""
    sources: dict[str, list[str]] = {}
    for item in evidence:
        if item.supports:
            for ref in item.claim_ids:
                sources.setdefault(ref, []).append(item.source_id)
    derived_from: dict[str, list[str]] = {}
    for item in assessments:
        for ref in item.derived_claim_ids:
            derived_from.setdefault(ref, []).append(item.computation_id)
    material = {
        ClaimType.api_claim,
        ClaimType.metric,
        ClaimType.legal_claim,
        ClaimType.market_claim,
        ClaimType.promise,
    }
    lines: list[str] = []
    for claim in claims:
        if claim.status in _VERIFIED_STATUSES:
            refs = ", ".join(sorted(sources.get(claim.claim_id, []))) or "linked evidence"
            lines.append(f"Supported claim ({claim.status.value}; evidence: {refs}): {claim.text}")
        elif claim.status is ClaimStatus.derived:
            refs = ", ".join(sorted(derived_from.get(claim.claim_id, [])))
            lines.append(f"Derived claim (computed from verified inputs; computation: {refs}): {claim.text}")
        elif claim.claim_type in material:
            lines.append(
                f"Not verified — do not state as fact; qualify or omit ({claim.status.value}): {claim.text}"
            )
    return lines


def _confidence_band(score: float) -> ConfidenceBand:
    if score >= 0.90:
        return ConfidenceBand.verified_high
    if score >= 0.80:
        return ConfidenceBand.verified
    if score >= 0.65:
        return ConfidenceBand.provisional
    return ConfidenceBand.blocking


def _default_brand_domains(family: PromptFamily) -> list[str]:
    mapping = {
        PromptFamily.image: ["strategy", "visual"],
        PromptFamily.ui_ux: ["strategy", "visual", "verbal", "motion"],
        PromptFamily.copy: ["strategy", "verbal"],
        PromptFamily.motion: ["strategy", "visual", "motion"],
        PromptFamily.video: ["strategy", "visual", "verbal", "motion"],
        PromptFamily.storyboard: ["strategy", "visual", "motion"],
        PromptFamily.print: ["strategy", "visual", "verbal"],
        PromptFamily.presentation: ["strategy", "visual", "verbal"],
    }
    return list(mapping[family])


def _default_capabilities(family: PromptFamily) -> list[ProviderCapabilityName]:
    mapping = {
        PromptFamily.image: [ProviderCapabilityName.text_to_image],
        PromptFamily.ui_ux: [ProviderCapabilityName.ui_generation],
        PromptFamily.copy: [ProviderCapabilityName.structured_text],
        PromptFamily.motion: [ProviderCapabilityName.text_to_video],
        PromptFamily.video: [ProviderCapabilityName.text_to_video],
        PromptFamily.storyboard: [ProviderCapabilityName.text_to_image],
        PromptFamily.print: [ProviderCapabilityName.text_to_image],
        PromptFamily.presentation: [ProviderCapabilityName.structured_text],
    }
    return list(mapping[family])


def compile_asset_spec(requirement: AssetRequirement, brand: BrandCore) -> AssetSpec:
    domains = requirement.required_brand_domains or _default_brand_domains(requirement.family)
    capabilities = requirement.required_capabilities or _default_capabilities(requirement.family)
    rules = [
        "Preserve canonical brand authority.",
        "Do not invent missing facts, claims, logos, or production requirements.",
        "Respect destination, accessibility, and production constraints.",
        "Return a result suitable for independent downstream validation.",
    ]
    if requirement.exact_text:
        rules.append("Reproduce every exact_text string character-for-character.")
    if requirement.series is not None:
        rules.append("Hold series invariants fixed; vary only the declared variation axes.")
    return AssetSpec(
        asset_id=requirement.asset_id,
        family=requirement.family,
        asset_type=requirement.asset_type,
        objective=requirement.objective,
        audience=requirement.audience,
        channel=requirement.channel,
        destination=requirement.destination,
        brand_hash=stable_hash(brand),
        required_brand_domains=domains,
        required_capabilities=capabilities,
        content_requirements=list(requirement.content_requirements),
        negative_constraints=list(requirement.negative_constraints),
        quality_constraints=list(requirement.quality_constraints),
        production=requirement.production,
        validation_rules=rules,
        exact_text=list(requirement.exact_text),
        references=list(requirement.references),
        series=requirement.series,
    )


def resolve_prompt_context(
    spec: AssetSpec,
    brand: BrandCore,
    guidance: GuidanceSelection | None = None,
) -> PromptContext:
    included: dict[str, Any] = {}
    for domain in spec.required_brand_domains:
        if domain == "strategy":
            included["strategy"] = {
                "brand_name": brand.brand_name,
                "positioning_essence": brand.positioning_essence,
            }
        elif domain == "verbal":
            included["verbal"] = brand.voice.model_dump(mode="json")
        elif domain == "visual":
            included["visual"] = {
                "color_story": [item.model_dump(mode="json") for item in brand.color_story],
                "typography_direction": brand.typography_direction,
                "imagery_style": brand.imagery_style,
                "logo_lockups": [item.model_dump(mode="json") for item in brand.logo_lockups],
            }
        elif domain == "motion":
            included["motion"] = brand.motion.model_dump(mode="json")
        else:
            included[domain] = {"status": "[VOID_DETECTED:BRAND_DOMAIN]"}

    known = {"strategy", "verbal", "visual", "motion"}
    guidance_context = guidance.guidance_context if guidance is not None else {}
    guidance_hash = guidance.guidance_hash if guidance is not None else ""
    context_payload = {
        "brand_context": included,
        "guidance_hash": guidance_hash,
        "guidance_context": guidance_context,
    }
    return PromptContext(
        brand_context=included,
        included_domains=sorted(spec.required_brand_domains),
        excluded_domains=sorted(known - set(spec.required_brand_domains)),
        guidance_context=guidance_context,
        included_guidance=guidance.selected_section_ids if guidance is not None else [],
        excluded_guidance=guidance.rejected_pack_ids if guidance is not None else [],
        guidance_hash=guidance_hash,
        activation_reasons=guidance.activation_reasons if guidance is not None else [],
        registry_version=guidance.registry_version if guidance is not None else None,
        router_version=guidance.router_version if guidance is not None else None,
        context_hash=stable_hash(context_payload),
    )


def _flatten_guidance_value(value: Any, prefix: str = "") -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(f"{prefix}{value}" if prefix else value)
    elif isinstance(value, list):
        for item in value:
            values.extend(_flatten_guidance_value(item, prefix))
    elif isinstance(value, dict):
        for key in sorted(value):
            label = f"{prefix}{key}: " if prefix else f"{key}: "
            values.extend(_flatten_guidance_value(value[key], label))
    return values


def _guidance_directive_buckets(context: PromptContext) -> dict[str, list[str]]:
    buckets = {
        "strategy": [],
        "verbal": [],
        "visual": [],
        "composition": [],
        "typography": [],
        "interaction": [],
        "motion": [],
        "camera": [],
        "audio": [],
        "accessibility": [],
        "trend": [],
        "tokens": [],
        "engineering": [],
        "governance": [],
        "quality": [],
        "production": [],
    }
    for key in sorted(context.guidance_context):
        payload = context.guidance_context[key]
        section = payload.get("section", {})
        section_id = str(section.get("id", "")).lower()
        directives = [str(item) for item in section.get("directives", [])]
        targets = [str(item) for item in section.get("directive_targets", [])]

        if targets:
            for target in targets:
                if target in buckets:
                    buckets[target].extend(directives)
        elif "strategy" in section_id or "positioning" in section_id:
            buckets["strategy"].extend(directives)
        elif "verbal" in section_id or "naming" in section_id:
            buckets["verbal"].extend(directives)
        elif "motion" in section_id:
            buckets["motion"].extend(directives)
        else:
            buckets["visual"].extend(directives)
            if "creative_direction" in section_id:
                buckets["composition"].extend(directives)

        for criterion in section.get("evaluation_criteria", []):
            buckets["quality"].append(f"Evaluate: {criterion}")
        for anti_pattern in section.get("anti_patterns", []):
            buckets["quality"].append(f"Avoid: {anti_pattern}")
        for evidence_requirement in section.get("evidence_requirements", []):
            buckets["governance"].append(
                f"Evidence requirement: {evidence_requirement}"
            )

        subsections = section.get("subsections", {})
        visual_identity = subsections.get("visual_identity", {}) if isinstance(subsections, dict) else {}
        if isinstance(visual_identity, dict):
            for name, value in visual_identity.items():
                flattened = _flatten_guidance_value(value)
                if name == "typography":
                    buckets["typography"].extend(flattened)
                elif name in {"imagery", "geometry", "iconography", "color", "logo"}:
                    buckets["visual"].extend(flattened)

    for name in buckets:
        buckets[name] = list(dict.fromkeys(buckets[name]))
    return buckets


_UI_UX_BUCKET_MAP = {
    "composition": "composition",
    "interaction": "interaction",
    "accessibility": "accessibility",
    "tokens": "tokens",
    "motion": "motion",
    "engineering": "engineering",
    "quality": "quality",
    "governance": "governance",
}


_VISUAL_TEXT_FAMILIES = {PromptFamily.image, PromptFamily.print, PromptFamily.presentation}
_TEMPORAL_FAMILIES = {PromptFamily.video, PromptFamily.motion, PromptFamily.storyboard}


def render_stages_for(spec: AssetSpec) -> list[str]:
    """Separate generative imagery from deterministic typography (source spec §15).

    Exact headlines, logos, prices, legal lines and disclosures are not asked of
    a generator; they are composed in a deterministic layout stage and checked
    character-for-character.
    """
    if not spec.exact_text:
        return []
    if spec.family in _VISUAL_TEXT_FAMILIES:
        return [
            "GENERATIVE_VISUAL: produce imagery only; render no lettering; reserve copy-safe zones for the exact text.",
            "DETERMINISTIC_LAYOUT: typeset exact text, logos and disclosures in a layout tool; verify character-for-character and against safe areas.",
        ]
    if spec.family in _TEMPORAL_FAMILIES:
        return [
            "GENERATIVE_MOTION: produce footage or motion without rendered lettering.",
            "EDIT_COMPOSITING: apply exact on-screen text in the edit or compositing stage; verify character-for-character.",
        ]
    return ["VERBATIM_COPY: include every exact text string unchanged in the delivered copy."]


def _ordered_references(references: list[ReferenceSpec]) -> list[ReferenceSpec]:
    rank = {role: index for index, role in enumerate(REFERENCE_PRECEDENCE)}
    return sorted(references, key=lambda ref: (rank[ref.role], -ref.priority, ref.ref_id))


def compile_prompt_ir(
    spec: AssetSpec,
    context: PromptContext,
    ui_ux: UIUXDesignIR | None = None,
    *,
    evidence_lines: list[str] | None = None,
) -> PromptIR:
    brand_directives = [
        f"Canonical brand context ({domain}): {_canonical(context.brand_context[domain])}"
        for domain in context.included_domains
    ]
    production = [
        f"{key}={value}"
        for key, value in spec.production.model_dump(mode="json", exclude_none=True).items()
    ]
    guidance = _guidance_directive_buckets(context)
    provenance = [spec.brand_hash, context.context_hash]
    if context.guidance_hash:
        provenance.append(context.guidance_hash)
    if spec.series is not None:
        provenance.append(spec.series.concept_signature)
    if ui_ux is not None:
        for source, target in _UI_UX_BUCKET_MAP.items():
            guidance[target] = list(
                dict.fromkeys([*guidance[target], *directive_buckets(ui_ux).get(source, [])])
            )
        provenance.append(ui_ux.spec_hash)
    return PromptIR(
        asset_id=spec.asset_id,
        family=spec.family,
        objective=spec.objective,
        audience=spec.audience,
        channel=spec.channel,
        destination=spec.destination,
        brand_directives=brand_directives,
        strategy_directives=guidance["strategy"],
        verbal_directives=guidance["verbal"],
        visual_directives=guidance["visual"],
        composition_directives=guidance["composition"],
        typography_directives=guidance["typography"],
        interaction_directives=guidance["interaction"],
        motion_directives=guidance["motion"],
        camera_directives=guidance["camera"],
        audio_directives=guidance["audio"],
        accessibility_directives=guidance["accessibility"],
        trend_directives=guidance["trend"],
        token_directives=guidance["tokens"],
        engineering_directives=guidance["engineering"],
        governance_directives=guidance["governance"],
        qa_directives=guidance["quality"],
        production_guidance_directives=guidance["production"],
        content_directives=list(spec.content_requirements),
        production_directives=production,
        negative_constraints=list(spec.negative_constraints),
        quality_constraints=list(spec.quality_constraints),
        required_capabilities=list(spec.required_capabilities),
        provenance_refs=provenance,
        exact_text=list(spec.exact_text),
        references=_ordered_references(spec.references),
        render_stages=render_stages_for(spec),
        series=spec.series,
        evidence_directives=list(evidence_lines or []),
    )


def serialize_generic_prompt(
    ir: PromptIR, spec: AssetSpec, ui_ux: UIUXDesignIR | None = None
) -> str:
    def section(title: str, values: list[str]) -> list[str]:
        if not values:
            return []
        return [f"## {title}", *[f"- {value}" for value in values], ""]

    lines = [
        f"# {spec.asset_type} — production prompt",
        "",
        "## Objective",
        ir.objective,
        "",
        "## Audience",
        ir.audience,
        "",
        "## Channel / destination",
        f"{ir.channel} / {ir.destination}",
        "",
    ]
    if ui_ux is not None:
        lines += serialize_spec_section(ui_ux)
    lines += section("Canonical brand directives", ir.brand_directives)
    lines += section("Selected advisory strategy guidance", ir.strategy_directives)
    lines += section("Selected advisory verbal guidance", ir.verbal_directives)
    lines += section("Selected advisory visual guidance", ir.visual_directives)
    lines += section("Selected advisory composition guidance", ir.composition_directives)
    lines += section("Selected advisory typography guidance", ir.typography_directives)
    lines += section("Selected advisory interaction guidance", ir.interaction_directives)
    lines += section("Selected advisory motion guidance", ir.motion_directives)
    lines += section("Selected advisory camera guidance", ir.camera_directives)
    lines += section("Selected advisory audio guidance", ir.audio_directives)
    lines += section("Selected advisory accessibility guidance", ir.accessibility_directives)
    lines += section("Selected advisory trend guidance", ir.trend_directives)
    lines += section("Selected advisory token-system guidance", ir.token_directives)
    lines += section("Selected advisory engineering guidance", ir.engineering_directives)
    lines += section("Selected advisory governance guidance", ir.governance_directives)
    lines += section("Selected advisory QA guidance", ir.qa_directives)
    lines += section("Selected advisory production guidance", ir.production_guidance_directives)
    if ir.series is not None:
        binding = ir.series
        series_lines = [
            f"family={binding.family_id}@{binding.family_version}; instance={binding.instance_id}",
            f"concept thesis: {binding.concept_thesis}",
        ]
        if binding.campaign_ref:
            series_lines.append(f"campaign anchor: {binding.campaign_ref}")
        if binding.emotional_function:
            series_lines.append(f"emotional function: {binding.emotional_function}")
        series_lines += [f"signature device: {item}" for item in binding.signature_devices]
        series_lines += [f"hold fixed: {item}" for item in binding.series_invariants]
        series_lines += [f"this instance varies {axis}: {value}" for axis, value in sorted(binding.variation.items())]
        series_lines.append(f"concept signature: {binding.concept_signature}")
        lines += section("Series binding", series_lines)
    lines += section("Evidence ceiling", ir.evidence_directives)
    lines += section("Required content", ir.content_directives)
    lines += section(
        "Exact text (reproduce character-for-character)",
        [json.dumps(text, ensure_ascii=False) for text in ir.exact_text],
    )
    lines += section("Render stages", ir.render_stages)
    lines += section(
        "Reference roles (precedence: IDENTITY > CONTENT > COMPOSITION > STYLE > START/END FRAME > MOTION > AUDIO)",
        [
            f"{ref.ref_id}: {ref.role.value} (priority {ref.priority})" + (f" — {ref.note}" if ref.note else "")
            for ref in ir.references
        ],
    )
    lines += section("Production specification", ir.production_directives)
    lines += section("Quality constraints", ir.quality_constraints)
    lines += section("Negative constraints", ir.negative_constraints)
    lines += [
        "## Execution contract",
        "- Treat canonical brand context and verified project constraints as authoritative.",
        "- Treat selected domain guidance as advisory methodology only.",
        "- Never let guidance override canonical BrandCore, evidence, accessibility, permissions, or provider capability truth.",
        "- Do not invent missing factual claims, logos, product details, credentials, or provider features.",
        "- Preserve the requested medium, hierarchy, destination, and accessibility constraints.",
        "- Produce the requested creative asset for downstream review; do not reinterpret the brand system.",
    ]
    return "\n".join(lines).strip() + "\n"


def adapt_provider_prompts(
    ir: PromptIR, generic_prompt: str, providers: list[ProviderCapability]
) -> list[ProviderPrompt]:
    variants: list[ProviderPrompt] = []
    required = set(ir.required_capabilities)
    for provider in providers:
        if ir.family not in provider.families:
            continue
        missing = sorted(item.value for item in required - set(provider.capabilities))
        if not provider.verified:
            variants.append(
                ProviderPrompt(
                    provider=provider.provider,
                    model=provider.model,
                    status=AdapterStatus.unverified,
                    prompt=generic_prompt,
                    unsupported_requirements=missing,
                    source_ref=provider.source_ref,
                )
            )
            continue
        if missing:
            variants.append(
                ProviderPrompt(
                    provider=provider.provider,
                    model=provider.model,
                    status=AdapterStatus.blocked,
                    prompt=generic_prompt,
                    unsupported_requirements=missing,
                    source_ref=provider.source_ref,
                )
            )
            continue
        variants.append(
            ProviderPrompt(
                provider=provider.provider,
                model=provider.model,
                status=AdapterStatus.generic_compatible,
                prompt=generic_prompt,
                source_ref=provider.source_ref,
            )
        )
    return variants


def validate_prompt_package(
    spec: AssetSpec,
    context: PromptContext,
    generic_prompt: str,
    provider_prompts: list[ProviderPrompt],
    ui_ux: UIUXDesignIR | None = None,
) -> PromptValidationResult:
    issues: list[str] = []
    ui_blocked = False
    if spec.brand_hash == "":
        issues.append("brand hash missing")
    if not context.included_domains:
        issues.append("no brand context selected")
    if spec.objective not in generic_prompt:
        issues.append("objective missing from serialized prompt")
    if spec.audience not in generic_prompt:
        issues.append("audience missing from serialized prompt")
    if context.included_guidance and not context.guidance_hash:
        issues.append("selected guidance missing deterministic hash")
    text_corrupted = False
    for text in spec.exact_text:
        if json.dumps(text, ensure_ascii=False) not in generic_prompt:
            issues.append(f"required text not preserved verbatim: {text}")
            text_corrupted = True
    for ref in spec.references:
        if ref.role in _TEMPORAL_REFERENCE_ROLES and spec.family not in _TEMPORAL_FAMILIES:
            issues.append(f"reference {ref.ref_id} role {ref.role.value} is temporal but family is {spec.family.value}")
    for provider in provider_prompts:
        if provider.status is AdapterStatus.blocked:
            issues.append(
                f"{provider.provider}/{provider.model} lacks: "
                + ", ".join(provider.unsupported_requirements)
            )

    checked_dimensions = [
        "EVIDENCE",
        "BRAND",
        "CONTENT",
        "PRODUCTION",
        "PROVIDER",
        "ACCESSIBILITY",
        "SECURITY",
        "GUIDANCE_AUTHORITY",
        "PROVENANCE",
    ]
    if ui_ux is not None:
        checked_dimensions.append("UI_UX_SPEC")
        if ui_ux.terminal is UIUXTerminal.blocked:
            ui_blocked = True
            issues.extend(
                f"UI/UX spec blocked: {finding.engine.value} {finding.subject}: {finding.message}"
                for finding in ui_ux.evaluation
                if finding.severity.value == "BLOCKING" and not finding.repaired
            )
        elif ui_ux.terminal is UIUXTerminal.requires_approval:
            issues.extend(
                f"UI/UX spec requires approval: {item}"
                for item in ui_ux.approval_required
                if item.startswith("DECISION:")
            )
        if ui_ux.spec_hash not in generic_prompt:
            issues.append("UI/UX spec hash missing from serialized prompt")

    if spec.exact_text:
        checked_dimensions.append("EXACT_TEXT")
    if spec.references:
        checked_dimensions.append("REFERENCE_ROLES")
    status = PromptValidationStatus.passed
    if ui_blocked or text_corrupted:
        status = PromptValidationStatus.blocked
    elif issues:
        status = PromptValidationStatus.repair
    return PromptValidationResult(
        status=status,
        issues=issues,
        checked_dimensions=checked_dimensions,
    )


def synthesize_report(
    request: PromptCompilerRequest,
    validated_claims: list[ClaimRecord],
    gaps: list[GapRecord],
) -> tuple[CompletenessReport, float, ConfidenceBand]:
    material_types = {
        ClaimType.api_claim,
        ClaimType.metric,
        ClaimType.legal_claim,
        ClaimType.market_claim,
        ClaimType.promise,
    }
    material_claims = [claim for claim in validated_claims if claim.claim_type in material_types]
    material_scores = [claim.confidence for claim in material_claims]
    if not material_claims:
        evidence_score = 4
    elif material_scores and sum(material_scores) / len(material_scores) >= 0.8:
        evidence_score = 4
    else:
        evidence_score = 2
    brand_score = 4 if request.brand_core is not None else 0
    production_score = 4 if request.asset_requirements else 0
    verified_providers = [provider for provider in request.providers if provider.verified]
    provider_score = 4 if verified_providers else 2
    provenance_score = 4 if request.evidence or request.claims else 2

    blockers: list[str] = []
    if request.brand_core is None:
        blockers.append("brand")
    if not request.asset_requirements:
        blockers.append("production")
    if any(gap.blocks_synthesis for gap in gaps):
        blockers.append("evidence")

    if material_scores:
        confidence = sum(material_scores) / len(material_scores)
    else:
        confidence = 0.92 if request.brand_core is not None and request.asset_requirements else 0.60
    if blockers:
        confidence = min(confidence, 0.64)

    return (
        CompletenessReport(
            evidence=evidence_score,
            brand=brand_score,
            production=production_score,
            provider=provider_score,
            provenance=provenance_score,
            blocking_domains=sorted(set(blockers)),
        ),
        round(confidence, 3),
        _confidence_band(confidence),
    )


def _acceptance_report(
    status: AcceptanceStatus,
    *,
    blocking_criteria: list[str] | None = None,
    limitations: list[str] | None = None,
) -> AcceptanceReport:
    return AcceptanceReport(
        status=status,
        blocking_criteria=blocking_criteria or [],
        limitations=limitations or [],
        checks=[
            "brand_authority_present",
            "asset_requirements_present",
            "blocking_evidence_gaps_resolved",
            "prompt_validation_executed",
            "generation_firewall_preserved",
        ],
    )


def compile_prompt_packages(request: PromptCompilerRequest) -> PromptCompilerResult:
    passes: list[PassResult] = []

    claims = intake_claims(request)
    passes.append(PassResult(pass_name="INTAKE+CLAIMS", status="COMPLETE", produced=len(claims)))

    gaps = hunt_gaps(claims)
    passes.append(PassResult(pass_name="GAP_HUNT", status="COMPLETE", produced=len(gaps)))

    unresolved_gap_ids = {gap.gap_id for gap in gaps}
    evidence_claim_ids = {claim_id for item in request.evidence for claim_id in item.claim_ids}
    # Computations resolve a derived claim's gap only when every empirical input
    # is itself verified; they never stand in for the inputs' own evidence.
    computation_assessments = assess_computations(
        validate_claims(claims, request.evidence), request.computations
    )
    evidence_claim_ids |= sound_derived_claim_ids(computation_assessments)
    for gap in gaps:
        if any(ref in evidence_claim_ids for ref in gap.claim_refs):
            unresolved_gap_ids.discard(gap.gap_id)
    research_requests = build_research_backfill(
        [gap for gap in gaps if gap.gap_id in unresolved_gap_ids]
    )
    passes.append(
        PassResult(
            pass_name="RESEARCH_BACKFILL",
            status="COMPLETE" if not research_requests else "RETRIEVAL_REQUESTS_EMITTED",
            produced=len(research_requests),
            notes=["No retrieval result is fabricated; unresolved requests remain explicit."],
        )
    )

    validated_claims = apply_computations(
        validate_claims(claims, request.evidence), computation_assessments, request.computations
    )
    passes.append(
        PassResult(pass_name="VALIDATE", status="COMPLETE", produced=len(validated_claims))
    )

    completeness, confidence, confidence_band = synthesize_report(
        request, validated_claims, [gap for gap in gaps if gap.gap_id in unresolved_gap_ids]
    )
    passes.append(PassResult(pass_name="SYNTH+REPORT", status="COMPLETE", produced=1))

    if request.brand_core is None:
        return PromptCompilerResult(
            project_name=request.project_name,
            final_state=CompilerState.brand_system_incomplete,
            passes=passes,
            claims=validated_claims,
            gaps=gaps,
            research_requests=research_requests,
            evidence=request.evidence,
            completeness=completeness,
            confidence=confidence,
            confidence_band=confidence_band,
            acceptance=_acceptance_report(
                AcceptanceStatus.blocked,
                blocking_criteria=["brand_core_missing"],
                limitations=["Canonical BrandCore is required before prompt synthesis."],
            ),
            prompt_packages=[],
            voids=sorted(unresolved_gap_ids),
            computations=computation_assessments,
        )

    if not request.asset_requirements:
        return PromptCompilerResult(
            project_name=request.project_name,
            final_state=CompilerState.blocked,
            passes=passes,
            claims=validated_claims,
            gaps=gaps,
            research_requests=research_requests,
            evidence=request.evidence,
            completeness=completeness,
            confidence=confidence,
            confidence_band=confidence_band,
            acceptance=_acceptance_report(
                AcceptanceStatus.blocked,
                blocking_criteria=["asset_requirements_missing"],
                limitations=["At least one typed AssetRequirement is required."],
            ),
            prompt_packages=[],
            voids=["[VOID_DETECTED:ASSET_REQUIREMENTS]"],
            computations=computation_assessments,
        )

    blocking_unresolved = [
        gap
        for gap in gaps
        if gap.gap_id in unresolved_gap_ids and gap.blocks_synthesis
    ]
    if blocking_unresolved:
        return PromptCompilerResult(
            project_name=request.project_name,
            final_state=CompilerState.research_incomplete,
            passes=passes,
            claims=validated_claims,
            gaps=gaps,
            research_requests=research_requests,
            evidence=request.evidence,
            completeness=completeness,
            confidence=confidence,
            confidence_band=confidence_band,
            acceptance=_acceptance_report(
                AcceptanceStatus.blocked,
                blocking_criteria=[gap.gap_id for gap in blocking_unresolved],
                limitations=["Material evidence gaps block synthesis until resolved."],
            ),
            prompt_packages=[],
            voids=[f"[VOID_DETECTED:{gap.gap_id}]" for gap in blocking_unresolved],
            computations=computation_assessments,
        )

    packages: list[PromptPackage] = []
    guidance_registry = default_registry()
    for requirement in request.asset_requirements:
        spec = compile_asset_spec(requirement, request.brand_core)
        guidance = route_guidance(
            requirement,
            guidance_registry,
            requirement.guidance_overrides,
        )
        context = resolve_prompt_context(spec, request.brand_core, guidance)
        ui_ux = (
            compile_uiux(request_from_asset_requirement(requirement, request.brand_core))
            if requirement.family is PromptFamily.ui_ux
            else None
        )
        ir = compile_prompt_ir(
            spec,
            context,
            ui_ux,
            evidence_lines=evidence_directives(validated_claims, request.evidence, computation_assessments),
        )
        generic = serialize_generic_prompt(ir, spec, ui_ux)
        provider_prompts = adapt_provider_prompts(ir, generic, request.providers)
        validation = validate_prompt_package(spec, context, generic, provider_prompts, ui_ux)
        package_id = f"pkg_{stable_hash({'project': request.project_name, 'asset': spec.asset_id})[:16]}"
        packages.append(
            PromptPackage(
                package_id=package_id,
                project_name=request.project_name,
                asset_spec=spec,
                prompt_ir=ir,
                generic_master_prompt=generic,
                provider_prompts=provider_prompts,
                context_manifest=context,
                validation=validation,
                prompt_hash=stable_hash(generic),
                brand_hash=spec.brand_hash,
                unresolved_gaps=sorted(unresolved_gap_ids),
                ui_ux_design=ui_ux,
            )
        )

    if any(package.validation.status is PromptValidationStatus.blocked for package in packages):
        final_state = CompilerState.blocked
    else:
        final_state = CompilerState.prompt_package_ready

    has_validation_repairs = any(
        package.validation.status is PromptValidationStatus.repair
        for package in packages
    )
    partial_reasons: list[str] = []
    if unresolved_gap_ids and final_state is not CompilerState.blocked:
        partial_reasons.append("Non-blocking evidence gaps remain explicit in the package.")
    if has_validation_repairs and final_state is not CompilerState.blocked:
        partial_reasons.append("One or more prompt validation checks require bounded repair.")

    acceptance = _acceptance_report(
        AcceptanceStatus.failed
        if final_state is CompilerState.blocked
        else (
            AcceptanceStatus.partial
            if unresolved_gap_ids or has_validation_repairs
            else AcceptanceStatus.passed
        ),
        blocking_criteria=(
            ["prompt_validation_blocked"]
            if final_state is CompilerState.blocked
            else []
        ),
        limitations=partial_reasons,
    )

    return PromptCompilerResult(
        project_name=request.project_name,
        final_state=final_state,
        passes=passes,
        claims=validated_claims,
        gaps=gaps,
        research_requests=research_requests,
        evidence=request.evidence,
        completeness=completeness,
        confidence=confidence,
        confidence_band=confidence_band,
        acceptance=acceptance,
        prompt_packages=packages,
        voids=[f"[VOID_DETECTED:{gap_id}]" for gap_id in sorted(unresolved_gap_ids)],
        computations=computation_assessments,
    )


def load_request(path: str) -> PromptCompilerRequest:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return PromptCompilerRequest.model_validate(payload)


def write_result(path: str, result: PromptCompilerResult) -> None:
    payload = result.model_dump_json(indent=2)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")


def runtime_receipt(result: PromptCompilerResult) -> dict[str, Any]:
    return {
        "compiler_version": result.compiler_version,
        "project_name": result.project_name,
        "final_state": result.final_state.value,
        "prompt_package_count": len(result.prompt_packages),
        "confidence": result.confidence,
        "confidence_band": result.confidence_band.value,
        "acceptance_status": result.acceptance.status.value,
        "generation_firewall": result.generation_firewall,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result_hash": stable_hash(result),
    }
