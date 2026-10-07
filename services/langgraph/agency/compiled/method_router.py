"""MethodRouter: objective -> ProblemSignature -> minimal MethodStack -> MethodPlan.

Classification is multi-label and evidence-gated. A family is selected only
when a *structural* fact in the request supports it (two or more items to
rank, two or more options, a recurring problem with unknown cause, observed
variation, ...). Words in the objective are corroborating cues: on their own
they never select a family; they produce at most three clarifying questions,
because an answer would change the plan.

The stack is a deterministic minimum: each selected family contributes
*needs* (outputs, decisions, validation, measurement, risk gates), methods are
chosen by greedy set cover over the applicable, non-contraindicated catalog
entries (most uncovered needs, then lowest effort, then slot order, then id),
and every chosen method is then removed counterfactually. A method whose
removal leaves every need covered is pruned. What remains carries a
MinimalityCertificate naming the needs only it serves.

Nothing here executes, calls a model or grants authority.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from .hashing import semantic_hash
from .method_catalog import MethodCatalog, all_hold, any_holds, load_catalog
from .method_models import (
    MAX_ROUTER_PASSES,
    MAX_SHADOW_STACKS,
    MAX_TASK_RETRIES,
    SLOT_ORDER,
    DelegationEnvelope,
    ExcludedMethod,
    FamilyEvidence,
    HumanGate,
    MethodPlan,
    MethodSpec,
    MethodStack,
    MinimalityCertificate,
    ObjectiveRequest,
    ProblemSignature,
    ShadowDuel,
    Slot,
)

MACRO_NEED = "macro:structured_cycle"
PREREQ_NODE = "prereq:measurement_plan"
MAX_CLARIFICATIONS = 3

_WS = re.compile(r"\s+")

# Structural signals: each is a fact the caller stated, not a word they used.
SIGNALS: dict[str, Callable[[ObjectiveRequest], bool]] = {
    "items_to_rank": lambda r: len(r.items_to_rank) >= 2,
    "options": lambda r: len(r.options) >= 2,
    "process_gap_defined": lambda r: bool(r.process_exists and r.current_state_known and r.target_state_known),
    "problem_recurs_cause_unknown": lambda r: bool(r.problem_recurs) and r.root_cause_known is not True,
    "waste_observed": lambda r: bool(r.waste_observed),
    "throughput_constrained": lambda r: bool(r.throughput_constrained),
    "variation_observed": lambda r: bool(r.variation_observed),
    "high_consequence_or_irreversible": lambda r: r.consequence in {"high", "critical"} or r.reversibility == "irreversible",
    "customer_needs_unknown": lambda r: bool(r.customer_needs_unknown),
    "scoped_known_solution": lambda r: bool(r.deliverable_scope_defined and r.solution_known),
    "unknown_solution_high_uncertainty": lambda r: r.solution_known is False and r.uncertainty == "high",
    "strategic_question": lambda r: bool(r.strategic_question),
    "strategy_needs_alignment": lambda r: bool(r.strategy_needs_alignment),
    "decision_rights_unclear": lambda r: bool(r.decision_rights_unclear),
    "change_adoption_required": lambda r: bool(r.change_adoption_required),
    "coupled_feedback_system": lambda r: r.system_coupling == "high" and bool(r.feedback_loops_suspected),
    "live_service_incidents": lambda r: bool(r.live_service and r.incidents_recurring),
    "lessons_or_recurrence": lambda r: bool(r.lessons_to_capture or r.problem_recurs),
}

_OBSERVABLE = (
    "problem_recurs", "variation_observed", "waste_observed", "throughput_constrained",
    "customer_needs_unknown", "deliverable_scope_defined", "strategic_question",
    "strategy_needs_alignment", "decision_rights_unclear", "change_adoption_required",
    "feedback_loops_suspected", "live_service", "incidents_recurring", "lessons_to_capture",
)


class RouterError(ValueError):
    pass


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _set_like(values: tuple[str, ...], *, lower: bool = False) -> tuple[str, ...]:
    cleaned = {(_clean(v).lower() if lower else _clean(v)) for v in values if _clean(v)}
    return tuple(sorted(cleaned))


def normalize_request(request: ObjectiveRequest) -> ObjectiveRequest:
    """Canonical form: equivalent requests (reordered, re-spaced) are equal."""

    return request.model_copy(
        update={
            "objective": _clean(request.objective),
            "desired_outcome": _clean(request.desired_outcome),
            "domains": _set_like(request.domains, lower=True),
            "constraints": _set_like(request.constraints),
            "non_goals": _set_like(request.non_goals),
            "items_to_rank": _set_like(request.items_to_rank),
            "options": _set_like(request.options),
        }
    )


def request_hash(request: ObjectiveRequest) -> str:
    return semantic_hash(normalize_request(request).model_dump(mode="json"))


def _observations(request: ObjectiveRequest) -> tuple[str, ...]:
    facts = [name for name in _OBSERVABLE if getattr(request, name)]
    if len(request.items_to_rank) >= 2:
        facts.append("items_to_rank")
    if len(request.options) >= 2:
        facts.append("options")
    return tuple(sorted(facts))


def _cues(text: str, cues: tuple[str, ...]) -> tuple[str, ...]:
    lowered = text.casefold()
    return tuple(sorted(c for c in cues if re.search(rf"(?<![a-z]){re.escape(c.casefold())}", lowered)))


def classify(request: ObjectiveRequest, catalog: MethodCatalog) -> tuple[FamilyEvidence, ...]:
    text = f"{request.objective} {request.desired_outcome}"
    evidence = []
    for family in sorted(catalog.families.values(), key=lambda f: f.family_id):
        signals = tuple(sorted(s for s in family.signals if SIGNALS[s](request)))
        cues = _cues(text, family.lexical_cues)
        if signals or cues:
            evidence.append(
                FamilyEvidence(
                    family_id=family.family_id,
                    structural_signals=signals,
                    lexical_cues=cues,
                    selected=bool(signals),
                )
            )
    return tuple(evidence)


def build_signature(request: ObjectiveRequest, families: tuple[str, ...]) -> ProblemSignature:
    r = request
    return ProblemSignature(
        objective=r.objective,
        desired_outcome=r.desired_outcome,
        problem_families=families,
        domains=r.domains,
        current_state_known=r.current_state_known,
        target_state_known=r.target_state_known,
        process_exists=r.process_exists,
        root_cause_known=r.root_cause_known,
        solution_known=r.solution_known,
        measurement_available=r.measurement_available,
        uncertainty=r.uncertainty,
        reversibility=r.reversibility,
        consequence=r.consequence,
        externality=r.externality,
        data_sensitivity=r.data_sensitivity,
        system_coupling=r.system_coupling,
        time_pressure=r.time_pressure,
        change_adoption_required=r.change_adoption_required,
        evidence_status=r.evidence_status,
        constraints=r.constraints,
        non_goals=r.non_goals,
        observations=_observations(r),
    )


def compute_needs(signature: ProblemSignature, catalog: MethodCatalog) -> dict[str, Slot]:
    needs: dict[str, Slot] = {}
    for family_id in signature.problem_families:
        for need, slot in catalog.families[family_id].needs.items():
            needs.setdefault(need, slot)
    families = set(signature.problem_families)
    if "DECISION" in families and signature.consequence in {"high", "critical"}:
        needs["validation:decision_robustness"] = Slot.DECIDE
    if "STRATEGY" in families and signature.uncertainty == "high":
        needs["output:scenarios_explored"] = Slot.DIAGNOSE
    if "STRATEGY_EXECUTION" in families and signature.target_state_known is not True:
        needs["output:goals_specified"] = Slot.DECIDE
    # A structured lifecycle method earns its place only when the work spans
    # at least three distinct non-macro slots.
    if len({slot for slot in needs.values()}) >= 3:
        needs[MACRO_NEED] = Slot.MACRO
    return dict(sorted(needs.items()))


def _needs_measurement(needs: dict[str, Slot]) -> bool:
    return any(need.startswith(("measurement:", "control:")) for need in needs)


def _effective(signature: ProblemSignature, prereq: bool) -> ProblemSignature:
    """With a measurement-plan prerequisite, later methods may assume data."""
    return signature.model_copy(update={"measurement_available": True}) if prereq else signature


def _screen(
    catalog: MethodCatalog, signature: ProblemSignature, needs: dict[str, Slot], banned: set[str]
) -> tuple[list[MethodSpec], list[ExcludedMethod]]:
    usable: list[MethodSpec] = []
    excluded: list[ExcludedMethod] = []
    for method in sorted(catalog.methods.values(), key=lambda m: m.method_id):
        if not set(method.expected_outputs) & set(needs):
            continue
        if method.method_id in banned:
            excluded.append(ExcludedMethod(method_id=method.method_id, reason="CONFLICT_RESOLUTION"))
        elif method.slot is Slot.MACRO and not {method.family, *method.secondary_families} & set(signature.problem_families):
            # A lifecycle methodology frames only the problem families it belongs to.
            excluded.append(ExcludedMethod(method_id=method.method_id, reason="MACRO_FAMILY_MISMATCH"))
        elif any_holds(method.contraindications, signature):
            excluded.append(ExcludedMethod(method_id=method.method_id, reason="CONTRAINDICATED"))
        elif not all_hold(method.applicability_predicates, signature):
            excluded.append(ExcludedMethod(method_id=method.method_id, reason="NOT_APPLICABLE"))
        else:
            usable.append(method)
    return usable, excluded


def _key(method: MethodSpec, gain: int) -> tuple:
    return (-gain, method.effort, SLOT_ORDER.index(method.slot), method.method_id)


def _greedy(usable: list[MethodSpec], needs: set[str], force: Optional[str] = None):
    """Set cover. Returns (chosen ids, first tie as (a, b) or None)."""
    uncovered = set(needs)
    chosen: list[str] = []
    first_tie: Optional[tuple[str, str]] = None
    pool = {m.method_id: m for m in usable}
    while uncovered:
        scored = [(len(set(m.expected_outputs) & uncovered), m) for m in pool.values() if m.method_id not in chosen]
        scored = [(g, m) for g, m in scored if g > 0]
        if not scored:
            break
        scored.sort(key=lambda gm: _key(gm[1], gm[0]))
        best_gain, best = scored[0]
        tied = [m for g, m in scored if g == best_gain and m.effort == best.effort]
        pick = best
        if len(tied) > 1 and first_tie is None:
            first_tie = (tied[0].method_id, tied[1].method_id)
            if force is not None and force in {t.method_id for t in tied}:
                pick = pool[force]
        chosen.append(pick.method_id)
        uncovered -= set(pick.expected_outputs)
    return chosen, first_tie


def _prune(chosen: list[str], catalog: MethodCatalog, needs: set[str]) -> list[str]:
    """Counterfactually remove each method; keep only those some need requires."""
    kept = list(chosen)
    for method_id in reversed(chosen):
        others = [m for m in kept if m != method_id]
        covered = {o for m in others for o in catalog.methods[m].expected_outputs} & needs
        mine = set(catalog.methods[method_id].expected_outputs) & needs
        if mine <= covered:
            kept = others
    return kept


def _stack_score(chosen: list[str], catalog: MethodCatalog, needs: set[str]) -> tuple:
    covered = {o for m in chosen for o in catalog.methods[m].expected_outputs} & needs
    return (len(needs - covered), sum(catalog.methods[m].effort for m in chosen), len(chosen), tuple(sorted(chosen)))


def _conflicts(chosen: list[str], catalog: MethodCatalog) -> list[str]:
    losers = []
    for method_id in chosen:
        for other in catalog.methods[method_id].conflicts_with:
            if other in chosen:
                a, b = catalog.methods[method_id], catalog.methods[other]
                losers.append(max((a, b), key=lambda m: (m.effort, m.method_id)).method_id)
    return sorted(set(losers))


def select_methods(signature: ProblemSignature, needs: dict[str, Slot], catalog: MethodCatalog, *, prereq: bool):
    """Returns (methods, certificates, excluded, duels, unresolved, needs).

    The macro need is optional: when no lifecycle methodology fits the
    selected families it is dropped rather than reported as a gap.
    """
    effective = _effective(signature, prereq)
    if MACRO_NEED in needs:
        usable, _ = _screen(catalog, effective, needs, set())
        if not any(MACRO_NEED in m.expected_outputs for m in usable):
            needs = {k: v for k, v in needs.items() if k != MACRO_NEED}
    need_set = set(needs)
    banned: set[str] = set()
    unresolved: list[str] = []
    duels: list[ShadowDuel] = []
    for _ in range(MAX_ROUTER_PASSES):
        usable, excluded = _screen(catalog, effective, needs, banned)
        primary, tie = _greedy(usable, need_set)
        primary = _prune(primary, catalog, need_set)
        duels = []
        if tie is not None and MAX_SHADOW_STACKS >= 2:
            # Shadow duel (planning only): the alternative at the first exact
            # tie is compiled and both stacks are judged by the same
            # acceptance contract; nothing is executed for either.
            alternative, _ = _greedy(usable, need_set, force=tie[1])
            alternative = _prune(alternative, catalog, need_set)
            if sorted(alternative) != sorted(primary):
                stacks = {"A": primary, "B": alternative}
                winner = min(stacks, key=lambda k: _stack_score(stacks[k], catalog, need_set))
                duels.append(
                    ShadowDuel(
                        candidates=(semantic_hash(sorted(primary)), semantic_hash(sorted(alternative))),
                        winner=semantic_hash(sorted(stacks[winner])),
                        rule="fewest_uncovered_needs,lowest_effort,fewest_methods,lexical",
                    )
                )
                primary = stacks[winner]
        losers = _conflicts(primary, catalog)
        if not losers:
            break
        banned |= set(losers)
    else:
        unresolved.append("METHOD_CONFLICT_UNRESOLVED")
        losers = _conflicts(primary, catalog)
        primary = [m for m in primary if m not in losers]

    covered = {o for m in primary for o in catalog.methods[m].expected_outputs}
    unresolved.extend(f"NO_APPLICABLE_METHOD:{need}" for need in sorted(need_set - covered))
    certificates = []
    for method_id in sorted(primary):
        others = {o for m in primary if m != method_id for o in catalog.methods[m].expected_outputs}
        unique = tuple(sorted((set(catalog.methods[method_id].expected_outputs) & need_set) - others))
        certificates.append(
            MinimalityCertificate(
                method_id=method_id,
                necessary_for=unique,
                downstream_effect_if_removed=f"Uncovered needs: {', '.join(unique)}; dependents lose these inputs.",
            )
        )
    return primary, certificates, excluded, duels, unresolved, needs


def _stack(primary: list[str], catalog: MethodCatalog, excluded, classification) -> MethodStack:
    by_slot: dict[Slot, list[str]] = {slot: [] for slot in SLOT_ORDER}
    for method_id in sorted(primary):
        by_slot[catalog.methods[method_id].slot].append(method_id)
    selected = [e for e in classification if e.selected]
    strength = [min(1.0, (len(e.structural_signals) + (1 if e.lexical_cues else 0)) / 2) for e in selected]
    body = {slot.value: tuple(ids) for slot, ids in by_slot.items()}
    return MethodStack(
        macro_methodologies=body["MACRO"],
        diagnostic_methods=body["DIAGNOSE"],
        decision_methods=body["DECIDE"],
        execution_methods=body["EXECUTE"],
        control_methods=body["CONTROL"],
        learning_methods=body["LEARN"],
        excluded_methods=tuple(excluded),
        source_refs=tuple(sorted({r for m in primary for r in catalog.methods[m].source_refs})),
        selection_confidence=round(sum(strength) / len(strength), 4) if strength else 0.0,
        stack_hash=semantic_hash(body),
    )


_RISK = {"low": "low", "medium": "medium", "high": "high", "critical": "critical", "unknown": "medium"}
_STOP = (
    "acceptance criteria pass",
    "retry limit exhausted",
    "required authority or approval missing",
    "dependency or context becomes stale",
    "same failure fingerprint twice",
    "no measurable contract progress: reclassify problem",
)
_PROOF = (
    "validator confirms each expected output against its acceptance criterion",
    "output content hash recorded",
)


def _side_effect(method: Optional[MethodSpec], signature: ProblemSignature) -> str:
    if method is None or method.slot is not Slot.EXECUTE:
        return "DRAFT"
    if signature.reversibility == "irreversible" and signature.externality == "external":
        return "IRREVERSIBLE_WRITE"
    return "REVERSIBLE_WRITE"


def _retry_limit(side_effect: str) -> int:
    return {"PURE": MAX_TASK_RETRIES, "DRAFT": MAX_TASK_RETRIES, "REVERSIBLE_WRITE": 1, "IRREVERSIBLE_WRITE": 0}[side_effect]


def envelope_context_hash(body: dict, upstream: dict[str, str]) -> str:
    """Proof-carrying handoff: binds objective, inputs, methods, evidence,
    acceptance, authority, tools and each dependency's own context hash."""
    return semantic_hash(
        {
            "objective": body["objective"],
            "inputs": body["inputs"],
            "method_refs": body["method_refs"],
            "evidence_requirements": body["evidence_requirements"],
            "acceptance_criteria": body["acceptance_criteria"],
            "authority_refs": body["authority_refs"],
            "approval_refs": body["approval_refs"],
            "tool_plan": body["tool_plan"],
            # A dependency without a known hash (forward reference or cycle)
            # hashes as unresolved, so the chain check flags it and the graph
            # build rejects the cycle.
            "dependencies": sorted((dep, upstream.get(dep, "UNRESOLVED")) for dep in body["dependencies"]),
        }
    )


