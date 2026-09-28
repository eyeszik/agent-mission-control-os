"""T11 — Authority Shadow Graph (ASG) and the RoleOS → N3 AuthorityBridge.

Two different things are bound here and never equated (spec §23):

* the **RoleOS specialist** (one of 1,097 sealed roles) supplies expertise,
  routing and procedure — selected deterministically by exact skill name;
* the **N3 RoleContract** is the runtime permission envelope — which artifacts
  may be produced, whether an external side effect is even possible.

The side-effect ceiling of a :class:`SpecialistBinding` is the *intersection*
of both: RoleOS runtime authority is DENY_CONSEQUENTIAL_BY_DEFAULT for every
role, so no specialist — whatever its title or seniority — lifts a binding
above DRAFT. Consequential work additionally needs an explicit
:class:`AuthorityGrant` satisfying the sealed grant contract plus an exact
approval; missing either is ``AUTHORITY_UNRESOLVED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from pydantic import BaseModel

from services.langgraph.agency.kernel.roles import ROLE_REGISTRY
from services.langgraph.agency.role_os import RoleOSRegistry, RoleResolutionError, RoleResolver

from .hashing import semantic_hash

_FROZEN = {"frozen": True, "extra": "forbid"}

SIDE_EFFECT_RANK = {"PURE": 0, "DRAFT": 1, "REVERSIBLE_WRITE": 2, "IRREVERSIBLE_WRITE": 3}
CONSEQUENTIAL = frozenset({"REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"})


@dataclass(frozen=True)
class SpecialistQuery:
    skill_name: str
    department: str


# N3 runtime role → the sealed RoleOS specialist that carries its expertise.
# Stage-aligned roles reuse the bindings already declared by
# ``role_os/amc_profile.py`` so the compiled plan and the live pipeline agree.
N3_SPECIALISTS: dict[str, SpecialistQuery] = {
    "market_researcher": SpecialistQuery("market-researcher", "strategy"),
    "brand_strategist": SpecialistQuery("brand-strategist", "brand"),
    "brand_architect": SpecialistQuery("brand-architecture-strategist", "brand"),
    "creative_director": SpecialistQuery("creative-director", "creative"),
    "copywriter": SpecialistQuery("copywriter", "creative"),
    "design_lead": SpecialistQuery("art-director", "creative"),
    "product_manager": SpecialistQuery("product-manager", "experience-product"),
    "implementation_lead": SpecialistQuery("engineering-manager", "technology"),
    "growth_lead": SpecialistQuery("creative-producer", "production"),
    "media_planner": SpecialistQuery("media-planner", "growth-media"),
    "analytics_lead": SpecialistQuery("measurement-strategist", "ai-data"),
    "brand_safety_reviewer": SpecialistQuery("qa-engineer", "technology"),
    "release_manager": SpecialistQuery("project-manager", "client-delivery"),
}


class BindingStatus(str, Enum):
    RESOLVED = "RESOLVED"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    AUTHORITY_UNRESOLVED = "AUTHORITY_UNRESOLVED"


class AuthorityGrant(BaseModel):
    """A delegated consequential authority. Fields mirror the sealed grant contract."""

    model_config = _FROZEN

    grant_id: str
    actor_role_id: str
    operation: str
    target: str
    issued_by: str
    expires_at: str


class SpecialistBinding(BaseModel):
    model_config = _FROZEN

    specialist_role_id: str | None
    required_capabilities: tuple[str, ...]
    source_skill_hashes: tuple[str, ...]
    runtime_authority_role_id: str
    permitted_artifacts: tuple[str, ...]
    permitted_tools: tuple[str, ...]
    side_effect_ceiling: str
    approval_requirements: tuple[str, ...]
    segregation_constraints: tuple[str, ...]
    status: BindingStatus
    blockers: tuple[str, ...]
    binding_hash: str


def roleos_ceiling(runtime_authority: Mapping[str, object]) -> str:
    """Highest side-effect class a sealed RoleOS authority block permits."""
    if runtime_authority.get("can_execute_irreversible"):
        return "IRREVERSIBLE_WRITE"
    if runtime_authority.get("can_execute_reversible_external"):
        return "REVERSIBLE_WRITE"
    if runtime_authority.get("can_execute_draft"):
        return "DRAFT"
    if runtime_authority.get("can_execute_pure"):
        return "PURE"
    return "PURE"


def _min_class(a: str, b: str) -> str:
    return a if SIDE_EFFECT_RANK[a] <= SIDE_EFFECT_RANK[b] else b


def grant_contract_failures(grant: AuthorityGrant, *, required_fields: Iterable[str], as_of: str) -> list[str]:
    failures = [f"GRANT_FIELD_MISSING:{f}" for f in required_fields if not getattr(grant, f, None)]
    if grant.expires_at and grant.expires_at <= as_of:
        failures.append("GRANT_EXPIRED")
    if grant.issued_by == grant.actor_role_id:
        failures.append("GRANT_SELF_ISSUED")
    return failures


class AuthorityBridge:
    """Resolve specialist + runtime authority for a work node without inflating either."""

    def __init__(self, registry: RoleOSRegistry, *, source_hashes: Mapping[str, str] | None = None):
        self.registry = registry
        self.resolver = RoleResolver(registry)
        self.source_hashes = dict(source_hashes or {})
        self.grant_contract = registry.authority_registry.get("grant_contract", {})

    def resolve_specialist(self, query: SpecialistQuery) -> str | None:
        """Exact skill-name selection. A partial token overlap is not a specialist."""
        try:
            matches = self.resolver.resolve([query.skill_name], department_hint=query.department, limit=3)
        except RoleResolutionError:
            return None
        for match in matches:
            role = self.registry.get_role(match.role_id)
            if role.skill_name == query.skill_name:
                return role.role_id
        return None

    def bind(
        self,
        *,
        runtime_role_id: str,
        side_effect_class: str,
        operation: str,
        target: str,
        grants: Iterable[AuthorityGrant] = (),
        approval_refs: Iterable[str] = (),
        as_of: str,
        creator_role_id: str | None = None,
    ) -> SpecialistBinding:
        contract = ROLE_REGISTRY.get(runtime_role_id)
        blockers: list[str] = []
        if contract is None:
            blockers.append(f"AUTHORITY_UNRESOLVED:no N3 contract {runtime_role_id}")
        query = N3_SPECIALISTS.get(runtime_role_id)
        specialist_id = self.resolve_specialist(query) if query else None
        if specialist_id is None:
            blockers.append(f"CAPABILITY_GAP:{runtime_role_id}")

        ceiling = "PURE"
        if specialist_id is not None and contract is not None:
            ceiling = roleos_ceiling(self.registry.get_role(specialist_id).runtime_authority)
            # N3 can narrow further; it can only *permit* external effects when declared.
            n3_ceiling = "IRREVERSIBLE_WRITE" if contract.external_side_effect else "DRAFT"
            ceiling = _min_class(ceiling, n3_ceiling)

        approvals = tuple(sorted(set(approval_refs)))
        approval_requirements: list[str] = []
        if contract is not None and contract.requires_human_approval:
            approval_requirements.append("HUMAN_APPROVAL_BEFORE_CLIENT_VISIBLE")

        if side_effect_class in CONSEQUENTIAL:
            approval_requirements.append("EXACT_APPROVAL_REF")
            if contract is None or not contract.external_side_effect:
                blockers.append(f"AUTHORITY_UNRESOLVED:N3 {runtime_role_id} declares no external side effect")
            matching = [
                g for g in grants
                if g.actor_role_id in {runtime_role_id, specialist_id} and g.operation == operation and g.target == target
            ]
            valid = [g for g in matching if not grant_contract_failures(
                g, required_fields=self.grant_contract.get("required", ()), as_of=as_of)]
            if not valid:
                reasons = sorted({f for g in matching for f in grant_contract_failures(
                    g, required_fields=self.grant_contract.get("required", ()), as_of=as_of)})
                blockers.append("AUTHORITY_UNRESOLVED:no valid grant" + (f" ({', '.join(reasons)})" if reasons else ""))
            if self.grant_contract.get("high_consequence_requires_exact_approval_ref", True) and not approvals:
                blockers.append("AUTHORITY_UNRESOLVED:missing exact approval ref")
        elif SIDE_EFFECT_RANK[side_effect_class] > SIDE_EFFECT_RANK[ceiling]:
            blockers.append(f"AUTHORITY_UNRESOLVED:{side_effect_class} exceeds ceiling {ceiling}")

        segregation = ["CREATOR_NOT_SOLE_REVIEWER"]
        if creator_role_id and creator_role_id == runtime_role_id and side_effect_class in CONSEQUENTIAL:
            blockers.append("SEGREGATION_CONFLICT:creator cannot release own work")
        if any(b.startswith("CAPABILITY_GAP") for b in blockers):
            status = BindingStatus.CAPABILITY_GAP
        elif blockers:
            status = BindingStatus.AUTHORITY_UNRESOLVED
        else:
            status = BindingStatus.RESOLVED

        body = {
            "specialist_role_id": specialist_id,
            "required_capabilities": tuple(sorted(c.value for c in contract.capabilities)) if contract else (),
            "source_skill_hashes": tuple(sorted(h for r, h in self.source_hashes.items() if r == specialist_id)),
            "runtime_authority_role_id": runtime_role_id,
            "permitted_artifacts": tuple(sorted(a.value for a in contract.produces)) if contract else (),
            "permitted_tools": ("langgraph.workflow",) if ceiling in {"PURE", "DRAFT"} else (),
            "side_effect_ceiling": ceiling,
            "approval_requirements": tuple(approval_requirements),
            "segregation_constraints": tuple(segregation),
            "status": status,
            "blockers": tuple(sorted(set(blockers))),
        }
        return SpecialistBinding(**body, binding_hash=semantic_hash(body))


class RACI(BaseModel):
    """Responsibility metadata. Deliberately separate from runtime authority (spec §36)."""

    model_config = _FROZEN

    responsible: tuple[str, ...]
    accountable: str | None
    consulted: tuple[str, ...]
    informed: tuple[str, ...]
    runtime_authority: str
    approver: str
    validators: tuple[str, ...]
