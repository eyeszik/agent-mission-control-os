"""ActionRegistry: a typed, versioned catalogue of every action the system knows.

Entries come only from real definitions:

* gateway-owned adapters (``adapters.py``: the sandbox fakes);
* execution-fabric skills (``agency.skills.dispatcher.SKILL_REGISTRY``);
* VNEXUS media providers (``agency.vnexus.media_fabric.REGISTRY``);
* the publication / paid-media integrations and the Project OS scheduler.

Each entry names exactly one ``dispatch_owner`` (I02): the gateway dispatches
only its own entries, and refuses the rest, which keep their existing dispatch
path. The candidate namespaces EXT-001..090 and ART-001..012 have no source
definition anywhere in the repository, so they are reserved as VOID_DETECTED:
looking one up says NOT_IMPLEMENTED and never invents a description.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.execution.canonical import canonical_hash

from .risk import RiskAssessment, RiskFacts, assess
from .vocabulary import (
    Audience,
    DataClass,
    Environment,
    ImplStatus,
    OperationKind,
    RetryClass,
    Reversibility,
)

CATALOG_VERSION = "amc-action-catalog/v1"
RESERVED_NAMESPACES = (
    {"prefix": "EXT", "first": 1, "last": 90},
    {"prefix": "ART", "first": 1, "last": 12},
)
_RESERVED = re.compile(r"^(EXT|ART)-(\d{3})$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskProfile(_Strict):
    """The catalogue's default facts. The gateway combines them with per-request
    server facts; a request can make them stricter, never looser."""

    operation: OperationKind
    external: bool = False
    audience: Audience = Audience.NONE
    reversibility: Reversibility = Reversibility.REVERSIBLE
    data_class: DataClass = DataClass.INTERNAL
    notifies: bool = False
    scopes: tuple[str, ...] = ()


class RetryPolicy(_Strict):
    retry_class: RetryClass
    max_attempts: int = Field(default=3, ge=1, le=3)


class Compensation(_Strict):
    supported: bool = False
    operation: Optional[str] = None


class ActionDescriptor(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    version: str
    title: str
    domain: str
    provider: str
    risk: RiskProfile
    scopes: tuple[str, ...] = ()
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    approval_policy: str
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    timeout_seconds: int = Field(default=30, ge=1, le=3600)
    retry: RetryPolicy
    idempotency: str
    budget: str = "NONE"
    verification: str
    compensation: Compensation = Compensation()
    status: ImplStatus
    live_status: ImplStatus = ImplStatus.LIVE_GATED
    environments: tuple[Environment, ...]
    dispatch_owner: str
    source_ref: str
    status_reasons: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def descriptor_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def nominal_risk(self, environment: Environment = Environment.SANDBOX) -> RiskAssessment:
        return assess(RiskFacts(operation=self.risk.operation, environment=environment, external=self.risk.external,
                                audience=self.risk.audience, reversibility=self.risk.reversibility,
                                data_class=self.risk.data_class, notifies=self.risk.notifies, scopes=self.risk.scopes))


def approval_policy_for(profile: RiskProfile) -> str:
    risk = assess(RiskFacts(operation=profile.operation, environment=Environment.SANDBOX, external=profile.external,
                            audience=profile.audience, reversibility=profile.reversibility, data_class=profile.data_class,
                            notifies=profile.notifies, scopes=profile.scopes))
    parts = []
    if risk.requires_approval:
        parts.append("exact-binding human approval")
    if risk.requires_financial_approval:
        parts.append("separate financial approval")
    if risk.requires_step_up:
        parts.append("step-up authentication + independent approver")
    if risk.requires_privileged_review:
        parts.append("independent privileged review, no self-approval")
    return "; ".join(parts) or f"none beyond tenant scope and autonomy ({risk.effective.value})"


class ReservedLookup(_Strict):
    candidate_id: str
    status: ImplStatus = ImplStatus.NOT_IMPLEMENTED
    namespace_status: ImplStatus = ImplStatus.VOID_DETECTED
    reason: str = ("no source definition for this identifier exists in the repository; it is reserved and will not be "
                   "given an invented description")


class UnknownAction(LookupError):
    """NOT_IMPLEMENTED: the catalogue has no such action."""


class ActionCatalog:
    def __init__(self, descriptors: list[ActionDescriptor]):
        seen: dict[str, ActionDescriptor] = {}
        for d in descriptors:
            if d.id in seen:
                raise ValueError(f"duplicate action id {d.id}")
            seen[d.id] = d
        self._by_id = seen

    def get(self, action_id: str) -> ActionDescriptor:
        match = _RESERVED.match(action_id)
        if match:
            raise UnknownAction(f"NOT_IMPLEMENTED: {action_id} is a reserved candidate id with no source definition")
        found = self._by_id.get(action_id.split("@", 1)[0])
        if found is None:
            raise UnknownAction(f"NOT_IMPLEMENTED: no action {action_id!r} in the catalogue")
        if "@" in action_id and action_id.split("@", 1)[1] != found.version:
            raise UnknownAction(f"NOT_IMPLEMENTED: {action_id} (catalogue has {found.ref})")
        return found

    def reserved(self, candidate_id: str) -> ReservedLookup:
        match = _RESERVED.match(candidate_id)
        if not match:
            raise UnknownAction(f"{candidate_id!r} is not in a reserved namespace")
        prefix, number = match.group(1), int(match.group(2))
        ns = next(n for n in RESERVED_NAMESPACES if n["prefix"] == prefix)
        if not ns["first"] <= number <= ns["last"]:
            raise UnknownAction(f"{candidate_id} is outside {prefix}-{ns['first']:03d}..{ns['last']:03d}")
        return ReservedLookup(candidate_id=candidate_id)

    def all(self) -> list[ActionDescriptor]:
        return [self._by_id[k] for k in sorted(self._by_id)]

    def snapshot(self) -> dict[str, Any]:
        entries = []
        for d in self.all():
            risk = d.nominal_risk()
            entries.append({**d.model_dump(mode="json"), "ref": d.ref, "descriptor_hash": d.descriptor_hash,
                            "nominal_risk": {"classes": [c.value for c in risk.classes], "effective": risk.effective.value,
                                             "controls": [c.value for c in risk.controls]}})
        return {
            "catalog_version": CATALOG_VERSION,
            "entries": entries,
            "reserved_namespaces": [{"namespace": f"{n['prefix']}-{n['first']:03d}..{n['prefix']}-{n['last']:03d}",
                                     "status": ImplStatus.VOID_DETECTED.value,
                                     "reason": "no source definitions in the repository"} for n in RESERVED_NAMESPACES],
            "catalog_hash": canonical_hash([e["descriptor_hash"] for e in entries]),
        }


# --------------------------------------------------------------------------- repository-derived entries


def _fabric_entries() -> list[ActionDescriptor]:
    import services.langgraph.agency.execution_fabric.skills  # noqa: F401  (registers the fabric skills)
    from services.langgraph.agency.skills.dispatcher import SKILL_REGISTRY

    out = []
    for skill in sorted(SKILL_REGISTRY.values(), key=lambda s: s.skill_id):
        available = skill.availability_check() if skill.availability_check else None
        reads_external = skill.skill_id == "zo_ask"
        if skill.provider_requirement and available is not True and skill.provider_requirement not in {"ffprobe"}:
            status, reasons = ImplStatus.PROVIDER_GAP, (f"provider {skill.provider_requirement!r} is not installed",)
        elif skill.provider_requirement == "ffprobe":
            status, reasons = ImplStatus.IMPLEMENTED, ("needs ffprobe on the host; the fabric checks it before dispatch",)
        else:
            status, reasons = ImplStatus.IMPLEMENTED, ()
        profile = RiskProfile(operation=OperationKind.READ if reads_external else OperationKind.CREATE_LOCAL,
                              external=reads_external)
        out.append(ActionDescriptor(
            id=f"fabric.{skill.skill_id}", version="v1", title=skill.description[:120] or skill.skill_id, domain="production",
            provider=skill.provider_requirement or "local", risk=profile,
            input_schema={"owned_by": "execution_fabric work order"}, output_schema={"owned_by": "Project OS artifact"},
            approval_policy=approval_policy_for(profile),
            preconditions=("N3 role holds capability " + skill.capability.value, "fabric eligibility checks pass"),
            postconditions=("artifact persisted, read back and validated by " + (", ".join(skill.validator_ids) or "no validator"),),
            timeout_seconds={"FAST": 5, "STANDARD": 30, "LONG": 300}[skill.timeout_class],
            retry=RetryPolicy(retry_class=RetryClass.RETRY_SAFE), idempotency="fabric execution key (tenant, project, mission, work order, contract, input)",
            verification="storage read-back ObservationReceipt + declared validators", status=status,
            live_status=ImplStatus.UNAVAILABLE if reads_external else ImplStatus.LIVE_GATED,
            environments=(Environment.LOCAL,), dispatch_owner="execution_fabric",
            source_ref="services/langgraph/agency/execution_fabric/skills.py", status_reasons=reasons,
            tests=("services/langgraph/tests/test_execution_fabric.py",),
        ))
    return out


def _vnexus_entries() -> list[ActionDescriptor]:
    from services.langgraph.agency.vnexus.media_fabric import REGISTRY, ProviderStatus

    out = []
    for provider_id in sorted(REGISTRY):
        provider = REGISTRY[provider_id]
        caps = provider.capabilities()
        ident = provider.identify()
        hosted = ident.kind.value == "HOSTED"
        mock = ident.kind.value == "MOCK"
        if caps.status is ProviderStatus.DISABLED:
            status = ImplStatus.PROVIDER_GAP if hosted else ImplStatus.UNAVAILABLE
        elif caps.status is ProviderStatus.AVAILABLE:
            status = ImplStatus.IMPLEMENTED
        else:
            status = ImplStatus.UNAVAILABLE
        profile = RiskProfile(operation=OperationKind.SPEND if hosted else OperationKind.CREATE_LOCAL, external=hosted)
        out.append(ActionDescriptor(
            id=f"vnexus.{provider_id.replace('.', '_')}", version=ident.version or "v1",
            title=ident.description[:120] or provider_id, domain="creative", provider=provider_id, risk=profile,
            input_schema={"owned_by": "vnexus media job MediaRequest"}, output_schema={"owned_by": "vnexus MediaArtifact"},
            approval_policy=approval_policy_for(profile),
            preconditions=("approved brand genome", "provider capability discovered"),
            postconditions=("bytes re-hashed and quality-checked before QC_PASSED",),
            timeout_seconds=min(max(int(caps.timeout_s or 30), 1), 3600),
            retry=RetryPolicy(retry_class=RetryClass.RETRY_SAFE), idempotency="tenant + Idempotency-Key per media job",
            budget="provider estimate; spend approval when non-zero" if hosted else "NONE",
            verification="QC on stored bytes (verify_media / format probes)", status=status,
            live_status=ImplStatus.PROVIDER_GAP if hosted else ImplStatus.LIVE_GATED,
            environments=(Environment.LOCAL,) if not mock else (Environment.SANDBOX,),
            dispatch_owner="vnexus.media_fabric", source_ref="services/langgraph/agency/vnexus/media_fabric.py",
            status_reasons=tuple(b.value if hasattr(b, "value") else str(b) for b in (caps.blockers or ())),
            tests=("services/langgraph/tests/test_vnexus_production.py",),
        ))
    return out


def _integration_entries() -> list[ActionDescriptor]:
    common = dict(version="v1", input_schema={"owned_by": "api/routes/operations.py"}, output_schema={"owned_by": "operations tables"},
                  retry=RetryPolicy(retry_class=RetryClass.NON_RETRYABLE), idempotency="Idempotency-Key on the owning route")
    dry = RiskProfile(operation=OperationKind.CREATE_LOCAL)
    publish = RiskProfile(operation=OperationKind.PUBLISH, external=True, audience=Audience.PUBLIC,
                          reversibility=Reversibility.COMPENSATABLE)
    spend_req = RiskProfile(operation=OperationKind.CREATE_LOCAL)
    spend = RiskProfile(operation=OperationKind.SPEND, external=True, reversibility=Reversibility.COMPENSATABLE)
    return [
        ActionDescriptor(id="publication.dry_run", title="Record a publication dry run (no network call)", domain="distribution",
                         provider="integrations.publication", risk=dry, approval_policy=approval_policy_for(dry),
                         verification="publication_jobs row read back", status=ImplStatus.IMPLEMENTED,
                         environments=(Environment.LOCAL,), dispatch_owner="api.operations",
                         source_ref="services/langgraph/integrations/publication.py", **common),
        ActionDescriptor(id="publication.publish", title="Publish content to a live channel", domain="distribution",
                         provider="integrations.publication", risk=publish, approval_policy=approval_policy_for(publish),
                         verification="none: no live adapter exists", status=ImplStatus.LIVE_GATED,
                         live_status=ImplStatus.NOT_IMPLEMENTED, environments=(Environment.LIVE,),
                         dispatch_owner="none (no live adapter)", source_ref="services/langgraph/integrations/publication.py",
                         status_reasons=("AMC_PUBLICATION_MODE beyond dry_run raises; no reviewed adapter is installed",), **common),
        ActionDescriptor(id="project_os.scheduled_publish", title="Scheduled publication through the outbox", domain="distribution",
                         provider="project_os.scheduler", risk=publish, approval_policy=approval_policy_for(publish),
                         verification="outbox delivery receipt; dry-run provider only", status=ImplStatus.LIVE_GATED,
                         live_status=ImplStatus.NOT_IMPLEMENTED, environments=(Environment.LOCAL,),
                         dispatch_owner="project_os.scheduler", source_ref="services/langgraph/persistence/project_ops.py",
                         status_reasons=("live publication registry ships empty",), **common),
        ActionDescriptor(id="paid_media.request_authorization", title="Record a spend-authorization request (no spend)",
                         domain="marketing", provider="integrations.paid_media", risk=spend_req,
                         approval_policy=approval_policy_for(spend_req), verification="spend_authorizations row read back",
                         status=ImplStatus.IMPLEMENTED, environments=(Environment.LOCAL,), dispatch_owner="api.operations",
                         source_ref="services/langgraph/integrations/paid_media.py", **common),
        ActionDescriptor(id="paid_media.execute_spend", title="Commit paid-media spend", domain="marketing",
                         provider="integrations.paid_media", risk=spend, approval_policy=approval_policy_for(spend),
                         budget="BUDGET_RESERVATION", verification="none: spend_execution_available() is always False",
                         status=ImplStatus.LIVE_GATED, live_status=ImplStatus.NOT_IMPLEMENTED, environments=(Environment.LIVE,),
                         dispatch_owner="none (no live adapter)", source_ref="services/langgraph/integrations/paid_media.py",
                         status_reasons=("spend_execution_available() returns False unconditionally",), **common),
    ]


_CATALOG: Optional[ActionCatalog] = None


def catalog() -> ActionCatalog:
    """The process-wide catalogue (repository entries + gateway adapters)."""
    global _CATALOG
    if _CATALOG is None:
        from .adapters import gateway_descriptors

        _CATALOG = ActionCatalog([*gateway_descriptors(), *_fabric_entries(), *_vnexus_entries(), *_integration_entries()])
    return _CATALOG


def reset_catalog() -> None:
    global _CATALOG
    _CATALOG = None


__all__ = [
    "ActionCatalog", "ActionDescriptor", "CATALOG_VERSION", "Compensation", "RESERVED_NAMESPACES", "ReservedLookup",
    "RetryPolicy", "RiskProfile", "UnknownAction", "approval_policy_for", "catalog", "reset_catalog",
]
