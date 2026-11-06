"""Derived read models over a schedule and its execution report.

None of these owns state or grants anything; each is recomputable from the
planner output, the report and the stored artifacts:

* :func:`coverage_graph` — ContractRequirement → AcceptanceTest →
  MethodPlanNode → WorkOrder → Skill → ArtifactVersion → Validator. Any break in
  the planned chain is an orphan and the graph is ``PLAN_INCOMPLETE``.
* :func:`derive_envelope` — the autonomy envelope a cell actually ran (or would
  run) under. It is an intersection of canonical permissions and can only be
  narrower; :func:`envelope_within_canonical` proves it.
* :func:`cross_modal_witness` — every produced modality uses the brand
  capsule's palette (CIE76 delta-E) and names the brand consistently.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.execution.canonical import canonical_hash

from .capsules import BrandContextCapsule
from .consumer import MissionExecutionReport
from .contracts import ExecutionContext, ExecutionState
from .schedule import CellPlan, MissionSchedule
from .skills import ARTIFACT_SKILLS, FABRIC_SKILLS
from .verifiers import JND_DELTA_E, palette_conformance

_FROZEN = ConfigDict(extra="forbid", frozen=True)
_RANK = {"PURE": 0, "DRAFT": 1, "REVERSIBLE_WRITE": 2, "IRREVERSIBLE_WRITE": 3}
_CLASS = {v: k for k, v in _RANK.items()}

NodeKind = Literal["REQUIREMENT", "ACCEPTANCE_TEST", "PLAN_NODE", "WORK_ORDER", "SKILL", "ARTIFACT_VERSION", "VALIDATOR"]


class CoverageNode(BaseModel):
    model_config = _FROZEN

    id: str
    kind: NodeKind
    status: str


class ExecutionCoverageGraph(BaseModel):
    model_config = _FROZEN

    nodes: tuple[CoverageNode, ...]
    edges: tuple[tuple[str, str], ...]
    orphans: tuple[str, ...]
    status: Literal["COVERED", "EXECUTION_INCOMPLETE", "PLAN_INCOMPLETE"]
    executed_fraction: float
    graph_hash: str


def coverage_graph(schedule: MissionSchedule, report: MissionExecutionReport,
                   skill_overrides: Mapping[str, str] | None = None) -> ExecutionCoverageGraph:
    overrides = skill_overrides or {}
    nodes: dict[str, CoverageNode] = {}
    edges: set[tuple[str, str]] = set()
    orphans: list[str] = []

    def add(node_id: str, kind: NodeKind, status: str) -> str:
        nodes[node_id] = CoverageNode(id=node_id, kind=kind, status=status)
        return node_id

    for root in sorted(schedule.deliverables):
        req = add(f"req:{root}", "REQUIREMENT", "DECLARED")
        closure = sorted({schedule.cell_for_node[n] for n in schedule.graph.ancestors(root) | {root}
                          if n in schedule.cell_for_node})
        if not closure:
            orphans.append(f"{req}:NO_PLAN_NODE")
        for cid in closure:
            edges.add((req, f"plan:{schedule.cells[cid].node_id}"))
    for cid, cp in sorted(schedule.cells.items()):
        outcome = report.cells.get(cid)
        plan = add(f"plan:{cp.node_id}", "PLAN_NODE", outcome.state.value if outcome else "UNREPORTED")
        if cp.work_order_id is None:
            orphans.append(f"{plan}:NO_WORK_ORDER")
            continue
        wo = add(f"wo:{cp.work_order_id}", "WORK_ORDER", "READY" if cp.execution_ready else "BLOCKED")
        edges.add((plan, wo))
        skill_id = overrides.get(cp.node_id) or ARTIFACT_SKILLS.get(cp.artifact_type or "")
        spec = FABRIC_SKILLS.get(skill_id or "")
        if spec is None:
            orphans.append(f"{wo}:NO_SKILL")
            continue
        sk = add(f"skill:{skill_id}", "SKILL", spec.skill.side_effect_class)
        edges.add((wo, sk))
        if not spec.skill.validator_ids:
            orphans.append(f"{sk}:NO_ACCEPTANCE_TEST")
        for vid in spec.skill.validator_ids:
            test = add(f"test:{vid}", "ACCEPTANCE_TEST", "DECLARED")
            for root in schedule.deliverables:
                if cp.node_id in schedule.graph.ancestors(root) | {root}:
                    edges.add((f"req:{root}", test))
        if outcome and outcome.state is ExecutionState.SUCCEEDED:
            if not outcome.artifact_ref:
                orphans.append(f"{sk}:SUCCEEDED_WITHOUT_ARTIFACT")
                continue
            art = add(f"artifact:{outcome.artifact_ref}", "ARTIFACT_VERSION", "PERSISTED")
            edges.add((sk, art))
            for verdict in outcome.verdicts:
                v = add(f"validator:{outcome.artifact_ref}:{verdict['validator_id']}", "VALIDATOR",
                        "PASS" if verdict["passed"] else "FAIL")
                edges.add((art, v))
                edges.add((f"test:{verdict['validator_id']}", v))

    executed = sum(1 for o in report.cells.values() if o.state is ExecutionState.SUCCEEDED)
    fraction = round(executed / len(report.cells), 4) if report.cells else 0.0
    if orphans:
        status = "PLAN_INCOMPLETE"
    elif executed == len(schedule.cells):
        status = "COVERED"
    else:
        status = "EXECUTION_INCOMPLETE"
    body = {"nodes": sorted(n.model_dump(mode="json")["id"] for n in nodes.values()), "edges": sorted(edges), "orphans": sorted(orphans)}
    return ExecutionCoverageGraph(
        nodes=tuple(sorted(nodes.values(), key=lambda n: n.id)), edges=tuple(sorted(edges)), orphans=tuple(sorted(orphans)),
        status=status, executed_fraction=fraction, graph_hash=canonical_hash(body),
    )


class AutonomyEnvelope(BaseModel):
    model_config = _FROZEN

    cell_id: str
    max_side_effect_class: str
    authority_refs: tuple[str, ...]
    approval_refs: tuple[str, ...]
    tools: tuple[str, ...]
    network: Literal["NONE_REQUIRED", "ISOLATED", "PROVIDER"]
    live_external_actions: Literal[False] = False


def derive_envelope(cp: CellPlan, context: ExecutionContext, skill_id: str | None) -> AutonomyEnvelope:
    spec = FABRIC_SKILLS.get(skill_id or "")
    ranks = [_RANK.get(cp.side_effect_class, 3), _RANK["DRAFT"]]
    if spec is not None:
        ranks.append(_RANK[spec.skill.side_effect_class])
    network = "NONE_REQUIRED"
    if spec is not None and spec.skill.sandbox_requirement == "NETWORK_ISOLATED":
        network = "ISOLATED"
    elif spec is not None and spec.skill.provider_requirement:
        network = "PROVIDER"
    return AutonomyEnvelope(
        cell_id=cp.cell.cell_id,
        max_side_effect_class=_CLASS[min(ranks)],
        authority_refs=tuple(sorted(set(cp.authority_refs) & set(context.authority_refs))),
        approval_refs=tuple(sorted(set(cp.approval_refs) & set(context.approval_refs))),
        tools=(skill_id,) if spec is not None else (),
        network=network,
    )


def envelope_within_canonical(envelope: AutonomyEnvelope, cp: CellPlan, context: ExecutionContext) -> bool:
    return (
        _RANK[envelope.max_side_effect_class] <= _RANK.get(cp.side_effect_class, 3)
        and set(envelope.authority_refs) <= set(cp.authority_refs) & set(context.authority_refs)
        and set(envelope.approval_refs) <= set(cp.approval_refs) & set(context.approval_refs)
        and envelope.live_external_actions is False
    )


class CrossModalConsistencyWitness(BaseModel):
    model_config = _FROZEN

    capsule_hash: str
    tolerance_delta_e76: float
    artifacts: dict[str, dict[str, Any]]
    passed: bool
    witness_hash: str


def cross_modal_witness(capsule: BrandContextCapsule, contents: Mapping[str, str],
                        *, tolerance: float = JND_DELTA_E) -> CrossModalConsistencyWitness:
    """``contents`` maps an artifact ref to its text (SVG, CSS/JSON, HTML)."""
    results: dict[str, dict[str, Any]] = {}
    for ref, text in sorted(contents.items()):
        verdict = palette_conformance(text, capsule.palette.values(), tolerance=tolerance)
        results[ref] = {"palette": verdict.as_dict(), "names_brand": capsule.brand_name in text or "<svg" not in text}
    passed = bool(results) and all(r["palette"]["passed"] and r["names_brand"] for r in results.values())
    body = {"capsule": capsule.capsule_hash, "tolerance": tolerance, "artifacts": results, "passed": passed}
    return CrossModalConsistencyWitness(capsule_hash=capsule.capsule_hash, tolerance_delta_e76=tolerance,
                                        artifacts=results, passed=passed, witness_hash=canonical_hash(body))


__all__ = [
    "AutonomyEnvelope",
    "CrossModalConsistencyWitness",
    "ExecutionCoverageGraph",
    "coverage_graph",
    "cross_modal_witness",
    "derive_envelope",
    "envelope_within_canonical",
]
