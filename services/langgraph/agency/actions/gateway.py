"""ExecutionGateway: the only dispatch path for actions the gateway owns.

Sequence for one action (every arrow is a persisted, hash-chained transition):

    propose:  PROPOSED → VALIDATED → PREPARED → (AWAITING_APPROVAL | AUTHORIZED | BLOCKED)
    settle:   AWAITING_APPROVAL → (AUTHORIZED | REJECTED | EXPIRED | BLOCKED)
    dispatch: preflight → [RESERVED] → DISPATCHING (lease; persisted *before* the effect)
              → effect → OBSERVING (receipt persisted) → read-back → VERIFIED → COMPLETED
    timeout:  DISPATCHING/OBSERVING → UNKNOWN → RECONCILING → VERIFIED | FAILED | NEEDS_HUMAN

The preflight re-derives every fact right before dispatch. A change to any of
the following blocks the action (E05/E11/I06/I07):

* identity and project ownership;
* freezes;
* the LIVE gate;
* expiry;
* the policy version;
* the catalogue entry;
* dependency heads;
* approvals.

Delivery is at-least-once: a retry reuses the same effect key, and the
provider dedupes on it. Exactly-once is not claimed.

Nothing here runs inside a LangGraph node. A node is re-executed from its
start on resume (langgraph 1.2.11, ``langgraph.types.interrupt`` docstring),
so a side effect there would repeat; ``test_ace12_*`` enforces the separation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import actions as db
from services.langgraph.security.auth import Principal

from . import broker
from .adapters import (
    ActionAdapter,
    AdapterError,
    ArgsInvalid,
    CompensationUnsupported,
    EffectContext,
    Observation,
    OutcomeUnknown,
    PermanentFailure,
    ToolUnavailable,
    TransientBeforeEffect,
    get_adapter,
)
from .catalog import ActionDescriptor, UnknownAction, catalog
from .fsm import MAX_ATTEMPTS, ActionState
from .governance import autonomy, freeze_reasons, live_enablement
from .models import ApprovalBinding, binding_diff, effect_key
from .risk import RiskAssessment, RiskFacts, assess
from .safety import UnsafeInput, assert_no_secrets, injection_flags, redacted
from .vocabulary import (
    RISK_POLICY_VERSION,
    STATUS_LABELS,
    AutonomyLevel,
    DataClass,
    Environment,
    RiskClass,
)

GATEWAY_OWNER = "actions.gateway"
MAX_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_TTL_SECONDS = 24 * 3600
LEASE_SLACK_SECONDS = 60
MAX_RECONCILE_ATTEMPTS = 3


class GatewayError(ValueError):
    status = 409

    def __init__(self, code: str, detail: str = "", *, details: Optional[dict] = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.details = details or {}


class LiveGated(GatewayError):
    status = 409


class Frozen(GatewayError):
    status = 423


class NotDispatchable(GatewayError):
    status = 409


class InvalidRequest(GatewayError):
    status = 422


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _trust_decision(row: dict, *, stage: str, effect: str, required: tuple[str, ...] = (), evidence: tuple[str, ...] = ()) -> None:
    """Record the policy decision in the existing trust kernel (audit chain)."""
    from services.langgraph.agency.reliability import PolicyEffect
    from services.langgraph.app.runtime_support import trust_kernel

    trust = trust_kernel()
    trust.bind_project(tenant_id=row["tenant_id"], project_id=row["project_id"])
    trust.record_policy_decision(
        tenant_id=row["tenant_id"], project_id=row["project_id"],
        decision_id=f"action-{row['action_id']}-{stage}-v{row['version']}", subject_ref=row["action_id"],
        action=f"action.{stage}", target=row["target_ref"], policy_version=RISK_POLICY_VERSION,
        policy_input={"binding_hash": row["binding_hash"], "state": row["state"], "risk_hash": row["risk_hash"]},
        effect=PolicyEffect(effect), required_authority_refs=required, evidence_refs=evidence)


def _move(row: dict, to: ActionState, *, actor: str, reason: str, evidence: Optional[dict] = None,
          updates: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    return db.transition(row["action_id"], expected_version=row["version"], expected_states=(row["state"],), to_state=to.value,
                         actor=actor, reason=reason, evidence=evidence or {}, updates=updates, now=now)


def _ctx(row: dict) -> EffectContext:
    return EffectContext(tenant_id=row["tenant_id"], project_id=row["project_id"], action_id=row["action_id"],
                         effect_key=effect_key(tenant_id=row["tenant_id"], capability_ref=row["binding"]["capability_ref"],
                                               target_ref=row["target_ref"], payload_hash=row["payload_hash"],
                                               idempotency_key=row["idempotency_key"]),
                         environment=Environment(row["environment"]), target_ref=row["target_ref"], payload_hash=row["payload_hash"])


def _adapter_for(descriptor: ActionDescriptor) -> ActionAdapter:
    if descriptor.dispatch_owner != GATEWAY_OWNER:
        raise NotDispatchable("NOT_GATEWAY_OWNED", f"{descriptor.id} is dispatched by {descriptor.dispatch_owner}")
    adapter = get_adapter(descriptor.id)
    if adapter is None:
        raise NotDispatchable("ADAPTER_MISSING", descriptor.id)
    return adapter


def _facts(descriptor: ActionDescriptor, adapter: ActionAdapter, args: Any, environment: Environment,
           requested_class: Optional[RiskClass], data_class: Optional[DataClass]) -> tuple[RiskFacts, Any]:
    est = adapter.estimate(args)
    rf = adapter.request_facts(args)
    profile = descriptor.risk
    worst_data = max([profile.data_class, rf.data_class or profile.data_class, data_class or profile.data_class],
                     key=lambda d: d.rank)
    audience = max([profile.audience, rf.audience or profile.audience], key=lambda a: a.rank)
    facts = RiskFacts(operation=profile.operation, environment=environment, data_class=worst_data, cost_minor=est.amount_minor,
                      currency=est.currency, reversibility=profile.reversibility, audience=audience, external=profile.external,
                      notifies=profile.notifies or rf.notifies, blast_radius=rf.blast_radius,
                      scopes=tuple(sorted({*profile.scopes, *rf.scopes})), requested_class=requested_class)
    return facts, est


def _binding(*, descriptor: ActionDescriptor, tenant_id: str, project_id: str, environment: Environment, target_ref: str,
             payload_hash: str, deps: tuple[tuple[str, str], ...], risk: RiskAssessment, cost: Any, expires_at: str,
             subjects: list[str]) -> tuple[ApprovalBinding, dict]:
    b = ApprovalBinding(capability_ref=descriptor.ref, descriptor_hash=descriptor.descriptor_hash, tenant_id=tenant_id,
                        project_id=project_id, environment=environment, target_ref=target_ref, payload_hash=payload_hash,
                        dependency_hashes=deps, policy_version=RISK_POLICY_VERSION, effective_class=risk.effective.value,
                        cost_minor=cost.amount_minor, currency=cost.currency, expires_at=expires_at)
    doc = {**b.model_dump(mode="json"), "approval_subjects": subjects}
    return b, doc


def _binding_hash(doc: dict) -> str:
    return canonical_hash(doc)


# --------------------------------------------------------------------------- preview / shadow dispatch


def _plan(principal: Principal, *, capability_id: str, project_id: str, environment: str, args: dict, dependency_refs: tuple[str, ...],
          requested_class: Optional[str], data_class: Optional[str], ttl_seconds: int, now: datetime) -> dict:
    descriptor = catalog().get(capability_id)  # UnknownAction -> 404 NOT_IMPLEMENTED
    try:
        env = Environment(environment)
    except ValueError as exc:
        raise InvalidRequest("UNKNOWN_ENVIRONMENT", environment) from exc
    broker.authorize_scope(principal, project_id, write=True)
    if env is Environment.LIVE:
        raise LiveGated("LIVE_GATED", "LIVE execution is disabled", details=live_enablement())
    adapter = _adapter_for(descriptor)
    if env not in descriptor.environments:
        raise InvalidRequest("ENVIRONMENT_NOT_SUPPORTED", f"{descriptor.id} runs in {[e.value for e in descriptor.environments]}")
    try:
        assert_no_secrets(args)
    except UnsafeInput as exc:
        raise InvalidRequest(exc.code, str(exc)) from exc
    try:
        validated = adapter.validate(args)
    except ArgsInvalid as exc:
        raise InvalidRequest("ARGS_INVALID", exc.detail) from exc
    try:
        deps = broker.resolve_dependencies(project_id, dependency_refs)
    except broker.DependencyInvalid as exc:
        raise InvalidRequest("DEPENDENCY_INVALID", str(exc)) from exc
    try:
        req_cls = RiskClass(requested_class) if requested_class else None
        dclass = DataClass(data_class) if data_class else None
    except ValueError as exc:
        raise InvalidRequest("UNKNOWN_CLASSIFICATION", str(exc)) from exc
    facts, cost = _facts(descriptor, adapter, validated, env, req_cls, dclass)
    risk = assess(facts)
    level = autonomy(project_id)
    auto_ok = risk.effective.rank <= level.auto_ceiling.rank and not risk.requires_approval
    blockers: list[str] = []
    if risk.requires_step_up:
        blockers.append("STEP_UP_UNAVAILABLE: step-up authentication is not implemented in this deployment")
    if not auto_ok and level is not AutonomyLevel.REQUEST_APPROVAL:
        blockers.append(f"AUTONOMY_CEILING: this project allows up to {level.auto_ceiling.value} without a person "
                        f"({level.value}); raise it to REQUEST_APPROVAL to ask for approval")
    subjects = [] if (auto_ok or blockers) else broker.required_subjects(risk, needs_execution_approval=True)
    ttl = max(60, min(int(ttl_seconds), MAX_TTL_SECONDS))
    expires = db.iso(now + timedelta(seconds=ttl))
    target_ref = adapter.target_ref(validated)
    payload = validated.model_dump(mode="json")
    payload_hash = canonical_hash(payload)
    binding, doc = _binding(descriptor=descriptor, tenant_id=principal.tenant_id, project_id=project_id, environment=env,
                            target_ref=target_ref, payload_hash=payload_hash, deps=deps, risk=risk, cost=cost, expires_at=expires,
                            subjects=subjects)
    return {"descriptor": descriptor, "adapter": adapter, "validated": validated, "payload": payload, "env": env, "deps": deps,
            "facts": facts, "risk": risk, "cost": cost, "autonomy": level, "auto_ok": auto_ok, "blockers": blockers,
            "subjects": subjects, "expires": expires, "target_ref": target_ref, "payload_hash": payload_hash,
            "binding": binding, "binding_doc": doc, "binding_hash": _binding_hash(doc), "flags": injection_flags(args),
            "dependency_refs": tuple(sorted(set(dependency_refs))), "ttl": ttl}


def preview(principal: Principal, *, capability_id: str, project_id: str, environment: str, args: dict,
            dependency_refs: tuple[str, ...] = (), requested_class: Optional[str] = None, data_class: Optional[str] = None,
            ttl_seconds: int = DEFAULT_TTL_SECONDS, now: Optional[datetime] = None) -> dict:
    """Zero-surprise preview and shadow dispatch: the full policy and routing
    decision with nothing persisted and nothing dispatched."""
    moment = _now(now)
    p = _plan(principal, capability_id=capability_id, project_id=project_id, environment=environment, args=args,
              dependency_refs=dependency_refs, requested_class=requested_class, data_class=data_class,
              ttl_seconds=ttl_seconds, now=moment)
    risk: RiskAssessment = p["risk"]
    frozen = freeze_reasons(principal.tenant_id, project_id)
    budget = None
    if risk.requires_financial_approval:
        budget = budget_headroom(principal.tenant_id, project_id, p["cost"].currency, now=moment)
    if p["blockers"]:
        outcome = "WOULD_BE_BLOCKED"
    elif p["auto_ok"]:
        outcome = "WOULD_RUN_WITHOUT_APPROVAL"
    else:
        outcome = "WOULD_REQUEST_APPROVAL"
    d: ActionDescriptor = p["descriptor"]
    return {
        "shadow": True, "label": "PREVIEW: nothing was persisted or dispatched", "outcome": outcome,
        "capability": {"id": d.id, "ref": d.ref, "title": d.title, "status": d.status.value, "live_status": d.live_status.value,
                       "dispatch_owner": d.dispatch_owner, "adapter": type(p["adapter"]).__name__},
        "environment": p["env"].value, "target_ref": p["target_ref"], "payload_hash": p["payload_hash"],
        "risk": _risk_view(risk), "effect": d.risk.operation.value, "reversibility": d.risk.reversibility.value,
        "compensation": d.compensation.model_dump(mode="json"),
        "cost": p["cost"].model_dump(mode="json"), "approvals_required": p["subjects"], "blockers": p["blockers"],
        "autonomy": p["autonomy"].value, "frozen": frozen, "live": live_enablement(), "budget": budget,
        "dependencies": [list(x) for x in p["deps"]], "injection_flags": list(p["flags"]),
        "binding_hash": p["binding_hash"], "expires_at": p["expires"],
    }


def _risk_view(risk: RiskAssessment) -> dict:
    return {"classes": [c.value for c in risk.classes], "effective": risk.effective.value,
            "controls": [c.value for c in risk.controls],
            "explanations": [e.model_dump(mode="json") for e in risk.explanations], "policy_version": risk.policy_version,
            "requires_approval": risk.requires_approval, "requires_financial_approval": risk.requires_financial_approval,
            "requires_step_up": risk.requires_step_up, "requires_privileged_review": risk.requires_privileged_review,
            "live_gated": risk.live_gated}


# --------------------------------------------------------------------------- propose


def propose(principal: Principal, *, capability_id: str, project_id: str, environment: str, args: dict, idempotency_key: str,
            dependency_refs: tuple[str, ...] = (), requested_class: Optional[str] = None, data_class: Optional[str] = None,
            correlation_id: Optional[str] = None, ttl_seconds: int = DEFAULT_TTL_SECONDS,
            now: Optional[datetime] = None) -> tuple[dict, bool]:
    moment = _now(now)
    if not idempotency_key or len(idempotency_key) < 8 or len(idempotency_key) > 200:
        raise InvalidRequest("IDEMPOTENCY_KEY_REQUIRED", "8 to 200 characters")
    p = _plan(principal, capability_id=capability_id, project_id=project_id, environment=environment, args=args,
              dependency_refs=dependency_refs, requested_class=requested_class, data_class=data_class,
              ttl_seconds=ttl_seconds, now=moment)
    descriptor: ActionDescriptor = p["descriptor"]
    risk: RiskAssessment = p["risk"]
    request_hash = canonical_hash({"capability": descriptor.ref, "project": project_id, "environment": p["env"].value,
                                   "payload": p["payload_hash"], "dependency_refs": list(p["dependency_refs"]),
                                   "requested_class": requested_class, "data_class": data_class, "ttl": p["ttl"]})
    existing = db.find_by_key(principal.tenant_id, idempotency_key)
    if existing is not None:
        if existing["request_hash"] != request_hash:
            raise GatewayError("IDEMPOTENCY_KEY_REUSED", "the key was already used for a different request")
        return existing, False
    from services.langgraph.persistence.actions import client_for_project

    action_id = "act-" + canonical_hash({"tenant": principal.tenant_id, "key": idempotency_key})[:32]
    client_id = client_for_project(project_id)
    correlation = correlation_id or action_id
    context_hash = canonical_hash({"tenant": principal.tenant_id, "project": project_id, "client": client_id,
                                   "actor": principal.user_id, "environment": p["env"].value, "policy": RISK_POLICY_VERSION,
                                   "descriptor": descriptor.descriptor_hash, "correlation": correlation})
    stamp = db.iso(moment)
    row = {
        "action_id": action_id, "tenant_id": principal.tenant_id, "project_id": project_id, "client_id": client_id,
        "capability_id": descriptor.id, "capability_version": descriptor.version, "environment": p["env"].value,
        "actor_ref": principal.user_id, "target_ref": p["target_ref"], "args": p["payload"],
        "args_hash": canonical_hash(args), "payload_hash": p["payload_hash"], "context_hash": context_hash,
        "dependency_hashes": [list(x) for x in p["deps"]], "policy_version": RISK_POLICY_VERSION,
        "risk": {**_risk_view(risk), "facts": p["facts"].model_dump(mode="json"), "autonomy": p["autonomy"].value},
        "risk_hash": risk.assessment_hash, "effective_class": risk.effective.value, "binding": p["binding_doc"],
        "binding_hash": p["binding_hash"], "run_id": None, "approval_id": None, "financial_approval_id": None,
        "budget_reservation_id": None, "idempotency_key": idempotency_key, "request_hash": request_hash,
        "correlation_id": correlation, "state": ActionState.PROPOSED.value, "version": 1, "attempts": 0,
        "reconcile_attempts": 0, "lease_owner": None, "lease_expires_at": None, "retry_eligible": False, "reasons": [],
        "outcome": None, "injection_flags": list(p["flags"]), "created_at": stamp, "updated_at": stamp, "expires_at": p["expires"],
    }
    try:
        row, created = db.insert_request(row, actor=principal.user_id, reason="proposed",
                                         evidence={"binding_hash": p["binding_hash"], "risk": risk.effective.value})
    except db.ActionConflict as exc:
        raise GatewayError("IDEMPOTENCY_KEY_REUSED", str(exc)) from exc
    if not created:
        return row, False
    actor = principal.user_id
    row = _move(row, ActionState.VALIDATED, actor=actor, reason="args, scope, secrets and dependencies validated",
                evidence={"injection_flags": list(p["flags"]), "dependencies": [list(x) for x in p["deps"]]}, now=moment)
    prepared = p["adapter"].prepare(_ctx(row), p["validated"])
    row = _move(row, ActionState.PREPARED, actor=actor, reason="effect plan prepared",
                evidence={"plan": prepared.plan, "expected": prepared.expected}, now=moment)
    needs_approval = bool(p["subjects"])
    run_id = broker.open_anchor_run(principal, action_id=action_id, tenant_id=principal.tenant_id, project_id=project_id,
                                    needs_approval=needs_approval, binding_hash=p["binding_hash"])
    if p["blockers"]:
        row = _move(row, ActionState.BLOCKED, actor=actor, reason=p["blockers"][0], updates={"run_id": run_id, "reasons": p["blockers"]},
                    now=moment)
        _trust_decision(row, stage="propose", effect="DENY", evidence=tuple(p["blockers"]))
        return row, True
    if needs_approval:
        ids = broker.open_approvals(principal, run_id=run_id, action_id=action_id, tenant_id=principal.tenant_id,
                                    project_id=project_id, subjects=p["subjects"], binding_hash=p["binding_hash"],
                                    title=f"{descriptor.title} → {p['target_ref']}")
        row = _move(row, ActionState.AWAITING_APPROVAL, actor=actor, reason="human approval required",
                    evidence={"approvals": ids}, updates={"run_id": run_id, "approval_id": ids.get(broker.SUBJECT_EXECUTION),
                                                          "financial_approval_id": ids.get(broker.SUBJECT_SPEND)}, now=moment)
        _trust_decision(row, stage="propose", effect="REQUIRE_APPROVAL", required=tuple(sorted(ids.values())))
        return row, True
    row = _move(row, ActionState.AUTHORIZED, actor=actor,
                reason=f"within autonomy {p['autonomy'].value} (≤ {p['autonomy'].auto_ceiling.value}); no approval required",
                updates={"run_id": run_id}, now=moment)
    _trust_decision(row, stage="propose", effect="ALLOW")
    return row, True


# --------------------------------------------------------------------------- settle / cancel / expire


def _release_budget(row: dict, status: str, reason: str) -> None:
    if row.get("budget_reservation_id"):
        r = db.get_reservation(row["budget_reservation_id"])
        if r is not None and r["status"] == "RESERVED":
            db.settle_reservation(r["reservation_id"], status=status, evidence={"reason": reason})


def settle(action_id: str, *, actor: str = "system:gateway", now: Optional[datetime] = None) -> dict:
    """Apply decisions made at /approvals/{id}/decide. Holds no authority itself."""
    moment = _now(now)
    row = db.get_request(action_id)
    if row is None:
        raise LookupError("action not found")
    if row["state"] != ActionState.AWAITING_APPROVAL.value:
        return row
    check = broker.check_approvals(row, now=moment)
    if check.rejected:
        row = _move(row, ActionState.REJECTED, actor=actor, reason="an approver rejected the action",
                    evidence={"approvals": list(check.approvals)}, updates={"reasons": list(check.reasons)}, now=moment)
        broker.stale_open_approvals(row, "action rejected by another approver")
        return row
    if check.expired:
        row = _move(row, ActionState.EXPIRED, actor=actor, reason="approval window expired",
                    evidence={"approvals": list(check.approvals)}, updates={"reasons": list(check.reasons)}, now=moment)
        broker.stale_open_approvals(row, "action expired")
        return row
    if check.stale or any(r.endswith(("SELF_APPROVAL", "SCOPE_MISMATCH", "APPROVAL_MISSING")) for r in check.reasons):
        row = _move(row, ActionState.BLOCKED, actor=actor, reason="approval no longer matches this action",
                    evidence={"approvals": list(check.approvals)}, updates={"reasons": list(check.reasons)}, now=moment)
        broker.stale_open_approvals(row, "approval no longer matches")
        return row
    if check.satisfied:
        row = _move(row, ActionState.AUTHORIZED, actor=actor, reason="every required approval matches the exact binding",
                    evidence={"approvals": list(check.approvals)}, now=moment)
    elif not check.pending:
        # Every approval is decided, yet together they do not authorize this action
        # (e.g. one person supplied two of them): it can never become valid.
        row = _move(row, ActionState.BLOCKED, actor=actor, reason="the decided approvals do not satisfy the policy",
                    evidence={"approvals": list(check.approvals)}, updates={"reasons": list(check.reasons)}, now=moment)
    return row


def cancel(principal: Principal, action_id: str, *, reason: str, now: Optional[datetime] = None) -> dict:
    row = broker.visible(principal, db.get_request(action_id))
    broker.authorize_scope(principal, row["project_id"], write=True)
    pre = {ActionState.PROPOSED.value, ActionState.VALIDATED.value, ActionState.PREPARED.value, ActionState.AWAITING_APPROVAL.value,
           ActionState.AUTHORIZED.value, ActionState.RESERVED.value}
    if row["state"] not in pre:
        raise NotDispatchable("NOT_CANCELLABLE", f"an action in {row['state']} can no longer be cancelled")
    _release_budget(row, "RELEASED", "cancelled")
    row = _move(row, ActionState.CANCELLED, actor=principal.user_id, reason=reason or "cancelled", now=_now(now))
    broker.stale_open_approvals(row, "action cancelled")
    return row


def expire_due(tenant_id: str, *, now: Optional[datetime] = None) -> list[str]:
    moment = _now(now)
    pre = (ActionState.PREPARED.value, ActionState.AWAITING_APPROVAL.value, ActionState.AUTHORIZED.value, ActionState.RESERVED.value)
    out = []
    for row in db.expiring_before(tenant_id, moment, pre):
        try:
            _release_budget(row, "EXPIRED", "action expired")
            row = _move(row, ActionState.EXPIRED, actor="system:gateway", reason="expired before dispatch", now=moment)
            broker.stale_open_approvals(row, "action expired")
            out.append(row["action_id"])
        except db.ActionConflict:
            continue
    return out


# --------------------------------------------------------------------------- dispatch


def preflight(row: dict, *, now: datetime) -> tuple[list[str], list[str]]:
    """Re-derive every fact. Returns (hold_reasons, block_reasons).

    Hold reasons refuse this dispatch but leave the action as it is (a freeze or
    a lowered autonomy can be lifted). Block reasons end the action: its binding
    or approvals no longer describe what would happen."""
    hold, block = [], []
    hold += freeze_reasons(row["tenant_id"], row["project_id"])
    if row["environment"] == Environment.LIVE.value:
        block.append("LIVE_GATED")
    if broker._past(now, row["expires_at"]):
        block.append("ACTION_EXPIRED")
    if row["policy_version"] != RISK_POLICY_VERSION:
        block.append(f"POLICY_CHANGED: approved under {row['policy_version']}, current {RISK_POLICY_VERSION}")
    try:
        descriptor = catalog().get(row["capability_id"])
        if descriptor.ref != row["binding"]["capability_ref"] or descriptor.descriptor_hash != row["binding"]["descriptor_hash"]:
            block.append("CAPABILITY_CHANGED: the catalogue entry changed since the action was bound")
    except UnknownAction:
        block.append("CAPABILITY_REMOVED")
    current = broker.current_dependencies(row["project_id"], row["dependency_hashes"])
    if [list(x) for x in current] != [list(x) for x in row["dependency_hashes"]]:
        block.append("DEPENDENCY_DRIFT: a dependency changed since the action was bound")
    subjects = row["binding"].get("approval_subjects") or []
    if subjects:
        check = broker.check_approvals(row, now=now)
        if not check.satisfied:
            block += [f"APPROVAL:{r}" for r in check.reasons] or [f"APPROVAL_PENDING:{p}" for p in check.pending]
    else:
        level = autonomy(row["project_id"])
        if RiskClass(row["effective_class"]).rank > level.auto_ceiling.rank:
            hold.append(f"AUTONOMY_CEILING_LOWERED: {level.value} now allows up to {level.auto_ceiling.value}")
    if row["risk"].get("requires_step_up"):
        block.append("STEP_UP_UNAVAILABLE")
    return hold, block


def budget_headroom(tenant_id: str, project_id: str, currency: Optional[str], *, now: datetime) -> dict:
    from services.langgraph.persistence.actions import _applicable, client_for_project, list_budget_policies, list_reservations

    if not currency:
        return {"currency": None, "policies": [], "note": "no cost"}
    client_id = client_for_project(project_id)
    policies = [p for p in list_budget_policies(tenant_id) if p["currency"] == currency]
    applicable = _applicable(policies, tenant_id=tenant_id, project_id=project_id, client_id=client_id)
    active = [r for r in list_reservations(tenant_id, statuses=("RESERVED", "COMMITTED")) if r["currency"] == currency]
    out = []
    for p in applicable:
        kind = p["scope_kind"]

        def match(r: dict) -> bool:
            if kind == "PROJECT":
                return r["project_id"] == project_id
            if kind == "CLIENT":
                return r.get("client_id") == client_id
            if kind == "TENANT_DAY":
                return r["created_at"] >= db.iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
            if kind == "TENANT_MONTH":
                return r["created_at"] >= db.iso(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
            return False

        used = sum(int(r["committed_minor"] if r["status"] == "COMMITTED" and r["committed_minor"] is not None else r["amount_minor"])
                   for r in active if match(r))
        out.append({"scope_kind": kind, "scope_ref": p["scope_ref"], "ceiling_minor": int(p["ceiling_minor"]), "used_minor": used,
                    "headroom_minor": max(int(p["ceiling_minor"]) - used, 0)})
    return {"currency": currency, "policies": out, "fail_closed": not out}


def dispatch(principal: Principal, action_id: str, *, worker_id: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    moment = _now(now)
    row = broker.visible(principal, db.get_request(action_id))
    broker.authorize_scope(principal, row["project_id"], write=True)
    if row["state"] == ActionState.AWAITING_APPROVAL.value:
        row = settle(action_id, now=moment)
    if row["state"] not in {ActionState.AUTHORIZED.value, ActionState.RESERVED.value}:
        raise NotDispatchable("NOT_DISPATCHABLE", f"action is {row['state']}",
                              details={"state": row["state"], "label": STATUS_LABELS.get(row["state"], row["state"])})
    descriptor = catalog().get(row["capability_id"])
    adapter = _adapter_for(descriptor)
    hold, block = preflight(row, now=moment)
    if hold:
        if any(h.startswith(("SYSTEM_FROZEN", "TENANT_FROZEN", "PROJECT_FROZEN")) for h in hold):
            raise Frozen("DISPATCH_FROZEN", "; ".join(hold), details={"reasons": hold})
        raise NotDispatchable("HELD", "; ".join(hold), details={"reasons": hold})
    if block:
        _release_budget(row, "RELEASED", "blocked at preflight")
        row = _move(row, ActionState.EXPIRED if block == ["ACTION_EXPIRED"] else ActionState.BLOCKED, actor=principal.user_id,
                    reason=block[0], updates={"reasons": block}, now=moment)
        broker.stale_open_approvals(row, f"blocked at dispatch: {block[0]}")
        return row
    if RiskClass.R4.value in row["risk"]["classes"] and row["state"] == ActionState.AUTHORIZED.value:
        binding = row["binding"]
        try:
            res = db.reserve_budget(tenant_id=row["tenant_id"], project_id=row["project_id"], client_id=row.get("client_id"),
                                    action_id=action_id, currency=binding["currency"], amount_minor=int(binding["cost_minor"]),
                                    expires_at=min(datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")),
                                                   moment + timedelta(hours=1)), now=moment)
        except db.BudgetExceeded as exc:
            row = _move(row, ActionState.BLOCKED, actor=principal.user_id, reason=exc.code,
                        evidence={"budget": exc.details}, updates={"reasons": [exc.code]}, now=moment)
            return row
        row = _move(row, ActionState.RESERVED, actor=principal.user_id, reason="budget reserved",
                    evidence={"reservation_id": res["reservation_id"], "amount_minor": res["amount_minor"],
                              "currency": res["currency"]},
                    updates={"budget_reservation_id": res["reservation_id"]}, now=moment)
    worker = worker_id or f"api:{principal.user_id}"
    lease_until = db.iso(moment + timedelta(seconds=descriptor.timeout_seconds * 2 + LEASE_SLACK_SECONDS))
    try:
        row = _move(row, ActionState.DISPATCHING, actor=principal.user_id, reason="lease taken; intent persisted before the effect",
                    evidence={"worker": worker, "effect_key": _ctx(row).effect_key},
                    updates={"lease_owner": worker, "lease_expires_at": lease_until, "attempts": int(row["attempts"]) + 1},
                    now=moment)
    except db.ActionConflict as exc:
        raise NotDispatchable("ALREADY_DISPATCHING", str(exc)) from exc
    _trust_decision(row, stage="dispatch", effect="ALLOW", evidence=(f"lease:{worker}",))
    _record_permit(row, moment)
    return _execute_and_observe(row, adapter, actor=principal.user_id, now=moment)


def _record_permit(row: dict, moment: datetime) -> None:
    from services.langgraph.agency.execution.models import DispatchPermit
    from services.langgraph.persistence.proofs import put_dispatch_permit

    approvals = tuple(sorted(a for a in (row.get("approval_id"), row.get("financial_approval_id")) if a))
    permit = DispatchPermit(permit_id=f"permit-{row['action_id']}-a{row['attempts']}", work_order_id=row["action_id"],
                            project_snapshot_hash=row["binding_hash"], causal_epoch=int(row["attempts"]),
                            dependency_version_refs=tuple(f"{a}@{h}" for a, h in row["dependency_hashes"]),
                            authority_refs=(f"principal:{row['actor_ref']}",), approval_refs=approvals,
                            tool_contract_refs=(row["binding"]["capability_ref"],), eligibility_policy_version=RISK_POLICY_VERSION,
                            issued_at=moment)
    put_dispatch_permit(row["run_id"], row["tenant_id"], row["project_id"], permit)


def _execution_receipt(row: dict, *, started: datetime, ended: datetime, returned_state: str, result_ref: Optional[str]) -> None:
    from services.langgraph.agency.execution.models import ExecutionReceipt
    from services.langgraph.persistence.proofs import put_execution_receipt

    put_execution_receipt(row["run_id"], row["tenant_id"], row["project_id"], ExecutionReceipt(
        operation_id=f"{row['action_id']}:a{row['attempts']}", work_order_id=row["action_id"], actor_role_id="actions.gateway",
        tool=row["capability_id"], tool_contract_ref=row["binding"]["capability_ref"], args_hash=row["payload_hash"],
        target=row["target_ref"], idempotency_key=_ctx(row).effect_key, attempt=max(1, min(int(row["attempts"]), 3)),
        started_at=started, ended_at=ended, returned_state=returned_state, result_ref=result_ref))


def _observation_receipt(row: dict, obs: Observation, expected_state: str, matches: bool, tag: str) -> None:
    from services.langgraph.agency.execution.models import ObservationReceipt
    from services.langgraph.persistence.proofs import put_observation_receipt

    put_observation_receipt(row["run_id"], row["tenant_id"], row["project_id"], ObservationReceipt(
        operation_id=f"{row['action_id']}:{tag}", target=row["target_ref"],
        expected_postcondition={"state": expected_state, "payload_hash": row["payload_hash"]},
        observed_postcondition={"found": obs.found, "state": obs.state, "payload_hash": obs.payload_hash, "cost_minor": obs.cost_minor},
        observation_method=obs.method, evidence_refs=tuple(x for x in (obs.provider_ref,) if x), matches=matches))


def _expected_state(row: dict, adapter: ActionAdapter) -> str:
    return adapter.expected_state(adapter.validate(row["args"]))


def _matches(row: dict, obs: Observation, expected: str) -> bool:
    return obs.found and obs.state == expected and obs.payload_hash == row["payload_hash"]


def _execute_and_observe(row: dict, adapter: ActionAdapter, *, actor: str, now: datetime) -> dict:
    ctx = _ctx(row)
    args = adapter.validate(row["args"])
    started = datetime.now(timezone.utc)
    try:
        receipt = adapter.execute(ctx, args)
    except OutcomeUnknown as exc:
        return _to_unknown(row, reason=f"OUTCOME_UNKNOWN: {exc.detail}", actor=actor, now=now)
    except TransientBeforeEffect as exc:
        eligible = int(row["attempts"]) < MAX_ATTEMPTS
        _release_budget(row, "RELEASED", "failed before effect")
        return _move(row, ActionState.FAILED, actor=actor, reason=f"{exc.code}: {exc.detail}",
                     updates={"retry_eligible": eligible, "lease_owner": None, "lease_expires_at": None, "reasons": [exc.code],
                              "budget_reservation_id": None}, now=now)
    except (PermanentFailure, ToolUnavailable, ArgsInvalid) as exc:
        _release_budget(row, "RELEASED", "failed")
        return _move(row, ActionState.FAILED, actor=actor, reason=f"{exc.code}: {exc.detail}",
                     updates={"retry_eligible": False, "lease_owner": None, "lease_expires_at": None, "reasons": [exc.code]},
                     now=now)
    ended = datetime.now(timezone.utc)
    _execution_receipt(row, started=started, ended=ended, returned_state=receipt.returned_state, result_ref=receipt.provider_ref)
    row = _move(row, ActionState.OBSERVING, actor=actor, reason="receipt persisted; reading back the provider state",
                evidence={"receipt": receipt.model_dump(mode="json")}, now=now)
    return _observe(row, adapter, actor=actor, now=now, tag=f"observe-a{row['attempts']}")


def _observe(row: dict, adapter: ActionAdapter, *, actor: str, now: datetime, tag: str) -> dict:
    expected = _expected_state(row, adapter)
    try:
        obs = adapter.observe(_ctx(row))
    except AdapterError as exc:
        return _to_unknown(row, reason=f"OBSERVE_FAILED: {exc.code}", actor=actor, now=now)
    matches = _matches(row, obs, expected)
    _observation_receipt(row, obs, expected, matches, tag)
    if not matches:
        return _to_unknown(row, reason="OBSERVATION_MISMATCH: the read-back does not match the expected effect", actor=actor,
                           now=now, observation=obs)
    return _complete(row, obs, actor=actor, now=now)


def _complete(row: dict, obs: Observation, *, actor: str, now: datetime) -> dict:
    row = _move(row, ActionState.VERIFIED, actor=actor, reason="independent read-back matches the expected effect",
                evidence={"observation": obs.model_dump(mode="json")}, now=now)
    budget = None
    if row.get("budget_reservation_id"):
        res = db.get_reservation(row["budget_reservation_id"])
        if res is not None and res["status"] == "RESERVED":
            budget = db.settle_reservation(res["reservation_id"], status="COMMITTED", committed_minor=int(obs.cost_minor),
                                           evidence={"observed_cost_minor": obs.cost_minor, "source": obs.method,
                                                     "provider_ref": obs.provider_ref})
    outcome = {"label": "SIMULATED" if obs.simulated else "OBSERVED", "simulated": obs.simulated, "provider_ref": obs.provider_ref,
               "observed_state": obs.state, "observed_payload_hash": obs.payload_hash, "observed_cost_minor": obs.cost_minor,
               "currency": obs.currency, "budget_committed": bool(budget), "delivered_externally": False}
    row = _move(row, ActionState.COMPLETED, actor=actor, reason="completed and independently checked",
                updates={"lease_owner": None, "lease_expires_at": None, "outcome": outcome, "retry_eligible": False}, now=now)
    if row.get("run_id"):
        from services.langgraph.persistence.runs import update_run_status

        update_run_status(row["run_id"], "completed")
    return row


def _to_unknown(row: dict, *, reason: str, actor: str, now: datetime, observation: Optional[Observation] = None) -> dict:
    from services.langgraph.app.runtime_support import trust_kernel

    row = _move(row, ActionState.UNKNOWN, actor=actor, reason=reason,
                evidence={"observation": observation.model_dump(mode="json") if observation else None},
                updates={"lease_owner": None, "lease_expires_at": None, "reasons": [reason]}, now=now)
    trust = trust_kernel()
    trust.bind_project(tenant_id=row["tenant_id"], project_id=row["project_id"])
    trust.open_recovery_case(tenant_id=row["tenant_id"], project_id=row["project_id"], operation_id=row["action_id"],
                             reason="AMBIGUOUS_EXTERNAL_RESULT" if observation is None else "OBSERVATION_MISMATCH",
                             idempotency_key=_ctx(row).effect_key, evidence_refs=(reason[:200],))
    return row


# --------------------------------------------------------------------------- reconcile / retry / compensate


def reconcile(action_id: str, *, actor: str = "system:recovery", principal: Optional[Principal] = None,
              now: Optional[datetime] = None) -> dict:
    """UNKNOWN → RECONCILING → VERIFIED | FAILED | NEEDS_HUMAN, by read-back only (I09).

    Never re-sends the effect: an unknown external write is not retried blindly."""
    moment = _now(now)
    row = db.get_request(action_id)
    if principal is not None:
        row = broker.visible(principal, row)
        broker.authorize_scope(principal, row["project_id"], write=True)
        actor = principal.user_id
    if row is None:
        raise LookupError("action not found")
    if row["state"] == ActionState.NEEDS_HUMAN.value and principal is not None:
        pass
    elif row["state"] != ActionState.UNKNOWN.value:
        raise NotDispatchable("NOT_RECONCILABLE", f"action is {row['state']}")
    descriptor = catalog().get(row["capability_id"])
    adapter = _adapter_for(descriptor)
    try:
        row = _move(row, ActionState.RECONCILING, actor=actor, reason="reading provider state by effect key",
                    updates={"lease_owner": actor, "lease_expires_at": db.iso(moment + timedelta(seconds=120)),
                             "reconcile_attempts": int(row["reconcile_attempts"]) + 1}, now=moment)
    except db.ActionConflict as exc:
        raise NotDispatchable("ALREADY_RECONCILING", str(exc)) from exc
    expected = _expected_state(row, adapter)
    try:
        obs = adapter.reconcile(_ctx(row))
    except AdapterError as exc:
        if int(row["reconcile_attempts"]) >= MAX_RECONCILE_ATTEMPTS:
            return _move(row, ActionState.NEEDS_HUMAN, actor=actor, reason=f"provider unreadable after {row['reconcile_attempts']} attempts",
                         updates={"lease_owner": None, "lease_expires_at": None, "reasons": [exc.code]}, now=moment)
        return _move(row, ActionState.UNKNOWN, actor=actor, reason=f"provider unreadable ({exc.code}); will try again",
                     updates={"lease_owner": None, "lease_expires_at": None}, now=moment)
    matches = _matches(row, obs, expected)
    _observation_receipt(row, obs, expected, matches, f"reconcile-{row['reconcile_attempts']}")
    if matches:
        return _complete(row, obs, actor=actor, now=moment)
    if not obs.found:
        eligible = int(row["attempts"]) < MAX_ATTEMPTS
        _release_budget(row, "RELEASED", "reconciled: not applied")
        return _move(row, ActionState.FAILED, actor=actor, reason="NOT_APPLIED: the provider has no record of the effect",
                     evidence={"observation": obs.model_dump(mode="json")},
                     updates={"lease_owner": None, "lease_expires_at": None, "retry_eligible": eligible, "reasons": ["NOT_APPLIED"],
                              "budget_reservation_id": None}, now=moment)
    return _move(row, ActionState.NEEDS_HUMAN, actor=actor, reason="OBSERVATION_MISMATCH: the provider state differs from the bound effect",
                 evidence={"observation": obs.model_dump(mode="json")},
                 updates={"lease_owner": None, "lease_expires_at": None, "reasons": ["OBSERVATION_MISMATCH"]}, now=moment)


def recover_stale(*, now: Optional[datetime] = None) -> list[dict]:
    """Crash recovery (E08): an expired lease means the worker died mid-flight.
    The effect may or may not exist, so the action becomes UNKNOWN and is
    reconciled by read-back, never re-sent."""
    moment = _now(now)
    out = []
    for row in db.leased_past(moment, (ActionState.DISPATCHING.value, ActionState.OBSERVING.value, ActionState.RECONCILING.value)):
        try:
            row = _move(row, ActionState.UNKNOWN, actor="system:recovery", reason="LEASE_EXPIRED: worker crashed mid-flight",
                        updates={"lease_owner": None, "lease_expires_at": None}, now=moment)
        except (db.ActionConflict, ValueError):
            continue
        out.append(reconcile(row["action_id"], now=moment))
    return out


def retry(principal: Principal, action_id: str, *, now: Optional[datetime] = None) -> dict:
    moment = _now(now)
    row = broker.visible(principal, db.get_request(action_id))
    broker.authorize_scope(principal, row["project_id"], write=True)
    if row["state"] != ActionState.FAILED.value or not row["retry_eligible"]:
        raise NotDispatchable("NOT_RETRYABLE", "only a failure known to have had no effect may be retried")
    if int(row["attempts"]) >= MAX_ATTEMPTS:
        raise NotDispatchable("RETRY_LIMIT", f"{MAX_ATTEMPTS} attempts used")
    row = _move(row, ActionState.AUTHORIZED, actor=principal.user_id, reason="bounded retry of a failure with no effect",
                updates={"retry_eligible": False, "reasons": [], "budget_reservation_id": None}, now=moment)
    return dispatch(principal, action_id, now=moment)


def compensate(principal: Principal, action_id: str, *, reason: str, now: Optional[datetime] = None) -> dict:
    """Run the adapter's compensation for a completed action and record it.
    Needs an approver role who is not the requester."""
    from services.langgraph.security.approval_authority import approver_roles

    moment = _now(now)
    row = broker.visible(principal, db.get_request(action_id))
    broker.authorize_scope(principal, row["project_id"], write=True)
    if broker.role(principal) not in approver_roles():
        raise broker.ActionForbidden("compensation requires an approver role")
    if principal.user_id == row["actor_ref"]:
        raise broker.ActionForbidden("the requester cannot compensate their own action")
    if row["state"] != ActionState.COMPLETED.value:
        raise NotDispatchable("NOT_COMPENSATABLE", f"action is {row['state']}")
    if freeze_reasons(row["tenant_id"], row["project_id"]):
        raise Frozen("DISPATCH_FROZEN", "compensation is a dispatch and is frozen too")
    adapter = _adapter_for(catalog().get(row["capability_id"]))
    try:
        obs = adapter.compensate(_ctx(row))
    except CompensationUnsupported as exc:
        raise NotDispatchable("COMPENSATION_UNSUPPORTED", exc.detail) from exc
    if row.get("budget_reservation_id"):
        res = db.get_reservation(row["budget_reservation_id"])
        if res is not None and res["status"] == "COMMITTED" and obs.state == "REFUNDED":
            db.settle_reservation(res["reservation_id"], status="REFUNDED", expected_status="COMMITTED",
                                  evidence={"refund_observed": obs.model_dump(mode="json")})
    outcome = {**(row.get("outcome") or {}), "compensation": {"by": principal.user_id, "reason": reason, "observed_state": obs.state,
                                                              "at": db.iso(moment)}}
    return db.annotate(action_id, expected_version=row["version"], actor=principal.user_id, reason=f"compensated: {reason}",
                       evidence={"observation": obs.model_dump(mode="json")}, outcome=outcome)


# --------------------------------------------------------------------------- views


def view(row: dict, *, now: Optional[datetime] = None) -> dict:
    moment = _now(now)
    risk = row.get("risk") or {}
    current_deps = broker.current_dependencies(row["project_id"], row["dependency_hashes"])
    binding = row["binding"]
    approvals = broker.check_approvals(row, now=moment) if binding.get("approval_subjects") else None
    current_binding = {**binding, "dependency_hashes": [list(x) for x in current_deps], "policy_version": RISK_POLICY_VERSION}
    return {
        "action_id": row["action_id"], "tenant_id": row["tenant_id"], "project_id": row["project_id"], "client_id": row.get("client_id"),
        "capability_id": row["capability_id"], "capability_version": row["capability_version"], "environment": row["environment"],
        "actor_ref": row["actor_ref"], "target_ref": row["target_ref"], "args": redacted(row["args"]),
        "payload_hash": row["payload_hash"], "context_hash": row["context_hash"], "policy_version": row["policy_version"],
        "dependency_hashes": row["dependency_hashes"], "risk": risk, "effective_class": row["effective_class"],
        "binding": binding, "binding_hash": row["binding_hash"],
        "binding_diff": binding_diff({**binding, "dependency_hashes": [list(x) for x in binding["dependency_hashes"]]}, current_binding),
        "approvals": approvals.model_dump(mode="json") if approvals else None, "run_id": row.get("run_id"),
        "budget_reservation_id": row.get("budget_reservation_id"), "idempotency_key": row["idempotency_key"],
        "correlation_id": row["correlation_id"], "state": row["state"], "status_label": STATUS_LABELS.get(row["state"], row["state"]),
        "version": row["version"], "attempts": row["attempts"], "retry_eligible": row["retry_eligible"],
        "reasons": row["reasons"], "outcome": row.get("outcome"), "injection_flags": row["injection_flags"],
        "created_at": row["created_at"], "updated_at": row["updated_at"], "expires_at": row["expires_at"],
        "live_execution": "DISABLED",
    }


__all__ = [
    "Frozen", "GatewayError", "InvalidRequest", "LiveGated", "NotDispatchable", "budget_headroom", "cancel", "compensate",
    "dispatch", "expire_due", "preflight", "preview", "propose", "reconcile", "recover_stale", "retry", "settle", "view",
]
