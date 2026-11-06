"""T12 — Evidence/Validation Graph (EVG), validation profiles and repair routing.

Validation is compiled per work node as an ordered list of obligations. Only
the profiles that genuinely apply to an artifact are attached (spec §31: never
every profile on every deliverable). A failure routes to the *smallest causal
producer* rather than restarting a phase; unaffected branches continue.

Release is never decided here: :func:`release_blockers` delegates to the N2
``release_guard_failures`` so degraded output cannot cross the existing gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Mapping

from pydantic import BaseModel

from services.langgraph.agency.kernel.lifecycle import TransitionContext, release_guard_failures
from services.langgraph.agency.kernel.ontology import ArtifactType
from services.langgraph.agency.kernel.roles import ROLE_REGISTRY

MAX_REPAIR_ATTEMPTS = 3


class ValidationStage(str, Enum):
    SCHEMA = "SCHEMA"
    PROVENANCE = "PROVENANCE"
    LOGICAL_CONSISTENCY = "LOGICAL_CONSISTENCY"
    FRESHNESS = "FRESHNESS"
    AUTHORITY = "AUTHORITY"
    ACCEPTANCE_CRITERIA = "ACCEPTANCE_CRITERIA"
    DISCIPLINE_QA = "DISCIPLINE_QA"
    BRAND = "BRAND"
    ACCESSIBILITY = "ACCESSIBILITY"
    LEGAL_RIGHTS = "LEGAL_RIGHTS"
    PRIVACY = "PRIVACY"
    SECURITY = "SECURITY"
    FINANCIAL_COMMERCIAL = "FINANCIAL_COMMERCIAL"
    GOVERNANCE = "GOVERNANCE"
    TOOL_PROOF = "TOOL_PROOF"
    COMPLETION_PROOF = "COMPLETION_PROOF"


STAGE_ORDER = {stage: i for i, stage in enumerate(ValidationStage)}

_A = ArtifactType
_BRAND_ARTIFACTS = frozenset({
    _A.brand_platform, _A.brand_core, _A.identity_guidelines, _A.brand_guidelines_doc,
    _A.creative_concept, _A.copy_variant, _A.campaign_package, _A.asset_prompt_set,
    _A.design_brief, _A.design_system_spec, _A.design_token_set, _A.website_lockup_spec,
})
_INTERFACE_ARTIFACTS = frozenset({
    _A.design_system_spec, _A.design_token_set, _A.website_lockup_spec, _A.app_build_spec, _A.product_spec,
})
_SOFTWARE_ARTIFACTS = frozenset({_A.app_build_spec, _A.implementation_plan, _A.automation_spec})
_STRATEGIC_ARTIFACTS = frozenset({
    _A.research_brief, _A.market_analysis, _A.positioning_statement, _A.brand_platform,
    _A.business_model_spec, _A.offer_definition, _A.measurement_plan,
})
_PUBLIC_COPY = frozenset({_A.copy_variant, _A.campaign_package})
_MEDIA_DOMAINS = frozenset({"FILM", "VIDEO", "MOTION", "ANIMATION", "VFX"})
_DATA_ARTIFACTS = frozenset({_A.measurement_plan, _A.media_plan, _A.app_build_spec, _A.automation_spec})


@dataclass(frozen=True)
class ValidationProfile:
    profile_id: str
    stage: ValidationStage
    validator_skill: str
    validator_department: str
    applies: Callable[[ArtifactType, frozenset[str], bool], bool]
    # Volatile requirement keys this profile cannot evaluate without a fresh,
    # officially verified VolatileConstraint (spec §32).
    volatile_keys: tuple[str, ...] = ()


def _p(profile_id, stage, skill, dept, applies, volatile=()):
    return ValidationProfile(profile_id, stage, skill, dept, applies, tuple(volatile))


VALIDATION_PROFILES: tuple[ValidationProfile, ...] = (
    _p("GROUNDING", ValidationStage.PROVENANCE, "research-manager", "strategy",
       lambda a, d, live: a in _STRATEGIC_ARTIFACTS),
    _p("USER_NEED", ValidationStage.ACCEPTANCE_CRITERIA, "ux-researcher", "strategy",
       lambda a, d, live: a in {_A.product_spec, _A.app_build_spec}),
    _p("ACCESSIBILITY", ValidationStage.ACCESSIBILITY, "accessibility-qa-analyst", "technology",
       lambda a, d, live: a in _INTERFACE_ARTIFACTS, ("accessibility.standard",)),
    _p("SECURITY", ValidationStage.SECURITY, "cloud-security-engineer", "technology",
       lambda a, d, live: a in _SOFTWARE_ARTIFACTS, ("security.testing_standard",)),
    _p("PRIVACY", ValidationStage.PRIVACY, "privacy-officer", "operations",
       lambda a, d, live: a in _DATA_ARTIFACTS),
    _p("AI_POLICY", ValidationStage.GOVERNANCE, "ai-governance-lead", "ai-data",
       lambda a, d, live: a in {_A.asset_prompt_set, _A.copy_variant, _A.creative_concept}),
    _p("BRAND_COHESION", ValidationStage.BRAND, "brand-governance-manager", "brand",
       lambda a, d, live: a in _BRAND_ARTIFACTS),
    _p("VISUAL_DIRECTION", ValidationStage.BRAND, "creative-director", "creative",
       lambda a, d, live: a in {_A.identity_guidelines, _A.design_system_spec, _A.design_token_set, _A.website_lockup_spec}),
    _p("TRADEMARK", ValidationStage.LEGAL_RIGHTS, "trademark-counsel", "operations",
       lambda a, d, live: a is _A.naming_candidate),
    _p("CLAIMS_LEGAL", ValidationStage.LEGAL_RIGHTS, "advertising-compliance-specialist", "operations",
       lambda a, d, live: a in _PUBLIC_COPY),
    _p("APP_STORE", ValidationStage.GOVERNANCE, "mobile-engineer", "technology",
       lambda a, d, live: "MOBILE_APP" in d and a in {_A.app_build_spec, _A.release_record}, ("app_store.requirements",)),
    _p("VIDEO_RIGHTS", ValidationStage.LEGAL_RIGHTS, "rights-and-clearances-manager", "operations",
       lambda a, d, live: bool(d & _MEDIA_DOMAINS) and a in {_A.asset_prompt_set, _A.campaign_package, _A.release_record}),
    _p("LIVE_OPERATION", ValidationStage.GOVERNANCE, "site-reliability-engineer", "technology",
       lambda a, d, live: live and a in {_A.release_record, _A.app_build_spec}),
)
PROFILES_BY_ID = {p.profile_id: p for p in VALIDATION_PROFILES}

BASE_OBLIGATIONS = (
    ValidationStage.SCHEMA,
    ValidationStage.PROVENANCE,
    ValidationStage.ACCEPTANCE_CRITERIA,
    ValidationStage.DISCIPLINE_QA,
    ValidationStage.GOVERNANCE,
    ValidationStage.COMPLETION_PROOF,
)


def applicable_profiles(
    artifact_type: ArtifactType, domains: Iterable[str], *, live_service: bool = False
) -> tuple[ValidationProfile, ...]:
    d = frozenset(domains)
    return tuple(p for p in VALIDATION_PROFILES if p.applies(artifact_type, d, live_service))


def obligations_for(
    artifact_type: ArtifactType,
    domains: Iterable[str],
    *,
    external_action: bool = False,
    live_service: bool = False,
) -> tuple[str, ...]:
    """Ordered obligation ids for one artifact's validation node."""
    items: list[tuple[int, str]] = [(STAGE_ORDER[s], s.value) for s in BASE_OBLIGATIONS]
    producer = next((r for r in ROLE_REGISTRY.values() if artifact_type in r.produces), None)
    if producer is not None and producer.min_evidence:
        items.append((STAGE_ORDER[ValidationStage.PROVENANCE], f"EVIDENCE_FLOOR:{producer.min_evidence}"))
    for profile in applicable_profiles(artifact_type, domains, live_service=live_service):
        items.append((STAGE_ORDER[profile.stage], f"PROFILE:{profile.profile_id}"))
    if external_action:
        items.append((STAGE_ORDER[ValidationStage.AUTHORITY], ValidationStage.AUTHORITY.value))
        items.append((STAGE_ORDER[ValidationStage.TOOL_PROOF], ValidationStage.TOOL_PROOF.value))
    return tuple(obligation for _, obligation in sorted(set(items)))


