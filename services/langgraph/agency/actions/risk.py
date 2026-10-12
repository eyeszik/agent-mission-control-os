"""RiskEngine: deterministic R0–R6 classification with explanations. Pure.

Risk = policy(operation, target, environment, data, cost, reversibility,
audience, blast radius, scope, dependencies). Every class an action earns is
kept: the controls are the UNION over all of them, not only the highest
class's. A caller-requested class can only *raise* the result (I03): risk is
derived on the server from the catalogue entry and server-side facts.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.execution.canonical import canonical_hash

from .vocabulary import (
    CLASS_CONTROLS,
    RISK_POLICY_VERSION,
    Audience,
    Control,
    DataClass,
    Environment,
    OperationKind,
    Reversibility,
    RiskClass,
)

# A mutation touching more resources than this is reviewed as critical (R5).
BULK_MUTATION_THRESHOLD = 25
GOVERNANCE_SCOPE_PREFIXES = ("governance:", "permission:", "policy:", "role:", "credential:")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskFacts(_Strict):
    """Everything the classification reads. Built by the gateway from the
    catalogue entry and server-side lookups; never taken from a client as-is."""

    operation: OperationKind
    environment: Environment
    data_class: DataClass = DataClass.INTERNAL
    cost_minor: int = Field(default=0, ge=0)
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    reversibility: Reversibility = Reversibility.REVERSIBLE
    audience: Audience = Audience.NONE
    external: bool = False
    notifies: bool = False
    blast_radius: int = Field(default=1, ge=0)
    scopes: tuple[str, ...] = ()
    dependents: int = Field(default=0, ge=0)
    requested_class: Optional[RiskClass] = None


class Explanation(_Strict):
    rule: str
    effect: str          # "class:R3" or "control:READ_BACK"
    reason: str


class RiskAssessment(_Strict):
    policy_version: str = RISK_POLICY_VERSION
    classes: tuple[RiskClass, ...]
    effective: RiskClass
    controls: tuple[Control, ...]
    explanations: tuple[Explanation, ...]
    requires_approval: bool
    requires_financial_approval: bool
    requires_step_up: bool
    requires_privileged_review: bool
    live_gated: bool
    facts_hash: str

    @property
    def assessment_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def _governance(scopes: tuple[str, ...]) -> list[str]:
    return sorted(s for s in scopes if s.lower().startswith(GOVERNANCE_SCOPE_PREFIXES))


def assess(facts: RiskFacts) -> RiskAssessment:
    classes: set[RiskClass] = set()
    controls: set[Control] = set()
    why: list[Explanation] = []

    def add(rule: str, cls: RiskClass, reason: str) -> None:
        classes.add(cls)
        why.append(Explanation(rule=rule, effect=f"class:{cls.value}", reason=reason))

    def need(rule: str, control: Control, reason: str) -> None:
        controls.add(control)
        why.append(Explanation(rule=rule, effect=f"control:{control.value}", reason=reason))

    op = facts.operation
    if op is OperationKind.READ:
        add("RK01", RiskClass.R0, "reads information without changing it")
        if facts.data_class.rank >= DataClass.CONFIDENTIAL.rank:
            need("RK09", Control.DATA_ACCESS_CHECK, f"reads {facts.data_class.value.lower()} data")
    if op is OperationKind.CREATE_LOCAL:
        add("RK02", RiskClass.R1, "creates or prepares something inside this system only")
    if op is OperationKind.WRITE_DRAFT or (facts.external and op not in {OperationKind.READ}):
        add("RK03", RiskClass.R2, "writes to a system outside this one")
    if op in {OperationKind.PUBLISH, OperationKind.COMMUNICATE}:
        add("RK04", RiskClass.R3, "makes something visible to an audience or sends a message")
    if facts.audience.rank >= Audience.CLIENT.rank and op is not OperationKind.READ:
        add("RK04a", RiskClass.R3, f"reaches a {facts.audience.value.lower()} audience")
    if facts.notifies:
        add("RK04b", RiskClass.R3, "triggers a notification to people")
    if op is OperationKind.SPEND:
        add("RK05", RiskClass.R4, "commits or changes money")
    if facts.cost_minor > 0:
        add("RK05a", RiskClass.R4, f"has an estimated cost of {facts.cost_minor} minor units {facts.currency or ''}".strip())
    if op in {OperationKind.DELETE, OperationKind.TRANSFER}:
        if facts.reversibility is Reversibility.IRREVERSIBLE or facts.data_class.rank >= DataClass.CONFIDENTIAL.rank \
                or op is OperationKind.TRANSFER:
            add("RK06", RiskClass.R5, "deletes or transfers something that cannot simply be restored")
        else:
            add("RK06a", RiskClass.R2, "removes something recoverable")
    if facts.blast_radius > BULK_MUTATION_THRESHOLD and op is not OperationKind.READ:
        add("RK07", RiskClass.R5, f"affects {facts.blast_radius} resources (over {BULK_MUTATION_THRESHOLD})")
    if op in {OperationKind.PERMISSION_CHANGE, OperationKind.POLICY_CHANGE}:
        add("RK08", RiskClass.R6, "changes who or what may authorise future actions")
    gov = _governance(facts.scopes)
    if gov:
        add("RK08a", RiskClass.R6, f"requests governance scopes {gov}")
    if facts.reversibility is Reversibility.IRREVERSIBLE and op is not OperationKind.READ:
        need("RK10", Control.RECOVERY_ANALYSIS, "the effect cannot be undone")
    if facts.dependents > 0 and op is not OperationKind.READ:
        need("RK11", Control.DEPENDENCY_IMPACT_REVIEW, f"{facts.dependents} downstream item(s) depend on the target")
    if facts.requested_class is not None and facts.requested_class not in classes \
            and facts.requested_class.rank > max((c.rank for c in classes), default=-1):
        add("RK12", facts.requested_class, "the requester asked for stricter handling (a request can raise risk, never lower it)")
    if not classes:  # fail closed: an unclassifiable operation is treated as critical
        add("RK00", RiskClass.R5, "the operation could not be classified")

    for cls in classes:
        controls |= CLASS_CONTROLS[cls]
    effective = max(classes, key=lambda c: c.rank)
    live = facts.environment is Environment.LIVE and effective.rank >= RiskClass.R2.rank
    if facts.environment is Environment.LIVE:
        need("RK13", Control.LIVE_GATE, "LIVE execution is disabled in this deployment")
    ordered = tuple(sorted(classes, key=lambda c: c.rank))
    return RiskAssessment(
        classes=ordered,
        effective=effective,
        controls=tuple(sorted(controls, key=lambda c: c.value)),
        explanations=tuple(why),
        requires_approval=effective.rank >= RiskClass.R3.rank,
        requires_financial_approval=RiskClass.R4 in classes,
        requires_step_up=RiskClass.R5 in classes,
        requires_privileged_review=RiskClass.R6 in classes,
        live_gated=live or facts.environment is Environment.LIVE,
        facts_hash=canonical_hash(facts.model_dump(mode="json")),
    )


__all__ = ["BULK_MUTATION_THRESHOLD", "Explanation", "RiskAssessment", "RiskFacts", "assess"]