def build_envelopes(
    signature: ProblemSignature,
    primary: list[str],
    needs: dict[str, Slot],
    certificates: list[MinimalityCertificate],
    catalog: MethodCatalog,
    *,
    prereq: bool,
) -> tuple[DelegationEnvelope, ...]:
    families = set(signature.problem_families)
    unique = {c.method_id: c.necessary_for for c in certificates}
    layers: list[list[tuple[str, Optional[MethodSpec]]]] = []
    for slot in SLOT_ORDER:
        layer = [(f"m:{mid}", catalog.methods[mid]) for mid in sorted(primary) if catalog.methods[mid].slot is slot]
        if slot is Slot.DIAGNOSE and prereq:
            # Uncertainty first: the missing measurement baseline is resolved
            # before any method that consumes measurements.
            layers.append([(PREREQ_NODE, None)])
        if layer:
            layers.append(layer)

    target = f"process:{semantic_hash(signature.objective)[:16]}"
    context: dict[str, str] = {}
    envelopes: list[DelegationEnvelope] = []
    previous: list[str] = []
    for layer in layers:
        for node_id, method in layer:
            if method is None:
                family = "PROCESS_VARIATION"
                outputs = ("measurement:baseline_defined",)
                inputs: tuple[str, ...] = ("desired outcome", "candidate metrics")
                evidence: tuple[str, ...] = ("metric definitions", "data sources")
                justified = ("E3:NO_MEASURABLE_TARGET", *sorted(n for n in needs if n.startswith(("measurement:", "control:"))))
                method_refs: tuple[str, ...] = ()
                objective = f"Define measurable targets and a baseline for: {signature.objective}"
                slot = Slot.DIAGNOSE
            else:
                family = method.family if method.family in families else next(
                    (f for f in method.secondary_families if f in families), method.family
                )
                outputs = tuple(sorted(set(method.expected_outputs) & set(needs)))
                inputs = tuple(method.expected_inputs)
                evidence = tuple(method.evidence_needs)
                justified = unique[method.method_id]
                method_refs = (method.method_id,)
                objective = f"Apply {method.name} to: {signature.objective}"
                slot = method.slot
            side_effect = _side_effect(method, signature)
            body = {
                "node_id": node_id,
                "objective": objective,
                "problem_family": family,
                "method_refs": method_refs,
                "dependencies": tuple(previous),
                "required_capabilities": catalog.families[family].capability_terms,
                "inputs": (*inputs, *(f"ref:{dep}" for dep in previous)),
                "expected_outputs": outputs,
                "acceptance_criteria": tuple(f"{tag}: produced, evidenced and reviewable" for tag in outputs),
                "evidence_requirements": evidence,
                "tool_plan": (),
                "side_effect_class": side_effect,
                "risk_level": _RISK[signature.consequence],
                "authority_refs": (),
                "approval_refs": (),
                "idempotency_class": side_effect,
                "retry_limit": _retry_limit(side_effect),
                "stop_conditions": _STOP,
                "completion_proof": _PROOF,
                "slot": slot,
                "justified_by": justified,
                "mutation_targets": (target,) if side_effect != "DRAFT" else (),
            }
            context[node_id] = envelope_context_hash(body, context)
            envelopes.append(DelegationEnvelope(**body, context_hash=context[node_id]))
        previous = [node_id for node_id, _ in layer]
    return tuple(envelopes)


