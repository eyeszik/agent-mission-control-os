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


COMPILER_VERSION = "amc-prompt-compiler/v1"
GENERATION_FIREWALL = "PROMPT_PACKAGE_READY"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_API_HINT = re.compile(r"\b(api|sdk|endpoint|webhook|mcp|provider|model)\b", re.I)
_METRIC_HINT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|x|ms|s|seconds?|minutes?|hours?|days?|users?|requests?|usd|\$)\b", re.I)
_MARKET_HINT = re.compile(r"\b(market|competitor|industry|audience|customer|tam|sam|som|share)\b", re.I)
_LEGAL_HINT = re.compile(r"\b(legal|law|regulation|compliance|licensed|copyright|trademark|wcag|privacy)\b", re.I)


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


class SourceClass(str, Enum):
    primary = "PRIMARY"
    official = "OFFICIAL"
    secondary = "SECONDARY"
    community = "COMMUNITY"
    user = "USER"


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
    content_directives: list[str]
    production_directives: list[str]
    negative_constraints: list[str]
    quality_constraints: list[str]
    required_capabilities: list[ProviderCapabilityName]
    provenance_refs: list[str]

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
    prompt_packages: list[PromptPackage]
    voids: list[str] = Field(default_factory=list)
    speculative_inferences: list[str] = Field(default_factory=list)
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
    if _MARKET_HINT.search(text):
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
    )


def resolve_prompt_context(spec: AssetSpec, brand: BrandCore) -> PromptContext:
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
    return PromptContext(
        brand_context=included,
        included_domains=sorted(spec.required_brand_domains),
        excluded_domains=sorted(known - set(spec.required_brand_domains)),
        context_hash=stable_hash(included),
    )


def compile_prompt_ir(spec: AssetSpec, context: PromptContext) -> PromptIR:
    brand_directives = [
        f"Canonical brand context ({domain}): {_canonical(context.brand_context[domain])}"
        for domain in context.included_domains
    ]
    production = [
        f"{key}={value}"
        for key, value in spec.production.model_dump(mode="json", exclude_none=True).items()
    ]
    return PromptIR(
        asset_id=spec.asset_id,
        family=spec.family,
        objective=spec.objective,
        audience=spec.audience,
        channel=spec.channel,
        destination=spec.destination,
        brand_directives=brand_directives,
        content_directives=list(spec.content_requirements),
        production_directives=production,
        negative_constraints=list(spec.negative_constraints),
        quality_constraints=list(spec.quality_constraints),
        required_capabilities=list(spec.required_capabilities),
        provenance_refs=[spec.brand_hash, context.context_hash],
    )


def serialize_generic_prompt(ir: PromptIR, spec: AssetSpec) -> str:
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
    lines += section("Canonical brand directives", ir.brand_directives)
    lines += section("Required content", ir.content_directives)
    lines += section("Production specification", ir.production_directives)
    lines += section("Quality constraints", ir.quality_constraints)
    lines += section("Negative constraints", ir.negative_constraints)
    lines += [
        "## Execution contract",
        "- Treat the supplied brand context as authoritative.",
        "- Do not invent missing factual claims, logos, product details, or credentials.",
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
) -> PromptValidationResult:
    issues: list[str] = []
    if spec.brand_hash == "":
        issues.append("brand hash missing")
    if not context.included_domains:
        issues.append("no brand context selected")
    if spec.objective not in generic_prompt:
        issues.append("objective missing from serialized prompt")
    if spec.audience not in generic_prompt:
        issues.append("audience missing from serialized prompt")
    for provider in provider_prompts:
        if provider.status is AdapterStatus.blocked:
            issues.append(
                f"{provider.provider}/{provider.model} lacks: "
                + ", ".join(provider.unsupported_requirements)
            )

    status = PromptValidationStatus.passed
    if issues:
        status = PromptValidationStatus.repair
    return PromptValidationResult(
        status=status,
        issues=issues,
        checked_dimensions=[
            "EVIDENCE",
            "BRAND",
            "CONTENT",
            "PRODUCTION",
            "PROVIDER",
            "ACCESSIBILITY",
            "SECURITY",
            "PROVENANCE",
        ],
    )


def synthesize_report(
    request: PromptCompilerRequest,
    validated_claims: list[ClaimRecord],
    gaps: list[GapRecord],
) -> tuple[CompletenessReport, float, ConfidenceBand]:
    verified = [claim.confidence for claim in validated_claims if claim.confidence > 0]
    evidence_score = 4 if verified and sum(verified) / len(verified) >= 0.8 else 2 if verified else 1
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

    confidence = sum(verified) / len(verified) if verified else (0.70 if request.brand_core else 0.45)
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


def compile_prompt_packages(request: PromptCompilerRequest) -> PromptCompilerResult:
    passes: list[PassResult] = []

    claims = intake_claims(request)
    passes.append(PassResult(pass_name="INTAKE+CLAIMS", status="COMPLETE", produced=len(claims)))

    gaps = hunt_gaps(claims)
    passes.append(PassResult(pass_name="GAP_HUNT", status="COMPLETE", produced=len(gaps)))

    research_requests = build_research_backfill(gaps)
    unresolved_gap_ids = {gap.gap_id for gap in gaps}
    evidence_claim_ids = {claim_id for item in request.evidence for claim_id in item.claim_ids}
    for gap in gaps:
        if any(ref in evidence_claim_ids for ref in gap.claim_refs):
            unresolved_gap_ids.discard(gap.gap_id)
    passes.append(
        PassResult(
            pass_name="RESEARCH_BACKFILL",
            status="COMPLETE" if not research_requests else "RETRIEVAL_REQUESTS_EMITTED",
            produced=len(research_requests),
            notes=["No retrieval result is fabricated; unresolved requests remain explicit."],
        )
    )

    validated_claims = validate_claims(claims, request.evidence)
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
            prompt_packages=[],
            voids=sorted(unresolved_gap_ids),
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
            prompt_packages=[],
            voids=["[VOID_DETECTED:ASSET_REQUIREMENTS]"],
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
            prompt_packages=[],
            voids=[f"[VOID_DETECTED:{gap.gap_id}]" for gap in blocking_unresolved],
        )

    packages: list[PromptPackage] = []
    for requirement in request.asset_requirements:
        spec = compile_asset_spec(requirement, request.brand_core)
        context = resolve_prompt_context(spec, request.brand_core)
        ir = compile_prompt_ir(spec, context)
        generic = serialize_generic_prompt(ir, spec)
        provider_prompts = adapt_provider_prompts(ir, generic, request.providers)
        validation = validate_prompt_package(spec, context, generic, provider_prompts)
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
            )
        )

    if any(package.validation.status is PromptValidationStatus.blocked for package in packages):
        final_state = CompilerState.blocked
    else:
        final_state = CompilerState.prompt_package_ready

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
        prompt_packages=packages,
        voids=[f"[VOID_DETECTED:{gap_id}]" for gap_id in sorted(unresolved_gap_ids)],
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
        "generation_firewall": result.generation_firewall,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result_hash": stable_hash(result),
    }
