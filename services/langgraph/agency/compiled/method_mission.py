"""MethodPlan -> mission -> canonical work orders -> cells/waves.

This is the delegation boundary. It reuses, never re-implements:

* ``role_os.MissionWorkOrderAdapter`` / ``WorkOrderCompiler`` / ``RoleResolver``
  for work-order identity, specialist resolution and execution readiness;
* ``compiled.backchain`` (CausalWorkGraph) and ``compiled.execution``
  (``build_cell`` / ``schedule_waves``) for cells and waves.

Execution: no generic executor consumes compiled work orders in this codebase
(``schedule_waves`` and ``advance_cell`` are planning-time only), so every
compiled mission reports ``EXECUTOR_GAP``. Nothing here runs a node.

Authority: envelopes carry no authority or approval refs, the adapter is given
none, and a ProofOfNonAuthority per node checks the work order holds exactly
what the envelope held (delta 0). Consequential nodes therefore compile but are
never execution-ready, whatever their routing score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.role_os.mission_adapter import MissionAdapterError, MissionWorkOrderAdapter
from services.langgraph.agency.role_os.registry import RoleOSRegistry

from .backchain import BackchainNode, CausalWorkGraph, NodeStatus, NodeType, Resolution, _finalize, _topological
from .execution import MissionCell, Wave, WavePlan, build_cell, schedule_waves
from .hashing import semantic_hash
from .method_catalog import MethodCatalog, load_catalog
from .method_models import (
    MAX_PLAN_REPAIRS,
    MAX_RETRIEVAL_PASSES,
    MAX_SPECIALISTS_PER_WAVE,
    MAX_TASK_RETRIES,
    DelegationEnvelope,
    MethodPlan,
)
from .method_router import PREREQ_NODE, envelope_context_hash

EXECUTOR_GAP = "EXECUTOR_GAP"
# Tools the method layer may plan to call. None are registered: method nodes
# produce analyses and plans, and any tool use would need a reviewed adapter.
AVAILABLE_TOOLS: frozenset[str] = frozenset()


class MethodCompileError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


class ProofOfNonAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    routing_score_used: int
    authority_source_refs: tuple[str, ...]
    authority_before: tuple[str, ...]
    authority_after: tuple[str, ...]
    authority_delta: Literal[0] = 0


@dataclass(frozen=True)
class NodeEligibility:
    node_id: str
    capability_match: bool
    schema_valid: bool
    tool_available: bool
    permission_valid: bool
    authority_valid_if_required: bool
    approval_valid_if_required: bool
    dependencies_current: bool
    policy_pass: bool
    blockers: tuple[str, ...]

    @property
    def eligible_to_execute(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class CompiledMethodMission:
    plan_hash: str
    mission: dict[str, Any]
    phase_map: dict[str, str]
    work_orders: tuple[dict[str, Any], ...]
    task_to_work_order: dict[str, str]
    eligibility: tuple[NodeEligibility, ...]
    non_authority_proofs: tuple[ProofOfNonAuthority, ...]
    graph: CausalWorkGraph
    cells: dict[str, MissionCell]
    wave_plan: WavePlan
    blocked_nodes: dict[str, tuple[str, ...]]
    executor_status: str
    executor_reason: str


def mission_projection(plan: MethodPlan, catalog: MethodCatalog) -> tuple[dict[str, Any], dict[str, str]]:
    """The canonical mission payload plus an explicit phase_map.

    Phase comes from the node's problem family (catalog policy), never from
    prose. Node ids are the MethodPlan's, kept for provenance.
    """
    if not plan.delegation_envelopes:
        raise MethodCompileError("PLAN_EMPTY", "the method plan has no delegation envelopes")
    capabilities: dict[str, dict[str, Any]] = {}
    nodes = []
    acceptance = []
    phase_map: dict[str, str] = {}
    for env in plan.delegation_envelopes:
        family = catalog.families[env.problem_family]
        cap_id = f"cap:{family.family_id}"
        capabilities[cap_id] = {"id": cap_id, "skills": list(family.capability_terms)}
        produces = [f"{env.node_id}#{tag}" for tag in env.expected_outputs]
        nodes.append(
            {
                "id": env.node_id,
                "capability": cap_id,
                "description": env.objective,
                "dependencies": list(env.dependencies),
                "produces": produces,
                "verification": list(env.acceptance_criteria),
                # HUMAN marks consequential nodes; the adapter then classes them
                # as reversible writes at high risk, which cannot be
                # execution-ready without authority and approval refs.
                "execution_mode": "HUMAN" if env.side_effect_class in {"REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"} else "AGENT",
                "tool": env.tool_plan[0] if env.tool_plan else None,
            }
        )
        acceptance.extend(
            {"artifact_id": artifact, "criterion": criterion}
            for artifact, criterion in zip(produces, env.acceptance_criteria)
        )
        phase_map[env.node_id] = family.phase_id
    mission = {
        "mission_id": f"mission-{plan.plan_hash[:20]}",
        "capabilities": [capabilities[k] for k in sorted(capabilities)],
        "task_graph": {"nodes": nodes},
        "acceptance_contracts": acceptance,
    }
    return mission, phase_map


def verify_context_chain(plan: MethodPlan) -> list[str]:
    """Node ids whose recorded context hash no longer matches its inputs.

    A changed upstream envelope changes its hash, which changes every
    dependent's recomputed hash: the stale set is the causal closure.
    """
    recomputed: dict[str, str] = {}
    stale = []
    for env in plan.delegation_envelopes:
        body = env.model_dump(mode="json")
        recomputed[env.node_id] = envelope_context_hash(body, recomputed)
        if recomputed[env.node_id] != env.context_hash:
            stale.append(env.node_id)
    return stale


def causal_closure(plan: MethodPlan, changed: Iterable[str]) -> tuple[str, ...]:
    """Nodes to invalidate and recompile when ``changed`` nodes change."""
    dependents: dict[str, set[str]] = {}
    for env in plan.delegation_envelopes:
        for dep in env.dependencies:
            dependents.setdefault(dep, set()).add(env.node_id)
    seen = set(changed)
    frontier = list(changed)
    while frontier:
        for nxt in dependents.get(frontier.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    order = [env.node_id for env in plan.delegation_envelopes]
    return tuple(n for n in order if n in seen)


def _eligibility(env: DelegationEnvelope, work_order: dict[str, Any], stale: set[str]) -> NodeEligibility:
    runtime = work_order["_runtime"]
    blockers = list(runtime["blockers"])
    tool_ok = all(tool in AVAILABLE_TOOLS for tool in env.tool_plan)
    if not tool_ok:
        blockers.append("TOOL_UNAVAILABLE")
    deps_current = env.node_id not in stale and not (set(env.dependencies) & stale)
    if not deps_current:
        blockers.append("DEPENDENCY_OR_CONTEXT_STALE")
    consequential = env.side_effect_class in {"REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"}
    authority_ok = not consequential or bool(work_order["authority_refs"])
    approval_needed = env.side_effect_class == "IRREVERSIBLE_WRITE" or env.risk_level in {"high", "critical"}
    approval_ok = not approval_needed or bool(work_order["approval_refs"])
    permission_ok = not consequential or bool(work_order["permission_refs"])
    if not permission_ok:
        blockers.append("MISSING_PERMISSION_REF")
    if not approval_ok:
        blockers.append("MISSING_EXACT_APPROVAL_REF")
    # Irreversible work never runs on policy defaults: it needs an exact approval.
    policy_ok = env.side_effect_class != "IRREVERSIBLE_WRITE" or approval_ok
    return NodeEligibility(
        node_id=env.node_id,
        capability_match=bool(runtime["role_match"]["matched_tokens"]),
        schema_valid=True,
        tool_available=tool_ok,
        permission_valid=permission_ok,
        authority_valid_if_required=authority_ok,
        approval_valid_if_required=approval_ok,
        dependencies_current=deps_current,
        policy_pass=policy_ok,
        blockers=tuple(sorted(set(blockers))),
    )


def _proof(env: DelegationEnvelope, work_order: dict[str, Any]) -> ProofOfNonAuthority:
    before = tuple(sorted({*env.authority_refs, *env.approval_refs}))
    after = tuple(sorted({*work_order["authority_refs"], *work_order["approval_refs"], *work_order["permission_refs"]}))
    if set(after) - set(before):
        raise MethodCompileError("ROUTER_AUTHORITY_ESCALATION", f"{env.node_id} gained authority {sorted(set(after) - set(before))}")
    return ProofOfNonAuthority(
        node_id=env.node_id,
        routing_score_used=int(work_order["_runtime"]["role_match"]["score"]),
        authority_source_refs=before,
        authority_before=before,
        authority_after=after,
    )


def _graph(plan: MethodPlan, phase_map: dict[str, str], eligibility: dict[str, NodeEligibility]) -> CausalWorkGraph:
    nodes: dict[str, BackchainNode] = {}
    for env in plan.delegation_envelopes:
        gate = eligibility[env.node_id]
        nodes[env.node_id] = _finalize(
            {
                "id": env.node_id,
                "type": NodeType.EXECUTABLE_WORK,
                "purpose": env.objective,
                "satisfies": env.justified_by,
                "hard_dependencies": env.dependencies,
                "phase_compatibility": (phase_map[env.node_id],),
                "required_capabilities": env.required_capabilities,
                "validation_obligations": env.acceptance_criteria,
                "side_effect_class": env.side_effect_class,
                "mutation_targets": env.mutation_targets,
                "status": NodeStatus.BLOCKED if gate.blockers else NodeStatus.PLANNED,
                "resolution": Resolution.EXECUTABLE_WORK,
                "stage": phase_map[env.node_id],
                "blockers": gate.blockers,
            }
        )
    order = _topological(nodes)  # raises BackchainCycleError on a cycle
    dependents = {d for n in nodes.values() for d in n.dependencies}
    roots = tuple(sorted(n for n in nodes if n not in dependents))
    return CausalWorkGraph(
        nodes=nodes,
        roots=roots,
        topological_order=order,
        eliminated=tuple(sorted(e.method_id for e in plan.method_stack.excluded_methods)),
        redundant_candidates=(),
        dedup_hits=0,
        graph_hash=semantic_hash({nid: n.semantic_hash for nid, n in nodes.items()}),
    )


def _cap_waves(plan: WavePlan) -> WavePlan:
    waves: list[Wave] = []
    for wave in plan.waves:
        for start in range(0, len(wave.cells), MAX_SPECIALISTS_PER_WAVE):
            chunk = wave.cells[start:start + MAX_SPECIALISTS_PER_WAVE]
            reason = wave.serialized_reason if start == 0 else "MAX_SPECIALISTS_PER_WAVE"
            waves.append(Wave(index=len(waves), cells=chunk, serialized_reason=reason))
    if len(waves) == len(plan.waves):
        return plan
    body = {"waves": [w.model_dump(mode="json") for w in waves], "held": {k: list(v) for k, v in plan.held.items()}}
    return WavePlan(waves=tuple(waves), held=plan.held, wave_hash=semantic_hash(body))


def compile_method_mission(
    plan: MethodPlan,
    *,
    registry: RoleOSRegistry,
    project_id: str,
    catalog: Optional[MethodCatalog] = None,
) -> CompiledMethodMission:
    catalog = catalog or load_catalog()
    mission, phase_map = mission_projection(plan, catalog)
    try:
        compiled = MissionWorkOrderAdapter(registry).compile(
            mission,
            project_id=project_id,
            phase_map=phase_map,
            context_capsule_hash=plan.plan_hash,
        )
    except MissionAdapterError as exc:
        code = "CAPABILITY_GAP" if "no role matches" in str(exc) or "no resolvable tokens" in str(exc) else "MISSION_INVALID"
        raise MethodCompileError(code, str(exc)) from exc

    stale = set(verify_context_chain(plan))
    by_task = {wo["_runtime"]["mission_task_id"]: wo for wo in compiled.work_orders}
    eligibility = {env.node_id: _eligibility(env, by_task[env.node_id], stale) for env in plan.delegation_envelopes}
    proofs = tuple(_proof(env, by_task[env.node_id]) for env in plan.delegation_envelopes)
    graph = _graph(plan, phase_map, eligibility)

    cells: dict[str, MissionCell] = {}
    cell_for_node: dict[str, str] = {}
    for env in plan.delegation_envelopes:
        wo = by_task[env.node_id]
        cell = build_cell(
            graph=graph,
            work_node_id=env.node_id,
            accountable_specialist=wo["accountable_role_id"],
            contributor_specialists=(),
            binding_hash=semantic_hash({"role": wo["accountable_role_id"], "authority": wo["authority_refs"]}),
            work_order_ids=(wo["work_order_id"],),
            capsule_hash=plan.plan_hash,
            validators=("acceptance_criteria",),
            resource_locks=env.mutation_targets,
            risk_class=wo["risk_level"],
            approval_refs=wo["approval_refs"],
            blockers=eligibility[env.node_id].blockers,
        )
        cells[cell.cell_id] = cell
        cell_for_node[env.node_id] = cell.cell_id
    wave_plan = _cap_waves(schedule_waves(graph, cells, cell_for_node=cell_for_node))
    return CompiledMethodMission(
        plan_hash=plan.plan_hash,
        mission=mission,
        phase_map=phase_map,
        work_orders=compiled.work_orders,
        task_to_work_order=compiled.task_to_work_order,
        eligibility=tuple(eligibility[env.node_id] for env in plan.delegation_envelopes),
        non_authority_proofs=proofs,
        graph=graph,
        cells=cells,
        wave_plan=wave_plan,
        blocked_nodes=dict(wave_plan.held),
        executor_status=EXECUTOR_GAP,
        executor_reason=(
            "No generic executor consumes compiled work orders or mission cells in this codebase; "
            "schedule_waves/advance_cell are planning-time only. The plan, work orders and waves are "
            "complete and callable; execution needs a reviewed runtime."
        ),
    )


def mutation_key(*, tenant_id: str, project_id: str, mission_id: str, node_id: str, operation: str, input_hash: str) -> str:
    """Stable semantic identity for a node's mutation: never time or randomness."""
    return semantic_hash(
        {
            "tenant": tenant_id,
            "project": project_id,
            "mission": mission_id,
            "node": node_id,
            "operation": operation,
            "input_hash": input_hash,
        }
    )


