"""T05 — human-process ontology for the compiled agency.

S00-S25 is a cross-domain *process ontology*, not a serial state machine: N2
(``kernel/lifecycle.py``) stays the only lifecycle authority. MB0-MB8 are
conditional overlays selected by domain; a logo refinement never instantiates
software beta or app-store work.

Stage → RoleOS phase bindings are compiled advisory metadata (INFERENCE over
``runtime/role_os/phases.runtime.json``), used to choose a phase for a work
order. They carry no authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from services.langgraph.agency.kernel.ontology import ArtifactType


class Domain(str, Enum):
    BRAND = "BRAND"
    GRAPHIC_DESIGN = "GRAPHIC_DESIGN"
    PRODUCT_DESIGN = "PRODUCT_DESIGN"
    UX_UI = "UX_UI"
    WEB = "WEB"
    SOFTWARE = "SOFTWARE"
    MOBILE_APP = "MOBILE_APP"
    FILM = "FILM"
    VIDEO = "VIDEO"
    MOTION = "MOTION"
    ANIMATION = "ANIMATION"
    VFX = "VFX"
    CONTENT = "CONTENT"
    DIGITAL_MARKETING = "DIGITAL_MARKETING"
    TRADITIONAL_ADVERTISING = "TRADITIONAL_ADVERTISING"
    MEDIA = "MEDIA"
    ANALYTICS = "ANALYTICS"
    BUSINESS_OPERATIONS = "BUSINESS_OPERATIONS"


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    name: str
    scope: str
    roleos_phase: str


LIFECYCLE_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition("S00", "SIGNAL", "inbound, outbound, referral, partner, RFP, existing-client need", "P0"),
    StageDefinition("S01", "QUALIFY", "fit, urgency, budget, authority, value, conflicts, capacity", "P1"),
    StageDefinition("S02", "COMMERCIAL_DISCOVERY", "objectives, stakeholders, procurement, NDA, constraints", "P2"),
    StageDefinition("S03", "RESEARCH", "company, user, customer, category, competitor, culture, analytics, technology, legal, operations", "P4"),
    StageDefinition("S04", "SYNTHESIS", "evidence map, insight, problem/opportunity model", "P4"),
    StageDefinition("S05", "BRIEF", "outcome, audience, proposition, requirements, constraints, metrics", "P5"),
    StageDefinition("S06", "STRATEGY", "brand/product/content/channel/experience/technical/production strategy", "P5"),
    StageDefinition("S07", "SCOPE", "deliverables, exclusions, dependencies, assumptions, acceptance", "P3"),
    StageDefinition("S08", "ESTIMATE", "effort, staffing, vendors, contingency, schedule, margin", "P3"),
    StageDefinition("S09", "CONTRACT", "proposal, SOW, MSA, IP, payment, change-control", "P3"),
    StageDefinition("S10", "KICKOFF", "governance, communication, tools, files, cadence, RAID", "P4"),
    StageDefinition("S11", "PLAN", "roadmap, backlog, IA, preproduction, media/production plan", "P8"),
    StageDefinition("S12", "EXPLORE", "hypotheses, concepts, territories, prototypes, tests", "P7"),
    StageDefinition("S13", "SELECT", "comparison, evidence, selection", "P7"),
    StageDefinition("S14", "PRODUCE", "design, write, code, shoot, animate, build, configure, traffic", "P9"),
    StageDefinition("S15", "INTERNAL_REVIEW", "discipline, creative, technical, business review", "P10"),
    StageDefinition("S16", "CLIENT_REVIEW", "client presentation, feedback, revision, approval", "P11"),
    StageDefinition("S17", "QA", "correctness, a11y, performance, security, legal, brand, platform/spec QA", "P10"),
    StageDefinition("S18", "RELEASE", "print, build, deploy, master, publish, traffic, activate", "P12"),
    StageDefinition("S19", "VERIFY_RELEASE", "smoke/proof/publication/tracking validation", "P12"),
    StageDefinition("S20", "HANDOFF", "sources, documentation, guidelines, runbooks, training", "P12"),
    StageDefinition("S21", "MEASURE", "brand/product/campaign/operational measurement", "P13"),
    StageDefinition("S22", "OPTIMIZE", "experiment, iterate, maintain, support", "P14"),
    StageDefinition("S23", "FINANCIAL_CLOSE", "vendor close, reconciliation, invoice, margin/utilization", "P15"),
    StageDefinition("S24", "ARCHIVE", "files, rights, decisions, versions, approvals, learnings", "P15"),
    StageDefinition("S25", "REUSE", "case study, portfolio, award submission, templates, reusable knowledge", "P15"),
)
STAGES_BY_ID = {s.stage_id: s for s in LIFECYCLE_STAGES}


def _stage_range(first: int, last: int) -> tuple[str, ...]:
    return tuple(f"S{n:02d}" for n in range(first, last + 1))


@dataclass(frozen=True)
class Overlay:
    overlay_id: str
    name: str
    stages: tuple[str, ...]
    domains: frozenset[Domain]


_ALL = frozenset(Domain)
_BRAND = frozenset({Domain.BRAND, Domain.GRAPHIC_DESIGN})
_DIGITAL = frozenset({Domain.PRODUCT_DESIGN, Domain.UX_UI, Domain.WEB, Domain.SOFTWARE, Domain.MOBILE_APP})
_SOFTWARE = frozenset({Domain.WEB, Domain.SOFTWARE, Domain.MOBILE_APP})
_MEDIA = frozenset({
    Domain.FILM, Domain.VIDEO, Domain.MOTION, Domain.ANIMATION, Domain.VFX, Domain.CONTENT,
    Domain.DIGITAL_MARKETING, Domain.TRADITIONAL_ADVERTISING, Domain.MEDIA,
})

MASTER_BUILDER_OVERLAYS: tuple[Overlay, ...] = (
    Overlay("MB0", "DISCOVERY/PROBLEM_MAPPING", _stage_range(2, 5), _ALL),
    Overlay("MB1", "STRATEGY/POSITIONING/NAMING", _stage_range(5, 9), _BRAND | _MEDIA | _DIGITAL),
    Overlay("MB2", "VISUAL_EXPLORATION", _stage_range(12, 13), _BRAND | _MEDIA | frozenset({Domain.UX_UI, Domain.PRODUCT_DESIGN})),
    Overlay("MB3", "IDENTITY_SYSTEM", _stage_range(14, 17), _BRAND),
    Overlay("MB4", "ALPHA/PROTOTYPING", _stage_range(11, 17), _DIGITAL),
    Overlay("MB5", "BETA/SECURITY/PRE_RELEASE", _stage_range(14, 19), _SOFTWARE),
    Overlay("MB6", "VIDEO/CONTENT/360_CAMPAIGN", _stage_range(11, 19), _MEDIA),
    Overlay("MB7", "APP_DISTRIBUTION", _stage_range(18, 19), frozenset({Domain.MOBILE_APP})),
    Overlay("MB8", "LIVE_OPERATIONS", _stage_range(20, 25), _SOFTWARE | frozenset({Domain.ANALYTICS})),
)


def select_overlays(domains: Iterable[Domain | str], *, live_service: bool = False) -> tuple[str, ...]:
    """Compile only the overlays the requested domains justify."""
    wanted = {Domain(d) for d in domains}
    selected = []
    for overlay in MASTER_BUILDER_OVERLAYS:
        if not (overlay.domains & wanted):
            continue
        # Live operations only exist for a live service.
        if overlay.overlay_id == "MB8" and not live_service:
            continue
        selected.append(overlay.overlay_id)
    return tuple(selected)


# Per-domain process maps (spec §10), kept as data. They inform backchain
# templates; no domain compiler executes solely because it exists.
DOMAIN_PROCESS_MAPS: dict[str, tuple[str, ...]] = {
    "BRAND": ("discovery", "research", "positioning", "brand_architecture", "naming_when_required", "verbal_identity",
              "creative_territories", "visual_motion_sonic_systems", "applications", "guidelines", "rollout", "governance"),
    "PRODUCT_UX": ("research", "problem_framing", "journeys", "information_architecture", "flows", "wireframes", "prototype",
                   "testing", "ui", "tokens_components", "responsive_a11y", "handoff", "design_qa"),
    "WEB": ("discovery", "content_seo_audit", "information_architecture", "wireframes", "design", "cms_data_architecture",
            "frontend_backend", "integrations", "analytics", "a11y_performance_security_qa", "migration", "deployment",
            "monitoring", "maintenance"),
    "SOFTWARE_APP": ("opportunity", "product_discovery", "prd", "domain_model", "architecture", "backlog", "ux_ui",
                     "api_data_contracts", "implementation", "qa", "beta_where_applicable", "platform_compliance",
                     "release", "telemetry", "support"),
    "FILM_VIDEO": ("brief", "treatment", "estimate", "script", "boards", "previz", "casting_location_crew", "schedule_shotlist",
                   "production", "ingest_backup", "edit_review", "vfx_motion", "color", "sound", "captions", "rights_qc",
                   "masters", "variants_distribution_archive"),
    "MARKETING": ("goals", "audience_data_audit", "channel_strategy", "measurement_architecture", "campaign_content_plan",
                  "production", "trafficking", "launch", "optimization", "reporting"),
    "SEO": ("crawl", "intent_keyword_research", "architecture", "content", "technical", "authority", "measure"),
    "PAID": ("goals", "audiences_keywords", "structure", "creative", "landing_experience", "tracking", "activation", "optimization"),
    "SOCIAL": ("audience", "content_pillars", "calendar", "production", "approval", "publish", "community"),
    "CRM": ("segments", "journeys", "copy_design", "build", "qa", "trigger", "measure"),
    "CRO": ("analytics", "hypothesis", "experiment", "qa", "run", "analysis", "decision"),
    "TRADITIONAL_ADVERTISING": ("planning", "insight", "brief", "creative", "production", "business_legal", "media_plan_buy",
                                "traffic", "proof", "launch", "post_buy"),
}


class ProcessElement(str, Enum):
    ACTOR = "ACTOR"
    ACTION = "ACTION"
    TRIGGER = "TRIGGER"
    INPUT = "INPUT"
    TOOL = "TOOL"
    ARTIFACT = "ARTIFACT"
    DECISION = "DECISION"
    RULE = "RULE"
    HANDOFF = "HANDOFF"
    WAIT = "WAIT"
    EXCEPTION = "EXCEPTION"
    APPROVAL = "APPROVAL"
    OUTPUT = "OUTPUT"


class FailureRoute(str, Enum):
    BLOCK = "BLOCK"
    RECORD_CONFLICT_REVIEW = "RECORD_CONFLICT+REVIEW"
    RESEARCH = "RESEARCH"
    BOUNDED_RETRY = "BOUNDED_RETRY"
    RECONCILE = "RECONCILE"
    COMPENSATE = "COMPENSATE"
    REJECT_REVISE = "REJECT/REVISE"
    LAST_APPROVED_STATE_REPAIR = "LAST_APPROVED_STATE_REPAIR"
    WAIT = "WAIT"
    ESCALATE = "ESCALATE"
    EXACT_APPROVAL = "EXACT_APPROVAL"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"


_F = FailureRoute
EXCEPTION_CATALOG: dict[str, FailureRoute] = {
    "ambiguous_goal": _F.RESEARCH,
    "conflicting_stakeholders": _F.RECORD_CONFLICT_REVIEW,
    "hidden_decider": _F.ESCALATE,
    "procurement_delay": _F.WAIT,
    "missing_agreement_or_nda": _F.BLOCK,
    "ip_trademark_conflict": _F.ESCALATE,
    "stale_or_contradictory_research": _F.RECORD_CONFLICT_REVIEW,
    "scope_creep": _F.RECORD_CONFLICT_REVIEW,
    "timeline_compression": _F.ESCALATE,
    "specialist_or_vendor_unavailable": _F.WAIT,
    "budget_overrun": _F.ESCALATE,
    "dependency_delay": _F.WAIT,
    "client_silence": _F.WAIT,
    "contradictory_feedback": _F.RECORD_CONFLICT_REVIEW,
    "approval_revoked": _F.EXACT_APPROVAL,
    "superseded_artifact": _F.LAST_APPROVED_STATE_REPAIR,
    "wrong_version_release": _F.COMPENSATE,
    "accessibility_failure": _F.REJECT_REVISE,
    "security_vulnerability": _F.ESCALATE,
    "privacy_consent_failure": _F.ESCALATE,
    "unlicensed_asset": _F.BLOCK,
    "talent_music_location_rights_gap": _F.BLOCK,
    "platform_store_rejection": _F.LAST_APPROVED_STATE_REPAIR,
    "deployment_failure": _F.COMPENSATE,
    "analytics_mismatch": _F.RECORD_CONFLICT_REVIEW,
    "print_broadcast_production_defect": _F.REJECT_REVISE,
    "corrupted_media_or_project_file": _F.LAST_APPROVED_STATE_REPAIR,
    "model_hallucination": _F.REJECT_REVISE,
    "source_prompt_injection": _F.BLOCK,
    "tool_failure": _F.BOUNDED_RETRY,
    "duplicate_non_idempotent_action": _F.RECONCILE,
    "uncertain_external_result": _F.RECONCILE,
    "irreversible_publication_error": _F.ESCALATE,
    "missing_source": _F.BLOCK,
    "repeated_non_progress": _F.CIRCUIT_BREAKER,
}


def route_exception(kind: str) -> FailureRoute:
    """Unknown exception kinds escalate rather than defaulting to retry."""
    return EXCEPTION_CATALOG.get(kind, FailureRoute.ESCALATE)


# Which lifecycle stage an N1 artifact is characteristically produced in, and
# which domains it serves. Domains with no N1 artifact (e.g. FILM masters)
# surface as ARTIFACT_TYPE_UNMODELED in the backchain rather than being faked.
ARTIFACT_STAGE: dict[ArtifactType, str] = {
    ArtifactType.research_brief: "S03",
    ArtifactType.market_analysis: "S04",
    ArtifactType.knowledge_capsule: "S25",
    ArtifactType.positioning_statement: "S06",
    ArtifactType.business_model_spec: "S06",
    ArtifactType.offer_definition: "S06",
    ArtifactType.brand_platform: "S06",
    ArtifactType.brand_core: "S06",
    ArtifactType.naming_candidate: "S12",
    ArtifactType.identity_guidelines: "S14",
    ArtifactType.brand_guidelines_doc: "S20",
    ArtifactType.creative_concept: "S12",
    ArtifactType.asset_prompt_set: "S14",
    ArtifactType.copy_variant: "S14",
    ArtifactType.design_brief: "S11",
    ArtifactType.design_system_spec: "S14",
    ArtifactType.design_token_set: "S14",
    ArtifactType.website_lockup_spec: "S14",
    ArtifactType.product_spec: "S11",
    ArtifactType.implementation_plan: "S11",
    ArtifactType.app_build_spec: "S14",
    ArtifactType.automation_spec: "S14",
    ArtifactType.campaign_package: "S14",
    ArtifactType.media_plan: "S11",
    ArtifactType.measurement_plan: "S11",
    ArtifactType.qa_report: "S17",
    ArtifactType.release_record: "S18",
}


def roleos_phase_for(artifact_type: ArtifactType) -> str:
    return STAGES_BY_ID[ARTIFACT_STAGE[artifact_type]].roleos_phase


# Stages where the work is a consequential external act (spec §37).
CONSEQUENTIAL_STAGES = frozenset({"S09", "S18", "S23"})
