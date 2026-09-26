"""Deterministic full-service agency contracts compiled from a campaign brief.

This module closes the gap between "named agency capability" and a testable
handoff contract without inventing external evidence. Unknown research,
licenses, legal review, accessibility verification, production telemetry, and
SLO baselines remain explicit states. The compiler never performs network
calls, media spend, publication, or legal clearance.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ProofStatus = Literal["PROVED", "UNPROVED", "UNKNOWN"]
ResearchStatus = Literal["READY", "NEEDS_EXTERNAL_EVIDENCE"]
VerificationStatus = Literal["PASS", "FAIL", "NOT_RUN", "NOT_APPLICABLE"]
LicenseStatus = Literal["SOURCE_ATTACHED", "UNKNOWN", "NOT_REQUIRED"]
PortfolioPermission = Literal["GRANTED", "DENIED", "UNKNOWN"]
LegalStatus = Literal["UNKNOWN", "SOURCE_ATTACHED", "COUNSEL_REQUIRED"]
TelemetryStatus = Literal["BOUND", "PARTIAL", "UNBOUND"]
ModelCardStatus = Literal["COMPLETE", "INCOMPLETE"]


class ResearchEvidenceInput(BaseModel):
    evidence_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_class: Literal["USER_ASSERTION", "PRIMARY", "SECONDARY", "REPOSITORY"] = "USER_ASSERTION"
    verified: bool = False


class ClaimProofInput(BaseModel):
    claim: str = Field(min_length=1)
    proof_status: ProofStatus = "UNKNOWN"
    evidence_refs: list[str] = Field(default_factory=list)
    ship_as_fact: bool = False

    @model_validator(mode="after")
    def _proved_claim_requires_evidence(self) -> "ClaimProofInput":
        if self.proof_status == "PROVED" and not self.evidence_refs:
            raise ValueError("PROVED claims require at least one evidence_ref")
        return self


class AssetRightsInput(BaseModel):
    asset_id: str = Field(min_length=1)
    owner: str | None = None
    license_status: LicenseStatus = "UNKNOWN"
    license_ref: str | None = None
    release_use_authorized: bool = False
    portfolio_permission: PortfolioPermission = "UNKNOWN"
    territory: str | None = None
    expires_at: str | None = None
    access_expires_at: str | None = None
    contact: str | None = None
    offboarding_action: str | None = None

    @model_validator(mode="after")
    def _source_attached_requires_ref(self) -> "AssetRightsInput":
        if self.license_status == "SOURCE_ATTACHED" and not self.license_ref:
            raise ValueError("SOURCE_ATTACHED license_status requires license_ref")
        return self


class AccessibilityCheckInput(BaseModel):
    check: Literal["contrast", "keyboard", "assistive_technology", "reduced_motion"]
    status: VerificationStatus
    evidence_ref: str | None = None

    @model_validator(mode="after")
    def _pass_requires_evidence(self) -> "AccessibilityCheckInput":
        if self.status == "PASS" and not self.evidence_ref:
            raise ValueError("PASS accessibility checks require evidence_ref")
        return self


class MediaPlanningInput(BaseModel):
    markets: list[str] = Field(default_factory=list)
    flight_start: str | None = None
    flight_end: str | None = None
    budget_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    kpis: list[str] = Field(default_factory=list)
    creative_specs: list[str] = Field(default_factory=list)
    execution_requested: bool = False


class ResearchPackage(BaseModel):
    status: ResearchStatus
    verified_evidence_count: int = Field(ge=0)
    audience_brief: str
    interview_guide: list[str]
    competitive_audit: list[str]
    stakeholder_map: list[str]
    perception_gap: list[str]
    category_language: list[str]
    evidence_refs: list[str]
    limitations: list[str]


class ClaimProofRecord(BaseModel):
    claim_id: str
    claim: str
    proof_status: ProofStatus
    evidence_refs: list[str]
    ship_as_fact: bool


class ClaimsProofRegistry(BaseModel):
    claims: list[ClaimProofRecord]
    blocking_reasons: list[str]


class RightsRecord(BaseModel):
    asset_id: str
    owner: str | None
    license_status: LicenseStatus
    license_ref: str | None
    release_use_authorized: bool
    portfolio_permission: PortfolioPermission
    territory: str | None
    expires_at: str | None
    access_expires_at: str | None
    contact: str | None
    offboarding_action: str | None


class HandoffRightsManifest(BaseModel):
    assets: list[RightsRecord]
    blocking_reasons: list[str]
    notes: list[str]


class AccessibilityCheck(BaseModel):
    check: str
    status: VerificationStatus
    evidence_ref: str | None


class AccessibilityEvidence(BaseModel):
    applicable: bool
    standard: Literal["WCAG 2.2"] = "WCAG 2.2"
    checks: list[AccessibilityCheck]
    blocking_reasons: list[str]
    limitations: list[str]


class MediaTraffickingRow(BaseModel):
    channel: str
    market: str | None
    flight_start: str | None
    flight_end: str | None
    creative_spec: str
    status: Literal["PLANNING_ONLY"] = "PLANNING_ONLY"


class MediaPlan(BaseModel):
    execution_mode: Literal["PLANNING_ONLY"] = "PLANNING_ONLY"
    audience: str
    markets: list[str]
    flight_start: str | None
    flight_end: str | None
    budget_minor: int | None
    currency: str | None
    kpis: list[str]
    creative_specs: list[str]
    trafficking_sheet: list[MediaTraffickingRow]
    execution_requested: bool
    blocking_reasons: list[str]
    notes: list[str]


class LegalReadiness(BaseModel):
    status: LegalStatus
    regulatory_context: list[str]
    source_refs: list[str]
    blocking_reasons: list[str]
    note: str


class TelemetrySignal(BaseModel):
    signal: Literal["events", "logs", "metrics", "traces"]
    status: TelemetryStatus
    evidence_ref: str | None
    owner: str
    retention: str
    alert_condition: str


class ObservabilityContract(BaseModel):
    schema_version: Literal["amc-observability/v1"] = "amc-observability/v1"
    service_identity: Literal["UNBOUND"] = "UNBOUND"
    status: Literal["PARTIAL"] = "PARTIAL"
    signals: list[TelemetrySignal]
    notes: list[str]


class SLOObjective(BaseModel):
    name: str
    indicator: str
    target: float | None
    target_status: Literal["BASELINE_REQUIRED"] = "BASELINE_REQUIRED"
    owner: str
    evidence_refs: list[str]


class SLOContract(BaseModel):
    schema_version: Literal["amc-slo/v1"] = "amc-slo/v1"
    status: Literal["BASELINE_REQUIRED"] = "BASELINE_REQUIRED"
    objectives: list[SLOObjective]
    notes: list[str]


class ModelCard(BaseModel):
    task: str
    provider: str | None
    model: str | None
    mode: str
    schema_version: str
    prompt_version: str
    prompt_hash: str
    status: ModelCardStatus
    evaluation_mode: Literal["HEURISTIC_ONLY"] = "HEURISTIC_ONLY"
    limitations: list[str]


class FullServicePlan(BaseModel):
    schema_version: Literal["amc-full-service/v1"] = "amc-full-service/v1"
    market: str | None
    language: str | None
    locale: str | None
    research: ResearchPackage
    claims: ClaimsProofRegistry
    handoff_rights: HandoffRightsManifest
    accessibility: AccessibilityEvidence
    media: MediaPlan
    legal_readiness: LegalReadiness
    observability: ObservabilityContract
    slo: SLOContract
    model_cards: list[ModelCard]
    blocking_reasons: list[str]
    advisories: list[str]


def _claim_id(text: str) -> str:
    return "claim-" + sha256(text.strip().encode("utf-8")).hexdigest()[:12]


def _compile_research(brief: dict) -> ResearchPackage:
    evidence = [
        ResearchEvidenceInput.model_validate(item)
        for item in (brief.get("research_evidence") or [])
    ]
    verified = [item for item in evidence if item.verified]
    target = str(brief.get("target_audience") or "Audience not specified")
    industry = str(brief.get("industry") or "category not specified")
    differentiators = [str(item) for item in (brief.get("differentiators") or []) if str(item).strip()]
    category_terms = [industry]
    category_terms.extend(differentiators)
    if brief.get("offer_summary"):
        category_terms.append(str(brief["offer_summary"]))

    return ResearchPackage(
        status="READY" if len(verified) >= 3 else "NEEDS_EXTERNAL_EVIDENCE",
        verified_evidence_count=len(verified),
        audience_brief=(
            f"Primary audience: {target}. Existing brief statements are treated as user assertions "
            "until independently evidenced."
        ),
        interview_guide=[
            "What problem are you trying to solve, and what triggers you to look for a solution?",
            "What alternatives do you use today, including doing nothing?",
            "What creates friction, doubt, or delay before switching?",
            "Which words do you naturally use to describe the problem and a successful outcome?",
            "What evidence would make a new option credible enough to try?",
        ],
        competitive_audit=[
            f"Identify direct competitors, indirect alternatives, and substitutes in {industry}.",
            "Compare category parity, distinctive claims, proof quality, pricing/offer structure, and adoption friction.",
            "Record source references for every factual comparison; unknowns remain UNKNOWN.",
        ],
        stakeholder_map=[
            f"Primary audience — {target}",
            "Brand owner / accountable approver",
            "Delivery and operations owner",
            "Specialist reviewer when legal, accessibility, security, or regulated-domain evidence is required",
        ],
        perception_gap=[
            "Current audience perception: UNKNOWN until research evidence is attached.",
            "Desired perception: derive from approved positioning and validate against audience evidence.",
            "Do not convert a desired perception into a claimed current fact.",
        ],
        category_language=list(dict.fromkeys(item for item in category_terms if item and item != "None")),
        evidence_refs=[item.source_ref for item in evidence],
        limitations=(
            []
            if len(verified) >= 3
            else [
                "Fewer than three verified research evidence items are attached; research outputs are a plan/hypothesis, not confirmed market findings."
            ]
        ),
    )


def _compile_claims(brief: dict) -> ClaimsProofRegistry:
    records: dict[str, ClaimProofRecord] = {}
    for raw in brief.get("claim_proofs") or []:
        item = ClaimProofInput.model_validate(raw)
        claim_id = _claim_id(item.claim)
        records[claim_id] = ClaimProofRecord(
            claim_id=claim_id,
            claim=item.claim.strip(),
            proof_status=item.proof_status,
            evidence_refs=list(item.evidence_refs),
            ship_as_fact=item.ship_as_fact,
        )

    for differentiator in brief.get("differentiators") or []:
        text = str(differentiator).strip()
        if not text:
            continue
        claim_id = _claim_id(text)
        records.setdefault(
            claim_id,
            ClaimProofRecord(
                claim_id=claim_id,
                claim=text,
                proof_status="UNKNOWN",
                evidence_refs=[],
                ship_as_fact=False,
            ),
        )

    blockers = [
        f"unproved_claim:{record.claim_id}"
        for record in records.values()
        if record.ship_as_fact and record.proof_status != "PROVED"
    ]
    return ClaimsProofRegistry(claims=list(records.values()), blocking_reasons=blockers)


def _compile_rights(brief: dict) -> HandoffRightsManifest:
    assets = [AssetRightsInput.model_validate(item) for item in (brief.get("asset_rights") or [])]
    blockers: list[str] = []
    records: list[RightsRecord] = []
    for item in assets:
        if item.license_status == "UNKNOWN":
            blockers.append(f"unknown_license:{item.asset_id}")
        if not item.release_use_authorized:
            blockers.append(f"release_use_not_authorized:{item.asset_id}")
        records.append(RightsRecord(**item.model_dump()))
    return HandoffRightsManifest(
        assets=records,
        blocking_reasons=sorted(set(blockers)),
        notes=[
            "Unknown license is never treated as permission.",
            "Portfolio permission is recorded separately from ownership and release-use authority.",
        ],
    )


_REQUIRED_A11Y_CHECKS = ("contrast", "keyboard", "assistive_technology", "reduced_motion")


def _compile_accessibility(brief: dict, design_brief: dict) -> AccessibilityEvidence:
    applicable = bool((design_brief or {}).get("ui_ux"))
    supplied = {
        item.check: item
        for item in (
            AccessibilityCheckInput.model_validate(raw)
            for raw in (brief.get("accessibility_evidence") or [])
        )
    }
    checks: list[AccessibilityCheck] = []
    blockers: list[str] = []
    for check in _REQUIRED_A11Y_CHECKS:
        if not applicable:
            status: VerificationStatus = "NOT_APPLICABLE"
            evidence_ref = None
        else:
            item = supplied.get(check)
            status = item.status if item else "NOT_RUN"
            evidence_ref = item.evidence_ref if item else None
            if status != "PASS":
                blockers.append(f"accessibility_{check}:{status.lower()}")
        checks.append(AccessibilityCheck(check=check, status=status, evidence_ref=evidence_ref))
    return AccessibilityEvidence(
        applicable=applicable,
        checks=checks,
        blocking_reasons=blockers,
        limitations=[
            "A design specification is not browser or assistive-technology verification.",
            "PASS is accepted only when the brief carries an evidence_ref for that check.",
        ],
    )


def _compile_media(brief: dict) -> MediaPlan:
    raw_media = brief.get("media")
    media = MediaPlanningInput.model_validate(raw_media or {})
    markets = list(media.markets)
    if not markets and brief.get("market"):
        markets = [str(brief["market"])]
    channels = [str(item) for item in (brief.get("channels") or [])]
    creative_specs = list(media.creative_specs) or [
        f"{channel}: creative dimensions/specification must be confirmed against the selected channel before trafficking."
        for channel in channels
    ]
    trafficking = [
        MediaTraffickingRow(
            channel=channel,
            market=markets[0] if len(markets) == 1 else None,
            flight_start=media.flight_start,
            flight_end=media.flight_end,
            creative_spec=creative_specs[index] if index < len(creative_specs) else "Specification pending",
        )
        for index, channel in enumerate(channels)
    ]
    blockers: list[str] = []
    if media.execution_requested:
        if not markets:
            blockers.append("media_market_missing")
        if not media.flight_start or not media.flight_end:
            blockers.append("media_flight_missing")
        if media.budget_minor is None or not media.currency:
            blockers.append("media_budget_missing")
        blockers.append("live_media_executor_unavailable")
    return MediaPlan(
        audience=str(brief.get("target_audience") or "Audience not specified"),
        markets=markets,
        flight_start=media.flight_start,
        flight_end=media.flight_end,
        budget_minor=media.budget_minor,
        currency=media.currency.upper() if media.currency else None,
        kpis=list(media.kpis),
        creative_specs=creative_specs,
        trafficking_sheet=trafficking,
        execution_requested=media.execution_requested,
        blocking_reasons=blockers,
        notes=[
            "This is a planning and handoff artifact only; it cannot execute spend.",
            "Provider-specific trafficking fields remain unverified until a concrete provider adapter is installed.",
        ],
    )


def _compile_legal(brief: dict) -> LegalReadiness:
    contexts = [str(item) for item in (brief.get("regulatory_context") or []) if str(item).strip()]
    refs = [str(item) for item in (brief.get("counsel_source_refs") or []) if str(item).strip()]
    if contexts and not refs:
        status: LegalStatus = "COUNSEL_REQUIRED"
        blockers = ["counsel_review_required"]
    elif refs:
        status = "SOURCE_ATTACHED"
        blockers = []
    else:
        status = "UNKNOWN"
        blockers = []
    return LegalReadiness(
        status=status,
        regulatory_context=contexts,
        source_refs=refs,
        blocking_reasons=blockers,
        note=(
            "This field records review state only. SOURCE_ATTACHED does not mean compliant, lawful, cleared, or certified."
        ),
    )


def _compile_observability() -> ObservabilityContract:
    return ObservabilityContract(
        signals=[
            TelemetrySignal(
                signal="events",
                status="BOUND",
                evidence_ref="services/langgraph/persistence/events.py",
                owner="operations",
                retention="deployment-defined",
                alert_condition="sequence/replay failure or missing terminal lifecycle event",
            ),
            TelemetrySignal(
                signal="logs",
                status="PARTIAL",
                evidence_ref="services/langgraph/graph/agency/nodes.py",
                owner="operations",
                retention="deployment-defined",
                alert_condition="runtime exception or secret/PII logging violation",
            ),
            TelemetrySignal(
                signal="metrics",
                status="PARTIAL",
                evidence_ref="services/langgraph/persistence/analytics.py",
                owner="analytics",
                retention="deployment-defined",
                alert_condition="lifecycle failure/rejection rate or missing expected analytics events",
            ),
            TelemetrySignal(
                signal="traces",
                status="UNBOUND",
                evidence_ref=None,
                owner="engineering",
                retention="UNBOUND",
                alert_condition="UNBOUND",
            ),
        ],
        notes=[
            "The contract is vendor-neutral. Traces remain UNBOUND until a deployed telemetry backend is configured and verified.",
            "Raw secrets, access tokens, and unsanitized PII are prohibited telemetry fields.",
        ],
    )


def _compile_slo() -> SLOContract:
    return SLOContract(
        objectives=[
            SLOObjective(
                name="api_availability",
                indicator="successful authenticated API requests / eligible requests",
                target=None,
                owner="operations",
                evidence_refs=[],
            ),
            SLOObjective(
                name="agency_run_latency",
                indicator="agency run duration from creation to needs_approval or terminal failure",
                target=None,
                owner="operations",
                evidence_refs=[],
            ),
            SLOObjective(
                name="recovery_success",
                indicator="resolved recovery cases / eligible recovery cases",
                target=None,
                owner="operations",
                evidence_refs=[],
            ),
        ],
        notes=[
            "Targets remain unset until representative production baselines exist.",
            "A missing target is BASELINE_REQUIRED, never an implied pass.",
        ],
    )


def _compile_model_cards(provenance: list[dict]) -> list[ModelCard]:
    cards: list[ModelCard] = []
    for item in provenance:
        provider = item.get("provider")
        model = item.get("model")
        mode = str(item.get("mode") or "UNKNOWN")
        cards.append(
            ModelCard(
                task=str(item.get("task") or "unknown"),
                provider=str(provider) if provider is not None else None,
                model=str(model) if model is not None else None,
                mode=mode,
                schema_version=str(item.get("schema_version") or "UNKNOWN"),
                prompt_version=str(item.get("prompt_version") or "UNKNOWN"),
                prompt_hash=str(item.get("prompt_hash") or "UNKNOWN"),
                status="COMPLETE" if provider and model and mode == "PROVIDER_SUCCESS" else "INCOMPLETE",
                limitations=[
                    "Current quality evaluation is heuristic and is not an independent model benchmark.",
                    "This card describes the observed run provenance only; it does not certify model fitness.",
                ],
            )
        )
    return cards


def compile_full_service_plan(
    *,
    brief: dict,
    strategy: dict,
    design_brief: dict,
    generation_provenance: list[dict],
) -> FullServicePlan:
    """Compile the full-service handoff without external side effects."""

    research = _compile_research(brief)
    claims = _compile_claims(brief)
    rights = _compile_rights(brief)
    accessibility = _compile_accessibility(brief, design_brief)
    media = _compile_media(brief)
    legal = _compile_legal(brief)
    blockers = sorted(
        set(
            [
                *claims.blocking_reasons,
                *rights.blocking_reasons,
                *accessibility.blocking_reasons,
                *media.blocking_reasons,
                *legal.blocking_reasons,
            ]
        )
    )
    advisories: list[str] = []
    if research.status != "READY":
        advisories.extend(research.limitations)
    if not brief.get("market"):
        advisories.append("Market is unspecified; no geography is assumed.")
    if not brief.get("language"):
        advisories.append("Language is unspecified; no language is assumed.")
    if not brief.get("locale"):
        advisories.append("Locale is unspecified; no locale is assumed.")

    return FullServicePlan(
        market=brief.get("market"),
        language=brief.get("language"),
        locale=brief.get("locale"),
        research=research,
        claims=claims,
        handoff_rights=rights,
        accessibility=accessibility,
        media=media,
        legal_readiness=legal,
        observability=_compile_observability(),
        slo=_compile_slo(),
        model_cards=_compile_model_cards(generation_provenance),
        blocking_reasons=blockers,
        advisories=advisories,
    )
