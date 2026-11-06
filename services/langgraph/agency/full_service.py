"""Deterministic full-service agency operations contract.

This module closes structural handoff gaps without fabricating evidence. It
turns facts already present in the campaign state into typed research,
claims-proof, rights, accessibility, media, observability, SLO, and model-card
records. Anything that requires external evidence remains an explicit GAP,
UNKNOWN, or NOT_MEASURED state.

The compiler is pure: no provider calls, no network access, no publication,
no spend, and no filesystem mutation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ProofStatus = Literal["PROVED", "UNPROVED", "UNKNOWN"]
ReadinessStatus = Literal["SOURCE_ATTACHED", "GAP", "COUNSEL_REQUIRED"]
MeasurementStatus = Literal["MEASURED", "NOT_MEASURED"]


class ResearchCoverage(BaseModel):
    audience_brief: str
    interview_guide: list[str] = Field(default_factory=list)
    competitive_audit: list[str] = Field(default_factory=list)
    stakeholder_map: list[dict[str, str]] = Field(default_factory=list)
    perception_gaps: list[str] = Field(default_factory=list)
    category_language: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ClaimProofRecord(BaseModel):
    claim_id: str
    text: str
    status: ProofStatus
    source_ref: str | None = None
    release_note: str


class RightsRecord(BaseModel):
    asset_ref: str
    owner: str = "UNKNOWN"
    license_status: str = "UNKNOWN"
    portfolio_permission: str = "UNKNOWN"
    territory: str = "UNKNOWN"
    expiry: str | None = None
    access_expiry: str | None = None
    offboarding_status: str = "GAP"
    contact: str = "UNKNOWN"


class AccessibilityEvidence(BaseModel):
    standard_ref: str = "WCAG 2.2"
    contrast: MeasurementStatus = "NOT_MEASURED"
    keyboard: MeasurementStatus = "NOT_MEASURED"
    semantics: MeasurementStatus = "NOT_MEASURED"
    assistive_technology: MeasurementStatus = "NOT_MEASURED"
    evidence_refs: list[str] = Field(default_factory=list)
    status: ReadinessStatus = "GAP"


class MediaPlanningHandoff(BaseModel):
    audience: str
    flight: str = "UNSPECIFIED"
    market: str = "UNKNOWN"
    budget: str = "UNSPECIFIED"
    kpis: list[str] = Field(default_factory=list)
    creative_specs: list[str] = Field(default_factory=list)
    trafficking_sheet: list[dict[str, str]] = Field(default_factory=list)
    execution_mode: Literal["PLANNING_ONLY"] = "PLANNING_ONLY"


class ObservabilityContract(BaseModel):
    required_signals: list[Literal["logs", "metrics", "traces"]] = Field(
        default_factory=lambda: ["logs", "metrics", "traces"]
    )
    service_identity: str = "amc-api"
    owner: str = "operations"
    retention_policy: str = "UNKNOWN"
    alert_conditions: list[str] = Field(default_factory=list)
    runtime_binding_status: Literal["UNVERIFIED_EXTERNAL_BINDING"] = "UNVERIFIED_EXTERNAL_BINDING"


class SLORecord(BaseModel):
    name: str
    target: str = "UNSET"
    measurement_ref: str | None = None
    status: Literal["GAP_NO_BASELINE", "SOURCE_ATTACHED"] = "GAP_NO_BASELINE"


class ModelCardRecord(BaseModel):
    task: str
    provider: str | None = None
    model: str | None = None
    mode: str
    prompt_version: str | None = None
    schema_version: str | None = None
    evaluation_status: Literal["NOT_MEASURED", "SOURCE_ATTACHED"] = "NOT_MEASURED"
    limitations: list[str] = Field(default_factory=list)


class AgencyOperationsPackage(BaseModel):
    schema_version: Literal["amc-agency-operations/v1"] = "amc-agency-operations/v1"
    market: str = "UNKNOWN"
    language: str = "UNKNOWN"
    locale: str = "UNKNOWN"
    research: ResearchCoverage
    claims: list[ClaimProofRecord] = Field(default_factory=list)
    rights_handoff: list[RightsRecord] = Field(default_factory=list)
    accessibility: AccessibilityEvidence = Field(default_factory=AccessibilityEvidence)
    media: MediaPlanningHandoff
    observability: ObservabilityContract = Field(default_factory=ObservabilityContract)
    slos: list[SLORecord] = Field(default_factory=list)
    model_cards: list[ModelCardRecord] = Field(default_factory=list)
    legal_readiness: ReadinessStatus = "GAP"
    required_reviewers: list[str] = Field(default_factory=lambda: ["brand_owner"])
    unresolved_gaps: list[str] = Field(default_factory=list)
    external_release_blockers: list[str] = Field(default_factory=list)


_HIGH_STAKES_TERMS = {
    "health",
    "medical",
    "finance",
    "financial",
    "legal",
    "safety",
    "children",
    "child",
    "minor",
}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _is_high_stakes(brief: dict[str, Any]) -> bool:
    corpus = " ".join(
        _text(brief.get(key))
        for key in ("industry", "business_idea", "offer_summary", "product_type")
    ).lower()
    return any(term in corpus for term in _HIGH_STAKES_TERMS)


def _claim_records(strategy: dict[str, Any], copy_variants: list[dict[str, Any]]) -> list[ClaimProofRecord]:
    rows: list[ClaimProofRecord] = []
    positioning = _text(strategy.get("positioning_statement"))
    if positioning:
        rows.append(
            ClaimProofRecord(
                claim_id="claim-positioning-1",
                text=positioning,
                status="UNKNOWN",
                release_note="Generated positioning is not factual proof; attach an evidence source before treating factual language as verified.",
            )
        )
    for index, item in enumerate(copy_variants, start=1):
        for field in ("headline", "body"):
            value = _text(item.get(field))
            if not value:
                continue
            rows.append(
                ClaimProofRecord(
                    claim_id=f"claim-copy-{index}-{field}",
                    text=value,
                    status="UNKNOWN",
                    release_note="Copy is creative output until a source is attached; factual interpretation requires proof review.",
                )
            )
    return rows


def _rights_records(asset_execution: dict[str, Any]) -> list[RightsRecord]:
    assets = asset_execution.get("rendered_assets") or []
    return [
        RightsRecord(asset_ref=_text(item.get("asset_id") or item.get("output_path") or f"asset-{index}"))
        for index, item in enumerate(assets, start=1)
        if isinstance(item, dict)
    ]


def _model_cards(provenance: list[dict[str, Any]]) -> list[ModelCardRecord]:
    cards: list[ModelCardRecord] = []
    for item in provenance:
        if not isinstance(item, dict):
            continue
        cards.append(
            ModelCardRecord(
                task=_text(item.get("task")) or "unknown-task",
                provider=item.get("provider"),
                model=item.get("model"),
                mode=_text(item.get("mode")) or "UNKNOWN",
                prompt_version=item.get("prompt_version"),
                schema_version=item.get("schema_version"),
                limitations=[
                    "No independent benchmark or eval dataset is attached to this generation receipt.",
                    "Provider/model provenance is operational metadata, not a quality or safety certification.",
                ],
            )
        )
    return cards


def compile_agency_operations(
    *,
    brief: dict[str, Any],
    strategy: dict[str, Any],
    copy_variants: list[dict[str, Any]],
    asset_execution: dict[str, Any],
    generation_provenance: list[dict[str, Any]],
) -> AgencyOperationsPackage:
    """Compile the full-service operational handoff from existing run evidence."""

    market = _text(brief.get("market")) or "UNKNOWN"
    language = _text(brief.get("language")) or "UNKNOWN"
    locale = _text(brief.get("locale")) or "UNKNOWN"
    audience = _text(brief.get("target_audience")) or "UNKNOWN"

    category_terms = [
        value
        for value in (
            _text(brief.get("industry")),
            _text(brief.get("product_type")),
        )
        if value
    ]
    research = ResearchCoverage(
        audience_brief=audience,
        interview_guide=[
            "What problem are you trying to solve today?",
            "What do you currently use instead, and why?",
            "What would make you switch from the current option?",
            "What creates hesitation or adoption friction?",
            "What proof would make this offer credible?",
        ],
        stakeholder_map=[
            {"stakeholder": "primary_audience", "evidence_ref": "brief.target_audience"},
            {"stakeholder": "brand_owner", "evidence_ref": "required_human_reviewer"},
        ],
        category_language=category_terms,
        evidence_refs=["brief.target_audience", "brief.industry", "brief.product_type"],
        unresolved=[
            "competitive_audit_requires_external_evidence",
            "perception_gap_requires_interviews_or_research",
            "stakeholder_map_requires_named_stakeholder_validation",
        ],
    )

    claims = _claim_records(strategy, copy_variants)
    rights = _rights_records(asset_execution)
    media = MediaPlanningHandoff(
        audience=audience,
        market=market,
        creative_specs=[_text(item) for item in brief.get("channels", []) if _text(item)],
    )
    slos = [
        SLORecord(name="availability"),
        SLORecord(name="latency"),
        SLORecord(name="error_rate"),
        SLORecord(name="recovery"),
    ]
    cards = _model_cards(generation_provenance)

    unresolved = list(research.unresolved)
    blockers: list[str] = []
    if market == "UNKNOWN":
        unresolved.append("market_missing")
    if language == "UNKNOWN":
        unresolved.append("language_missing")
    if locale == "UNKNOWN":
        unresolved.append("locale_missing")
    if claims:
        unresolved.append("claim_proof_sources_missing")
        blockers.append("unproved_or_unknown_factual_claims")
    if not rights:
        unresolved.append("asset_rights_inventory_empty")
    else:
        unresolved.append("asset_rights_clearance_missing")
        blockers.append("asset_rights_clearance_missing")
    unresolved.extend(
        [
            "browser_accessibility_measurements_missing",
            "assistive_technology_verification_missing",
            "runtime_observability_binding_unverified",
            "slo_runtime_baseline_missing",
        ]
    )

    high_stakes = _is_high_stakes(brief)
    reviewers = ["brand_owner", "counsel"] if high_stakes or claims or rights else ["brand_owner"]
    legal_readiness: ReadinessStatus = "COUNSEL_REQUIRED" if "counsel" in reviewers else "GAP"

    return AgencyOperationsPackage(
        market=market,
        language=language,
        locale=locale,
        research=research,
        claims=claims,
        rights_handoff=rights,
        media=media,
        slos=slos,
        model_cards=cards,
        legal_readiness=legal_readiness,
        required_reviewers=reviewers,
        unresolved_gaps=sorted(set(unresolved)),
        external_release_blockers=sorted(set(blockers)),
    )
