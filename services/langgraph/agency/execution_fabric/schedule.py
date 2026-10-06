"""Read adapters from the two existing planners to one execution view.

The fabric consumes whatever the canonical planners produce; it never
re-plans. ``from_compiled_agency_plan`` reads ``compiled.planner`` output and
``from_method_mission`` reads ``compiled.method_mission`` output. Both keep the
planner's graph, cells, work orders and wave plan untouched, plus a callable
that recomputes the wave plan with the *same* scheduler so the consumer can
prove the plan it is about to run is still the plan the scheduler would emit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from services.langgraph.agency.compiled.backchain import CausalWorkGraph
from services.langgraph.agency.compiled.execution import MissionCell, WavePlan, schedule_waves
from services.langgraph.agency.execution.canonical import canonical_hash


@dataclass(frozen=True)
class CellPlan:
    cell: MissionCell
    node_id: str
    artifact_type: str | None
    work_order_id: str | None
    contract_hash: str
    context_hash: str
    side_effect_class: str
    authority_refs: tuple[str, ...]
    approval_refs: tuple[str, ...]
    n3_role_id: str | None
    execution_ready: bool
    blockers: tuple[str, ...]
    max_attempts: int
    acceptance_criteria: tuple[str, ...] = ()


@dataclass(frozen=True)
class MissionSchedule:
    source: Literal["compiled_agency", "method_mission"]
    mission_id: str
    plan_hash: str
    graph: CausalWorkGraph
    cells: dict[str, CellPlan]
    wave_plan: WavePlan
    cell_for_node: dict[str, str]
    human_gates: tuple[str, ...]
    deliverables: dict[str, tuple[str, ...]]
    recompute_waves: Callable[[], WavePlan] = field(repr=False)

    @property
    def snapshot_hash(self) -> str:
        return canonical_hash({"plan_hash": self.plan_hash, "wave_hash": self.wave_plan.wave_hash, "source": self.source})


def _hash64(value: str | None, fallback: Any) -> str:
    if value and len(value) == 64:
        return value
    return canonical_hash(fallback)


def from_compiled_agency_plan(plan: Any) -> MissionSchedule:
    cell_for_node: dict[str, str] = {}
    for cid, cell in plan.cells.items():
        for ref in cell.node_refs:
            cell_for_node[ref] = cid
    cells: dict[str, CellPlan] = {}
    for cid, cell in plan.cells.items():
        node_id = cell.node_refs[0]
        node = plan.graph.nodes[node_id]
        pcwo = plan.work_orders.get(node_id)
        binding = plan.bindings.get(node_id)
        capsule = plan.capsules.get(node_id)
        blockers = set(cell.blockers) | set(plan.blocked.get(node_id, ())) | set(pcwo.blockers if pcwo else ("NO_VALID_PCWO",))
        retry = (pcwo.retry_policy if pcwo else {}) or {}
        cells[cid] = CellPlan(
            cell=cell,
            node_id=node_id,
            artifact_type=node.artifact_type,
            work_order_id=pcwo.work_order_id if pcwo else None,
            contract_hash=_hash64(pcwo.work_order_hash if pcwo else None, {"node": node_id, "none": True}),
            context_hash=_hash64(capsule.capsule_hash if capsule else None, {"node": node_id, "capsule": None}),
            side_effect_class=pcwo.side_effect_class if pcwo else node.side_effect_class,
            # PCWOs carry no authority refs of their own: grants live in the
            # planner request and only ever widen through a server context.
            authority_refs=(),
            approval_refs=tuple(cell.approval_refs),
            n3_role_id=binding.runtime_authority_role_id if binding else None,
            execution_ready=bool(pcwo and pcwo.execution_ready),
            blockers=tuple(sorted(blockers)),
            max_attempts=max(1, min(3, int(retry.get("max_attempts", 1)))),
            acceptance_criteria=tuple(pcwo.acceptance_criteria) if pcwo else (),
        )
    mission_id = "mission-" + plan.plan_hash[:20]

    def recompute() -> WavePlan:
        return schedule_waves(plan.graph, {cid: cp.cell for cid, cp in cells.items()}, cell_for_node=cell_for_node)

    deliverables = {
        root: tuple(plan.graph.nodes[root].validation_obligations or ()) for root in plan.graph.roots
    }
    return MissionSchedule(
        source="compiled_agency",
        mission_id=mission_id,
        plan_hash=plan.plan_hash,
        graph=plan.graph,
        cells=cells,
        wave_plan=plan.waves,
        cell_for_node=cell_for_node,
        human_gates=tuple(plan.human_gates),
        deliverables=deliverables,
        recompute_waves=recompute,
    )


def from_method_mission(compiled: Any) -> MissionSchedule:
    from services.langgraph.agency.compiled.method_mission import _cap_waves

    by_id = {wo["work_order_id"]: wo for wo in compiled.work_orders}
    eligibility = {e.node_id: e for e in compiled.eligibility}
    cell_for_node = {cell.node_refs[0]: cid for cid, cell in compiled.cells.items()}
    cells: dict[str, CellPlan] = {}
    for cid, cell in compiled.cells.items():
        node_id = cell.node_refs[0]
        wo = by_id[cell.work_order_refs[0]]
        body = {k: v for k, v in wo.items() if k != "_runtime"}
        blockers = set(cell.blockers) | set(eligibility[node_id].blockers) | {"ROLE_NO_N3_CONTRACT"}
        cells[cid] = CellPlan(
            cell=cell,
            node_id=node_id,
            artifact_type=None,
            work_order_id=wo["work_order_id"],
            contract_hash=canonical_hash(body),
            context_hash=_hash64(compiled.plan_hash, {"plan": compiled.plan_hash}),
            side_effect_class=wo["side_effect_class"],
            authority_refs=tuple(wo.get("authority_refs") or ()),
            approval_refs=tuple(wo.get("approval_refs") or ()),
            n3_role_id=None,
            execution_ready=bool(wo["_runtime"]["execution_ready"]),
            blockers=tuple(sorted(blockers)),
            max_attempts=3,
        )

    def recompute() -> WavePlan:
        return _cap_waves(schedule_waves(compiled.graph, {cid: cp.cell for cid, cp in cells.items()}, cell_for_node=cell_for_node))

    return MissionSchedule(
        source="method_mission",
        mission_id=compiled.mission["mission_id"],
        plan_hash=compiled.plan_hash,
        graph=compiled.graph,
        cells=cells,
        wave_plan=compiled.wave_plan,
        cell_for_node=cell_for_node,
        human_gates=(),
        deliverables={},
        recompute_waves=recompute,
    )


def wave_plan_fresh(schedule: MissionSchedule) -> bool:
    return schedule.recompute_waves().wave_hash == schedule.wave_plan.wave_hash


def stale_inputs(schedule: MissionSchedule, cell_id: str) -> tuple[str, ...]:
    """Inputs whose recorded hash no longer matches the graph node's hash."""
    cell = schedule.cells[cell_id].cell
    return tuple(sorted(
        dep for dep, recorded in cell.input_refs
        if dep not in schedule.graph.nodes or schedule.graph.nodes[dep].semantic_hash != recorded
    ))


__all__ = ["CellPlan", "MissionSchedule", "from_compiled_agency_plan", "from_method_mission", "stale_inputs", "wave_plan_fresh"]