def _gates(signature: ProblemSignature, envelopes, classification) -> tuple[tuple[HumanGate, ...], list[str]]:
    gates: list[HumanGate] = []
    debt: list[str] = []
    for env in envelopes:
        if env.side_effect_class in {"REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"}:
            # Mirrors what the canonical work order will block on: consequential
            # mission nodes compile as high-risk writes needing authority,
            # permission and an approval; irreversible ones an exact approval.
            requires = ["authority_ref", "permission_ref", "approval_ref"]
            if env.side_effect_class == "IRREVERSIBLE_WRITE":
                requires.append("exact_approval_ref")
            gates.append(
                HumanGate(
                    gate_id=f"gate:authority:{env.node_id}",
                    node_id=env.node_id,
                    kind="EXECUTION_AUTHORITY",
                    requires=tuple(requires),
                    enforced_by="role_os.WorkOrderCompiler.execution_ready + security.approval_authority.assert_may_decide",
                )
            )
        if env.slot is Slot.DECIDE and signature.consequence in {"high", "critical"}:
            # Decision debt stays explicit until a human records the decision.
            gates.append(
                HumanGate(
                    gate_id=f"gate:decision:{env.node_id}",
                    node_id=env.node_id,
                    kind="MATERIAL_DECISION",
                    requires=("human_decision_record",),
                    enforced_by="security.approval_authority.assert_may_decide",
                )
            )
            debt.append(f"DECISION_PENDING:{env.node_id}")
    cue_only = sorted(
        (e for e in classification if not e.selected),
        key=lambda e: (-len(e.lexical_cues), e.family_id),
    )[:MAX_CLARIFICATIONS]
    for e in cue_only:
        gates.append(
            HumanGate(
                gate_id=f"gate:clarify:{e.family_id}",
                node_id=None,
                kind="CLARIFICATION",
                requires=(f"Confirm with a structural fact whether {e.family_id} applies (cues: {', '.join(e.lexical_cues)})",),
                separation_of_duties=False,
                enforced_by="caller supplies the structured fact; keywords alone never route",
            )
        )
    return tuple(gates), debt