def volatile_keys_for(obligations: Iterable[str]) -> tuple[str, ...]:
    keys: set[str] = set()
    for ob in obligations:
        if ob.startswith("PROFILE:"):
            keys.update(PROFILES_BY_ID[ob.split(":", 1)[1]].volatile_keys)
    return tuple(sorted(keys))


class ResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ValidationResult(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    node_id: str
    obligation: str
    status: ResultStatus
    validator_ref: str
    attempt: int = 1
    failure_fingerprint: str | None = None


class ValidationVerdict(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    node_id: str
    passed: tuple[str, ...]
    failed: tuple[str, ...]
    pending: tuple[str, ...]
    independence_violations: tuple[str, ...]
    repair_routes: tuple[tuple[str, str], ...]
    escalation: str | None

    @property
    def complete(self) -> bool:
        return not self.failed and not self.pending and not self.independence_violations and self.escalation is None


# Obligation → which causal producer repairs it (spec §30).
_ROUTE_TO_RESEARCH = {"PROVENANCE", "FRESHNESS", "PROFILE:GROUNDING"}
_ROUTE_TO_SECURITY = {"SECURITY", "PROFILE:SECURITY"}
_ROUTE_TO_ASG = {"AUTHORITY"}


def route_failure(obligation: str, node_id: str, graph_nodes: Mapping[str, object]) -> str:
    """Smallest causal producer for a failed obligation."""
    artifact = node_id.split(":", 1)[1] if ":" in node_id else node_id
    producer = f"work:{artifact}"
    if obligation in _ROUTE_TO_RESEARCH or obligation.startswith("EVIDENCE_FLOOR"):
        for candidate in ("work:market_analysis", "work:research_brief"):
            if candidate in graph_nodes:
                return candidate
        return f"evidence:{artifact}"
    if obligation in _ROUTE_TO_SECURITY:
        for candidate in ("work:app_build_spec", "work:implementation_plan"):
            if candidate in graph_nodes:
                return candidate
    if obligation in _ROUTE_TO_ASG:
        return f"asg:{artifact}"
    if obligation == "APPROVAL_SCOPE":
        return f"approval_scope:{artifact}"
    return producer if producer in graph_nodes else node_id


def evaluate_validation(
    node_id: str,
    obligations: Iterable[str],
    results: Iterable[ValidationResult],
    *,
    creator_ref: str,
    risk_level: str,
    graph_nodes: Mapping[str, object],
) -> ValidationVerdict:
    obligations = tuple(obligations)
    latest: dict[str, ValidationResult] = {}
    history: dict[str, list[ValidationResult]] = {}
    for r in sorted((r for r in results if r.node_id == node_id), key=lambda r: (r.obligation, r.attempt)):
        latest[r.obligation] = r
        history.setdefault(r.obligation, []).append(r)

    passed = tuple(o for o in obligations if o in latest and latest[o].status is ResultStatus.PASS)
    failed = tuple(o for o in obligations if o in latest and latest[o].status is ResultStatus.FAIL)
    pending = tuple(o for o in obligations if o not in latest)

    violations: list[str] = []
    if risk_level in {"medium", "high", "critical"}:
        for o in passed:
            if latest[o].validator_ref == creator_ref:
                violations.append(f"CREATOR_SOLE_REVIEWER:{o}")

    escalation = None
    for o in failed:
        attempts = history[o]
        if len(attempts) > MAX_REPAIR_ATTEMPTS:
            escalation = "CIRCUIT_BREAKER"
            break
        fingerprints = [a.failure_fingerprint for a in attempts if a.status is ResultStatus.FAIL and a.failure_fingerprint]
        if len(fingerprints) >= 2 and fingerprints[-1] == fingerprints[-2]:
            escalation = "HUMAN_REVIEW_REQUIRED"
    routes = tuple(sorted((o, route_failure(o, node_id, graph_nodes)) for o in failed))
    return ValidationVerdict(
        node_id=node_id,
        passed=passed,
        failed=failed,
        pending=pending,
        independence_violations=tuple(violations),
        repair_routes=routes,
        escalation=escalation,
    )


def release_blockers(
    *,
    generation_mode: str | None,
    approval_decision: str | None,
    brand_safety_passed: bool | None,
    external_side_effect: bool,
    spend_authorized: bool,
    unmet_hard_dependencies: Iterable[str] = (),
) -> list[str]:
    """Delegate the release decision to N2; return stable guard codes."""
    context = TransitionContext(
        generation_mode=generation_mode,
        approval_exists=approval_decision is not None,
        approval_resolved=approval_decision is not None,
        approval_decision=approval_decision,
        brand_safety_passed=brand_safety_passed,
        external_side_effect=external_side_effect,
        spend_authorized=spend_authorized,
        unmet_hard_dependencies=tuple(unmet_hard_dependencies),
    )
    codes = [f.code for f in release_guard_failures(context)]
    if context.unmet_hard_dependencies:
        codes.append("unmet_hard_dependencies")
    return codes
