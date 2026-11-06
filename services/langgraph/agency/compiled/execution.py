"""T16/T17 — MissionCells and the execution-wave scheduler.

A MissionCell is formed per causal work unit (produce → validate → accept one
artifact) and dissolves when done; there is no standing all-to-all chat.
Handoffs between cells are typed immutable references (node id + semantic
hash).

The scheduler layers cells into waves. Independent PURE/DRAFT work runs in
parallel; protected mutation collisions, exclusive resources and
consequential external actions are serialized; anything gated on a human
decision, missing evidence, missing authority or a pending approval is held
out with explicit reasons. Ordering inside a wave is stable:
critical_path → blocker_reduction → information_gain → reversibility → id.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping

from pydantic import BaseModel

from .backchain import CausalWorkGraph, NodeType
from .hashing import semantic_hash

_FROZEN = {"frozen": True, "extra": "forbid"}


class CellStatus(str, Enum):
    FORMED = "FORMED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    REVISION = "REVISION"
    ESCALATED = "ESCALATED"
    DISSOLVED = "DISSOLVED"


CELL_TRANSITIONS: dict[CellStatus, frozenset[CellStatus]] = {
    CellStatus.FORMED: frozenset({CellStatus.READY, CellStatus.BLOCKED}),
    CellStatus.READY: frozenset({CellStatus.EXECUTING, CellStatus.BLOCKED}),
    CellStatus.EXECUTING: frozenset({CellStatus.VALIDATING, CellStatus.BLOCKED, CellStatus.ESCALATED}),
    CellStatus.VALIDATING: frozenset({CellStatus.ACCEPTED, CellStatus.BLOCKED, CellStatus.REVISION, CellStatus.ESCALATED}),
    CellStatus.REVISION: frozenset({CellStatus.EXECUTING, CellStatus.ESCALATED}),
    CellStatus.BLOCKED: frozenset({CellStatus.READY, CellStatus.ESCALATED, CellStatus.DISSOLVED}),
    CellStatus.ESCALATED: frozenset({CellStatus.READY, CellStatus.DISSOLVED}),
    CellStatus.ACCEPTED: frozenset({CellStatus.DISSOLVED}),
    CellStatus.DISSOLVED: frozenset(),
}


class CellTransitionError(ValueError):
    pass


class MissionCell(BaseModel):
    model_config = _FROZEN

    cell_id: str
    objective: str
    node_refs: tuple[str, ...]
    accountable_specialist: str | None
    contributor_specialists: tuple[str, ...]
    runtime_authority_binding: str
    work_order_refs: tuple[str, ...]
    context_capsule_ref: str | None
    input_refs: tuple[tuple[str, str], ...]
    output_contracts: tuple[str, ...]
    validators: tuple[str, ...]
    mutation_targets: tuple[str, ...]
    resource_locks: tuple[str, ...]
    risk_class: str
    side_effect_class: str
    approval_refs: tuple[str, ...]
    status: CellStatus
    blockers: tuple[str, ...]

    @property
    def cell_hash(self) -> str:
        return semantic_hash(self, exclude={"status"})


def advance_cell(cell: MissionCell, to: CellStatus) -> MissionCell:
    if to not in CELL_TRANSITIONS[cell.status]:
        raise CellTransitionError(f"{cell.cell_id}: {cell.status.value} -> {to.value} is not permitted")
    if to is CellStatus.READY and cell.blockers:
        raise CellTransitionError(f"{cell.cell_id}: cannot become READY with blockers {list(cell.blockers)}")
    return cell.model_copy(update={"status": to})


class Wave(BaseModel):
    model_config = _FROZEN

    index: int
    cells: tuple[str, ...]
    serialized_reason: str | None = None


class WavePlan(BaseModel):
    model_config = _FROZEN

    waves: tuple[Wave, ...]
    held: dict[str, tuple[str, ...]]
    wave_hash: str


def _critical_path(graph: CausalWorkGraph) -> dict[str, int]:
    """Longest downstream path length to any root (higher = more critical)."""
    forward = graph.dependents()
    memo: dict[str, int] = {}
    for nid in reversed(graph.topological_order):
        memo[nid] = 1 + max((memo[d] for d in forward.get(nid, ())), default=0)
    return memo


# Earlier lifecycle stages reduce more uncertainty downstream.
def _information_gain(stage: str | None) -> int:
    return 30 - int(stage[1:]) if stage else 0


def schedule_waves(
    graph: CausalWorkGraph,
    cells: Mapping[str, MissionCell],
    *,
    cell_for_node: Mapping[str, str],
) -> WavePlan:
    """Layer READY cells into waves; hold gated cells with reasons."""
    held: dict[str, tuple[str, ...]] = {c.cell_id: c.blockers for c in cells.values() if c.blockers}

    # Hold anything downstream of a held cell or of a non-work gate.
    def gates(cell: MissionCell) -> set[str]:
        reasons: set[str] = set()
        work_node = cell.node_refs[0]
        for anc in graph.ancestors(work_node):
            node = graph.nodes[anc]
            if node.type is NodeType.MATERIAL_DECISION and node.status.value == "AWAITING_HUMAN":
                reasons.add(f"WAIT_HUMAN_DECISION:{anc}")
            elif node.status.value == "BLOCKED":
                reasons.add(f"UPSTREAM_BLOCKED:{anc}")
            elif node.type is NodeType.EXECUTABLE_WORK or node.type is NodeType.EXTERNAL_ACTION:
                upstream = cell_for_node.get(anc)
                if upstream in held:
                    reasons.add(f"UPSTREAM_HELD:{upstream}")
        return reasons

    changed = True
    while changed:
        changed = False
        for cell in sorted(cells.values(), key=lambda c: c.cell_id):
            if cell.cell_id in held:
                continue
            reasons = gates(cell)
            if reasons:
                held[cell.cell_id] = tuple(sorted(reasons))
                changed = True

    critical = _critical_path(graph)
    descendants = {nid: len(graph.descendants([nid])) for nid in graph.nodes}
    runnable = {cid: c for cid, c in cells.items() if cid not in held}

    depth: dict[str, int] = {}
    for nid in graph.topological_order:
        cid = cell_for_node.get(nid)
        if cid not in runnable or graph.nodes[nid].type not in {NodeType.EXECUTABLE_WORK, NodeType.EXTERNAL_ACTION}:
            continue
        upstream = [cell_for_node[a] for a in graph.ancestors(nid)
                    if cell_for_node.get(a) in runnable and cell_for_node[a] != cid
                    and graph.nodes[a].type in {NodeType.EXECUTABLE_WORK, NodeType.EXTERNAL_ACTION}]
        depth[cid] = 1 + max((depth[u] for u in upstream), default=-1)

    def priority(cid: str) -> tuple:
        cell = runnable[cid]
        work = cell.node_refs[0]
        return (
            -critical.get(work, 0),
            -descendants.get(work, 0),
            -_information_gain(graph.nodes[work].stage),
            0 if cell.side_effect_class in {"PURE", "DRAFT"} else 1,
            cid,
        )

    waves: list[Wave] = []
    for level in sorted(set(depth.values())):
        members = sorted((cid for cid, d in depth.items() if d == level), key=priority)
        parallel: list[list[str]] = [[]]
        serial: list[tuple[str, str]] = []
        for cid in members:
            cell = runnable[cid]
            if cell.side_effect_class not in {"PURE", "DRAFT"}:
                serial.append((cid, "CONSEQUENTIAL_EXTERNAL_ACTION"))
                continue
            for bucket in parallel:
                locks = {lock for other in bucket for lock in runnable[other].resource_locks}
                if not (locks & set(cell.resource_locks)):
                    bucket.append(cid)
                    break
            else:
                parallel.append([cid])
        for i, bucket in enumerate(b for b in parallel if b):
            waves.append(Wave(index=len(waves), cells=tuple(bucket),
                              serialized_reason="RESOURCE_OR_MUTATION_COLLISION" if i else None))
        for cid, reason in serial:
            waves.append(Wave(index=len(waves), cells=(cid,), serialized_reason=reason))

    body = {"waves": [w.model_dump(mode="json") for w in waves], "held": {k: list(v) for k, v in sorted(held.items())}}
    return WavePlan(waves=tuple(waves), held=dict(sorted(held.items())), wave_hash=semantic_hash(body))


def build_cell(
    *,
    graph: CausalWorkGraph,
    work_node_id: str,
    accountable_specialist: str | None,
    contributor_specialists: Iterable[str],
    binding_hash: str,
    work_order_ids: Iterable[str],
    capsule_hash: str | None,
    validators: Iterable[str],
    resource_locks: Iterable[str],
    risk_class: str,
    approval_refs: Iterable[str],
    blockers: Iterable[str],
) -> MissionCell:
    node = graph.nodes[work_node_id]
    artifact = node.artifact_type
    refs = [work_node_id]
    for suffix in ("validate", "accept"):
        candidate = f"{suffix}:{artifact}"
        if artifact and candidate in graph.nodes and node.type is NodeType.EXECUTABLE_WORK:
            refs.append(candidate)
    blockers = tuple(sorted(set(blockers)))
    return MissionCell(
        cell_id=f"cell:{work_node_id.split(':', 1)[1]}" if node.type is NodeType.EXECUTABLE_WORK else f"cell:{work_node_id}",
        objective=node.purpose,
        node_refs=tuple(refs),
        accountable_specialist=accountable_specialist,
        contributor_specialists=tuple(sorted(set(contributor_specialists))),
        runtime_authority_binding=binding_hash,
        work_order_refs=tuple(sorted(work_order_ids)),
        context_capsule_ref=capsule_hash,
        input_refs=tuple(sorted((d, graph.nodes[d].semantic_hash) for d in node.hard_dependencies)),
        output_contracts=(artifact,) if artifact else (),
        validators=tuple(sorted(set(validators))),
        mutation_targets=node.mutation_targets,
        resource_locks=tuple(sorted(set(resource_locks))),
        risk_class=risk_class,
        side_effect_class=node.side_effect_class,
        approval_refs=tuple(sorted(set(approval_refs))),
        status=CellStatus.BLOCKED if blockers else CellStatus.FORMED,
        blockers=blockers,
    )