# ---------------------------------------------------------------------------
# Bounded attempt control: retry, repair, reclassify, escalate.
# ---------------------------------------------------------------------------

FailureClass = Literal["TRANSIENT", "ACCEPTANCE", "AUTHORITY", "DEPENDENCY_STALE", "TOOL_UNAVAILABLE"]
Action = Literal["DONE", "RETRY", "REPAIR", "RECLASSIFY_PROBLEM", "INVALIDATE_AND_RECOMPILE", "ESCALATE_HUMAN"]


class Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    succeeded: bool = False
    failure_class: Optional[FailureClass] = None
    failure_fingerprint: Optional[str] = None
    # Contract progress measured after the attempt (e.g. accepted outputs);
    # None when nothing was measured.
    progress: Optional[float] = None
    retrieval_new_evidence: Optional[bool] = None


class NextStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    reason: str


def next_step(envelope: DelegationEnvelope, history: list[Attempt]) -> NextStep:
    """Decide what follows an attempt history; every path is bounded."""
    if not history:
        return NextStep(action="RETRY", reason="FIRST_ATTEMPT")
    last = history[-1]
    if last.succeeded:
        return NextStep(action="DONE", reason="ACCEPTANCE_PASS")

    fingerprints = [a.failure_fingerprint for a in history if a.failure_fingerprint]
    if len(fingerprints) >= 2 and fingerprints[-1] == fingerprints[-2]:
        return NextStep(action="ESCALATE_HUMAN", reason="CIRCUIT_BREAKER:SAME_FAILURE_TWICE")
    retrievals = [a.retrieval_new_evidence for a in history if a.retrieval_new_evidence is not None]
    if len(retrievals) >= MAX_RETRIEVAL_PASSES:
        return NextStep(action="ESCALATE_HUMAN", reason="RETRIEVAL_BUDGET_EXHAUSTED")
    if len(retrievals) >= 2 and not retrievals[-1] and not retrievals[-2]:
        return NextStep(action="ESCALATE_HUMAN", reason="NO_NEW_EVIDENCE_TWICE")

    if last.failure_class == "AUTHORITY":
        return NextStep(action="ESCALATE_HUMAN", reason="AUTHORITY_OR_APPROVAL_MISSING")
    if last.failure_class == "TOOL_UNAVAILABLE":
        return NextStep(action="ESCALATE_HUMAN", reason="TOOL_UNAVAILABLE")
    if last.failure_class == "DEPENDENCY_STALE":
        return NextStep(action="INVALIDATE_AND_RECOMPILE", reason="RECOMPILE_CAUSAL_CLOSURE_ONLY")

    progress = [a.progress for a in history if a.progress is not None]
    if len(progress) >= 3 and progress[-1] <= progress[-3]:
        # Method drift: valid work that no longer moves the outcome means the
        # problem model is wrong, not that another retry will help.
        return NextStep(action="RECLASSIFY_PROBLEM", reason="NO_MEASURABLE_PROGRESS")

    if last.failure_class == "ACCEPTANCE":
        repairs = sum(1 for a in history if a.failure_class == "ACCEPTANCE")
        if repairs > MAX_PLAN_REPAIRS:
            return NextStep(action="ESCALATE_HUMAN", reason="REPAIR_BUDGET_EXHAUSTED")
        return NextStep(action="REPAIR", reason="REPAIR_SMALLEST_CAUSAL_PRODUCER")

    # TRANSIENT (or unclassified) failure.
    if envelope.retry_limit == 0:
        return NextStep(action="ESCALATE_HUMAN", reason="NO_AUTOMATIC_RETRY_FOR_THIS_SIDE_EFFECT_CLASS")
    failures = sum(1 for a in history if not a.succeeded)
    if failures > min(envelope.retry_limit, MAX_TASK_RETRIES):
        return NextStep(action="ESCALATE_HUMAN", reason="RETRY_BUDGET_EXHAUSTED")
    return NextStep(action="RETRY", reason="TRANSIENT_FAILURE")


__all__ = [
    "EXECUTOR_GAP",
    "PREREQ_NODE",
    "Attempt",
    "CompiledMethodMission",
    "MethodCompileError",
    "NextStep",
    "NodeEligibility",
    "ProofOfNonAuthority",
    "causal_closure",
    "compile_method_mission",
    "mission_projection",
    "mutation_key",
    "next_step",
    "verify_context_chain",
]