def compile_method_plan(request: ObjectiveRequest, catalog: Optional[MethodCatalog] = None) -> MethodPlan:
    catalog = catalog or load_catalog()
    normalized = normalize_request(request)
    classification = classify(normalized, catalog)
    families = tuple(e.family_id for e in classification if e.selected)
    signature = build_signature(normalized, families)
    unresolved: list[str] = []
    if not families:
        unresolved.append("NO_STRUCTURAL_EVIDENCE")
    unresolved.extend(f"KEYWORD_ONLY:{e.family_id}" for e in classification if not e.selected)

    needs = compute_needs(signature, catalog)
    prereq = _needs_measurement(needs) and signature.measurement_available is not True
    if prereq:
        unresolved.append("ASSUMPTION:measurement_plan_precedes_measurement_methods")
    primary, certificates, excluded, duels, route_unresolved, needs = select_methods(signature, needs, catalog, prereq=prereq)
    unresolved.extend(route_unresolved)
    stack = _stack(primary, catalog, excluded, classification)
    envelopes = build_envelopes(signature, primary, needs, certificates, catalog, prereq=prereq)
    gates, debt = _gates(signature, envelopes, classification)
    unresolved.extend(debt)

    body = {
        "catalog_hash": catalog.catalog_hash,
        "request_hash": semantic_hash(normalized.model_dump(mode="json")),
        "problem_signature": signature,
        "classification": classification,
        "method_stack": stack,
        "minimality_certificates": tuple(certificates),
        "shadow_duels": tuple(duels),
        "delegation_envelopes": envelopes,
        "human_gates": gates,
        "unresolved": tuple(unresolved),
    }
    probe = MethodPlan(**body, plan_hash="pending")
    plan_hash = semantic_hash(probe.model_dump(mode="json"), exclude={"plan_hash"})
    return MethodPlan(**body, plan_hash=plan_hash)
