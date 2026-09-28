"""T03/T04 — external evidence architecture, rule promotion and the volatile firewall.

Three authority layers are kept apart (spec §2):

* Layer A ``INDUSTRY_EVIDENCE`` — what sources say organizations do;
* Layer B ``ORGANIZATION_POLICY`` — what this agency adopts;
* Layer C ``RUNTIME_AUTHORITY`` — what AMC code actually permits.

Evidence may flow A → candidate → applicability review → B → C, never A → C.
:func:`evaluate_promotion` is the only path a :class:`RuleCandidate` has
toward C, and it returns a *candidate* status: a rule becomes enforced only by
tested repository code, never by this ledger alone.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel

from .hashing import semantic_hash


class SourceClass(str, Enum):
    PRIMARY_OFFICIAL = "PRIMARY_OFFICIAL"
    PROFESSIONAL_STANDARD = "PROFESSIONAL_STANDARD"
    PRACTITIONER_PATTERN = "PRACTITIONER_PATTERN"
    CASE_STUDY = "CASE_STUDY"
    ACADEMIC = "ACADEMIC"
    VENDOR_DOCUMENTATION = "VENDOR_DOCUMENTATION"
    REPOSITORY_EVIDENCE = "REPOSITORY_EVIDENCE"
    INFERENCE = "INFERENCE"
    PROPOSED_POLICY = "PROPOSED_POLICY"


class RuleStatus(str, Enum):
    SOURCE_CLAIM = "SOURCE_CLAIM"
    VERIFIED_PATTERN = "VERIFIED_PATTERN"
    ORG_POLICY_CANDIDATE = "ORG_POLICY_CANDIDATE"
    RUNTIME_CONSTRAINT_CANDIDATE = "RUNTIME_CONSTRAINT_CANDIDATE"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    GAP = "GAP"
    REJECTED = "REJECTED"


class TargetLayer(str, Enum):
    INDUSTRY_EVIDENCE = "A_INDUSTRY_EVIDENCE"
    ORGANIZATION_POLICY = "B_ORGANIZATION_POLICY"
    RUNTIME_AUTHORITY = "C_RUNTIME_AUTHORITY"


class Volatility(str, Enum):
    STABLE = "STABLE"
    SLOW = "SLOW"
    VOLATILE = "VOLATILE"


class EvidenceStrength(str, Enum):
    NONE = "NONE"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class ClaimLabel(str, Enum):
    FACT = "FACT"
    INDUSTRY_PATTERN = "INDUSTRY_PATTERN"
    SOURCE_SPECIFIC_PRACTICE = "SOURCE_SPECIFIC_PRACTICE"
    INFERENCE = "INFERENCE"
    PROPOSED_AUTOMATION = "PROPOSED_AUTOMATION"
    CONFLICT = "CONFLICT"
    GAP = "GAP"


_FROZEN = {"frozen": True, "extra": "forbid"}


class SourceRecord(BaseModel):
    model_config = _FROZEN

    id: str
    title: str
    canonical_ref: str
    source_type: SourceClass
    publisher: str
    author: str | None = None
    date: str | None = None
    domains: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    departments: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    primary: bool = False
    quality: str | None = None
    claims: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class Claim(BaseModel):
    model_config = _FROZEN

    id: str
    statement: str
    label: ClaimLabel
    source_refs: tuple[str, ...] = ()


# Triangulation categories for high-impact process claims (spec §16).
_TRIANGULATION = {
    "PRIMARY_PROCESS": {SourceClass.PRIMARY_OFFICIAL, SourceClass.REPOSITORY_EVIDENCE},
    "PRACTITIONER_OR_CASE": {SourceClass.PRACTITIONER_PATTERN, SourceClass.CASE_STUDY},
    "STANDARD_OR_TECHNICAL": {
        SourceClass.PROFESSIONAL_STANDARD,
        SourceClass.PRIMARY_OFFICIAL,
        SourceClass.VENDOR_DOCUMENTATION,
        SourceClass.ACADEMIC,
    },
}


def triangulation_deficits(claim: Claim, sources: Iterable[SourceRecord]) -> list[str]:
    """Return missing triangulation categories; non-empty means EVIDENCE_DEFICIT."""
    by_id = {s.id: s for s in sources}
    classes = {by_id[r].source_type for r in claim.source_refs if r in by_id}
    missing = [name for name, allowed in _TRIANGULATION.items() if not (classes & allowed)]
    if claim.source_refs and any(r not in by_id for r in claim.source_refs):
        missing.append("UNRESOLVED_SOURCE_REF")
    return missing


class RuleCandidate(BaseModel):
    model_config = _FROZEN

    id: str
    statement: str
    source_refs: tuple[str, ...] = ()
    source_class: SourceClass
    jurisdiction: str | None = None
    domain: tuple[str, ...] = ()
    applicable_context: tuple[str, ...] = ()
    # ISO-8601 date the claim was last verified against its source.
    freshness: str | None = None
    recheck_at: str | None = None
    organization_specific: bool = False
    volatility: Volatility = Volatility.STABLE
    evidence_strength: EvidenceStrength = EvidenceStrength.WEAK
    conflicts: tuple[str, ...] = ()
    target_layer: TargetLayer = TargetLayer.INDUSTRY_EVIDENCE
    status: RuleStatus = RuleStatus.SOURCE_CLAIM
    # The tested repository location that already enforces this rule, if any.
    runtime_ref: str | None = None


class PromotionContext(BaseModel):
    model_config = _FROZEN

    as_of: str
    applicability_verified: bool = False
    repository_contract_compatible: bool | None = None
    org_policy_approval_ref: str | None = None
    jurisdictions_in_scope: tuple[str, ...] = ()


class PromotionResult(BaseModel):
    model_config = _FROZEN

    rule_id: str
    status: RuleStatus
    effective_layer: TargetLayer
    may_become_executable: bool
    failures: tuple[str, ...]
    result_hash: str


RUNTIME_SUFFICIENT_SOURCES = frozenset(
    {SourceClass.REPOSITORY_EVIDENCE, SourceClass.PRIMARY_OFFICIAL, SourceClass.PROFESSIONAL_STANDARD}
)


def evaluate_promotion(candidate: RuleCandidate, context: PromotionContext) -> PromotionResult:
    """Classify a candidate. Deterministic; never widens authority on its own."""
    failures: list[str] = []
    status = candidate.status

    def done(final: RuleStatus, layer: TargetLayer, executable: bool = False) -> PromotionResult:
        body = {
            "rule_id": candidate.id,
            "status": final.value,
            "effective_layer": layer.value,
            "may_become_executable": executable,
            "failures": sorted(set(failures)),
        }
        return PromotionResult(**body, result_hash=semantic_hash({**body, "candidate": candidate}))

    if status in {RuleStatus.REJECTED, RuleStatus.SUPERSEDED}:
        failures.append(f"TERMINAL_{status.value}")
        return done(status, TargetLayer.INDUSTRY_EVIDENCE)
    if not candidate.source_refs:
        failures.append("NO_SOURCE_REFS")
        return done(RuleStatus.GAP, TargetLayer.INDUSTRY_EVIDENCE)
    if candidate.conflicts:
        failures.append("UNRESOLVED_CONFLICT")
        return done(RuleStatus.CONFLICTED, TargetLayer.INDUSTRY_EVIDENCE)

    freshness_valid = True
    if candidate.volatility is Volatility.VOLATILE:
        if not candidate.freshness:
            failures.append("VOLATILE_NEVER_VERIFIED")
            return done(RuleStatus.GAP, TargetLayer.INDUSTRY_EVIDENCE)
        if not candidate.recheck_at or candidate.recheck_at <= context.as_of:
            failures.append("VOLATILE_RECHECK_EXPIRED")
            return done(RuleStatus.STALE, TargetLayer.INDUSTRY_EVIDENCE)

    source_sufficient = candidate.source_class in RUNTIME_SUFFICIENT_SOURCES
    jurisdiction_valid = candidate.jurisdiction is None or candidate.jurisdiction in context.jurisdictions_in_scope
    repository_compatible = context.repository_contract_compatible is True
    external = candidate.source_class is not SourceClass.REPOSITORY_EVIDENCE
    org_approved = bool(context.org_policy_approval_ref)
    org_needed = external or candidate.organization_specific

    if not context.applicability_verified:
        failures.append("APPLICABILITY_UNVERIFIED")
    if not source_sufficient:
        failures.append("SOURCE_AUTHORITY_INSUFFICIENT_FOR_RUNTIME")
    if not jurisdiction_valid:
        failures.append("JURISDICTION_OUT_OF_SCOPE")
    if not repository_compatible:
        failures.append("REPOSITORY_CONTRACT_UNPROVEN")
    if org_needed and not org_approved:
        failures.append("ORG_POLICY_APPROVAL_REQUIRED")
    if candidate.organization_specific and not org_approved:
        failures.append("ORG_SPECIFIC_NOT_UNIVERSAL")

    executable = (
        context.applicability_verified
        and source_sufficient
        and freshness_valid
        and jurisdiction_valid
        and repository_compatible
        and (org_approved or not org_needed)
    )
    if executable and candidate.target_layer is TargetLayer.RUNTIME_AUTHORITY:
        return done(RuleStatus.RUNTIME_CONSTRAINT_CANDIDATE, TargetLayer.RUNTIME_AUTHORITY, True)
    if context.applicability_verified and candidate.target_layer is not TargetLayer.INDUSTRY_EVIDENCE:
        return done(RuleStatus.ORG_POLICY_CANDIDATE, TargetLayer.ORGANIZATION_POLICY)
    if candidate.evidence_strength in {EvidenceStrength.MODERATE, EvidenceStrength.STRONG} and context.applicability_verified:
        return done(RuleStatus.VERIFIED_PATTERN, TargetLayer.INDUSTRY_EVIDENCE)
    return done(RuleStatus.SOURCE_CLAIM, TargetLayer.INDUSTRY_EVIDENCE)


# --------------------------------------------------------------------------
# Rule-promotion ledger seeded from the specification and repository.
# --------------------------------------------------------------------------
#
# Source refs of the form ``spec:§N`` point at the supplied master execution
# prompt. The external corpus behind its numeric citation markers was not
# supplied, so those practices carry a ``PRACTITIONER_PATTERN`` class and can
# never exceed ORG_POLICY_CANDIDATE without an adoption approval.

SPEC_RULE_CANDIDATES: tuple[RuleCandidate, ...] = (
    RuleCandidate(
        id="rule.degraded_cannot_release",
        statement="FALLBACK_DEGRADED generation cannot reach a client-visible state.",
        source_refs=("repo:services/langgraph/agency/kernel/lifecycle.py#_guard_not_degraded",),
        source_class=SourceClass.REPOSITORY_EVIDENCE,
        evidence_strength=EvidenceStrength.STRONG,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
        runtime_ref="services/langgraph/agency/kernel/lifecycle.py",
    ),
    RuleCandidate(
        id="rule.consequential_requires_exact_approval",
        statement="Irreversible or high-risk work is not execution-ready without an exact approval ref.",
        source_refs=("repo:services/langgraph/agency/role_os/work_order.py",),
        source_class=SourceClass.REPOSITORY_EVIDENCE,
        evidence_strength=EvidenceStrength.STRONG,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
        runtime_ref="services/langgraph/agency/role_os/work_order.py",
    ),
    RuleCandidate(
        id="rule.role_title_grants_no_authority",
        statement="Role seniority/title/source authority labels never grant runtime permission.",
        source_refs=("repo:runtime/role_os/authority_registry.runtime.json", "repo:docs/agency-role-os/source_instruction_dispositions.json#R01"),
        source_class=SourceClass.REPOSITORY_EVIDENCE,
        evidence_strength=EvidenceStrength.STRONG,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
        runtime_ref="runtime/role_os/authority_registry.runtime.json",
    ),
    RuleCandidate(
        id="rule.brand.logo_last",
        statement="Develop strategy and territories before the mark ('logo last').",
        source_refs=("spec:§10", "spec:§11.B"),
        source_class=SourceClass.PRACTITIONER_PATTERN,
        domain=("BRAND",),
        organization_specific=True,
        evidence_strength=EvidenceStrength.MODERATE,
        target_layer=TargetLayer.ORGANIZATION_POLICY,
    ),
    RuleCandidate(
        id="rule.creative.direction_freeze",
        statement="Freeze selected creative direction; changes go through controlled change.",
        source_refs=("spec:§11.C",),
        source_class=SourceClass.PRACTITIONER_PATTERN,
        domain=("BRAND", "CONTENT"),
        organization_specific=True,
        evidence_strength=EvidenceStrength.MODERATE,
        target_layer=TargetLayer.ORGANIZATION_POLICY,
    ),
    RuleCandidate(
        id="rule.media.budget_ratio",
        statement="Fixed production-to-media budget ratios.",
        source_refs=("spec:§11.F",),
        source_class=SourceClass.CASE_STUDY,
        domain=("MEDIA", "VIDEO"),
        organization_specific=True,
        evidence_strength=EvidenceStrength.WEAK,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
    ),
    RuleCandidate(
        id="rule.service.govuk_phases",
        statement="Discovery/Alpha/Beta/Live service phases apply to all digital work.",
        source_refs=("spec:§11.A",),
        source_class=SourceClass.PRIMARY_OFFICIAL,
        domain=("WEB", "SOFTWARE"),
        jurisdiction="GB-public-sector",
        evidence_strength=EvidenceStrength.STRONG,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
    ),
    RuleCandidate(
        id="rule.naming.automated_search_not_clearance",
        statement="Automated availability search is never presented as legal trademark clearance.",
        source_refs=("spec:§11.D",),
        source_class=SourceClass.PROFESSIONAL_STANDARD,
        domain=("BRAND",),
        evidence_strength=EvidenceStrength.STRONG,
        target_layer=TargetLayer.ORGANIZATION_POLICY,
    ),
    RuleCandidate(
        id="rule.app_store.metadata_limits",
        statement="App-store name/description character limits.",
        source_refs=("spec:§32",),
        source_class=SourceClass.PRIMARY_OFFICIAL,
        domain=("MOBILE_APP",),
        volatility=Volatility.VOLATILE,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
    ),
    RuleCandidate(
        id="rule.accessibility.standard_version",
        statement="Accessibility conformance target version.",
        source_refs=("spec:§31", "repo:services/langgraph/agency/ui_ux"),
        source_class=SourceClass.PROFESSIONAL_STANDARD,
        domain=("UX_UI", "WEB"),
        volatility=Volatility.VOLATILE,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
    ),
    RuleCandidate(
        id="rule.security.testing_standard_version",
        statement="Web/software security testing standard version.",
        source_refs=("spec:§31",),
        source_class=SourceClass.PROFESSIONAL_STANDARD,
        domain=("WEB", "SOFTWARE"),
        volatility=Volatility.VOLATILE,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
    ),
    RuleCandidate(
        id="rule.meetings.weekly_status",
        statement="A fixed weekly status meeting cadence is an invariant.",
        source_refs=(),
        source_class=SourceClass.INFERENCE,
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
    ),
    RuleCandidate(
        id="rule.cloudflare.runtime_topology",
        statement="Agency runtime executes on Cloudflare Durable Objects/D1/KV.",
        source_refs=("zip:references/imported_specs/runtime_topology.yaml",),
        source_class=SourceClass.VENDOR_DOCUMENTATION,
        conflicts=("repo:docs/agency-role-os/source_instruction_dispositions.json#R08",),
        target_layer=TargetLayer.RUNTIME_AUTHORITY,
    ),
)


def default_promotion_context(as_of: str) -> PromotionContext:
    """Repository-evidence rules are contract-compatible; nothing is org-adopted."""
    return PromotionContext(as_of=as_of, applicability_verified=True, repository_contract_compatible=True)


def rule_ledger(as_of: str, candidates: Iterable[RuleCandidate] = SPEC_RULE_CANDIDATES) -> dict:
    ctx = default_promotion_context(as_of)
    results = [evaluate_promotion(c, ctx) for c in candidates]
    summary = {
        "candidates": len(results),
        "accepted": sum(1 for r in results if r.status is RuleStatus.RUNTIME_CONSTRAINT_CANDIDATE),
        "rejected": sum(1 for r in results if r.status in {RuleStatus.REJECTED, RuleStatus.CONFLICTED}),
        "stale": sum(1 for r in results if r.status is RuleStatus.STALE),
        "gaps": sum(1 for r in results if r.status is RuleStatus.GAP),
    }
    return {"summary": summary, "results": [r.model_dump(mode="json") for r in results]}


# --------------------------------------------------------------------------
# Volatile requirement firewall (spec §32)
# --------------------------------------------------------------------------


class VolatileVerification(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    EXPIRED = "EXPIRED"


class VolatileConstraint(BaseModel):
    model_config = _FROZEN

    key: str
    source_ref: str | None = None
    retrieved_at: str | None = None
    effective_date: str | None = None
    value: str | None = None
    applicability: tuple[str, ...] = ()
    verification_status: VolatileVerification = VolatileVerification.UNVERIFIED
    expires_or_recheck_at: str | None = None


def volatile_status(constraint: VolatileConstraint, as_of: str) -> VolatileVerification:
    """A value is usable only with a source, a retrieval time and an unexpired recheck."""
    if (
        constraint.verification_status is not VolatileVerification.VERIFIED
        or not constraint.source_ref
        or not constraint.retrieved_at
        or constraint.value is None
    ):
        return VolatileVerification.UNVERIFIED
    if not constraint.expires_or_recheck_at or constraint.expires_or_recheck_at <= as_of:
        return VolatileVerification.EXPIRED
    return VolatileVerification.VERIFIED


def volatile_release_blockers(constraints: Iterable[VolatileConstraint], as_of: str) -> list[str]:
    return sorted(
        f"VOLATILE_{status.value}:{c.key}"
        for c in constraints
        if (status := volatile_status(c, as_of)) is not VolatileVerification.VERIFIED
    )
