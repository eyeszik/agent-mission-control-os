"""MissionIR + registry + availability + budget -> ExecutionPlan.

Topology is the smallest that satisfies the mission:

- T0 deterministic transform (design system spec from tokens);
- T1 generator (interface spec, prompt-only visual/motion work);
- T2 generator + validator (one candidate, independent critics);
- T3 specialist composition (several generators feeding one artifact);
- T4 bounded candidate search, only when the mission justifies exploration
  (``wants_exploration``) *and* the budget allows more than one candidate.

The plan is a validated DAG with finite budgets, classified effects and the
human gates preserved. Specialists exist only as plan nodes for this run;
nothing persists after the plan is discarded.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.execution.canonical import canonical_hash

from .capabilities import RegistryLoad
from .ir import MissionIR
from .mission import wants_exploration

Topology = Literal["T0", "T1", "T2", "T3", "T4"]
TOPOLOGY_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NodeBudget(_Strict):
    max_calls: int = Field(ge=0, le=64)
    max_seconds: float = Field(gt=0, le=600)


class PlanNode(_Strict):
    node_id: str
    responsibility: str
    capability_ids: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    deps: tuple[str, ...]
    idempotency_class: Literal["RETRY_SAFE", "RETRY_SAFE_VERSIONED", "NON_RETRYABLE", "HUMAN"]
    budget: NodeBudget
    blocked_reason: Optional[str] = None


class SearchPolicy(_Strict):
    enabled: bool
    reason: str
    population_size: int = Field(ge=1, le=4)
    generations: int = Field(ge=1, le=2)
    mutation_budget: int = Field(ge=0, le=4)
    diversity_floor: float = Field(ge=0.0, le=1.0)
    correction_limit: int = Field(ge=0, le=1)
    model_call_cap: int = Field(ge=0, le=64)
    token_cap: int = Field(ge=0, le=32000)
    wall_clock_cap: float = Field(gt=0, le=600)


class ExecutionPlan(_Strict):
    plan_id: str
    mission_hash: str
    topology_class: Topology
    nodes: tuple[PlanNode, ...]
    edges: tuple[tuple[str, str], ...]
    validators: tuple[str, ...]
    search_policy: SearchPolicy
    degradation_policy: dict[str, str]
    approval_policy: dict[str, Any]
    status: Literal["READY", "BLOCKED"]
    blocked_reasons: tuple[str, ...] = ()
    plan_hash: str


class PlanInvalid(ValueError):
    pass


DEGRADATION_POLICY = {
    "corpus_invalid": "continue without corpus context; record DEGRADED; never invent guidance",
    "provider_unavailable": "stop the affected node with PROVIDER_UNAVAILABLE; no simulated output",
    "budget_exhausted": "terminate; retain validated work; HITL",
    "search_collapse": "replace the least distinct candidate once; then keep the front as is",
}


def _node(node_id, responsibility, caps, inputs, outputs, deps, idem, calls=0, seconds=10.0, blocked=None) -> PlanNode:
    return PlanNode(node_id=node_id, responsibility=responsibility, capability_ids=tuple(caps), inputs=tuple(inputs),
                    outputs=tuple(outputs), deps=tuple(deps), idempotency_class=idem,
                    budget=NodeBudget(max_calls=calls, max_seconds=seconds), blocked_reason=blocked)


def select_topology(mission: MissionIR, registry: RegistryLoad, brief_text: str = "") -> tuple[Topology, str]:
    t = mission.artifact_type
    if t == "design_system":
        return "T0", "deterministic token -> spec transform"
    if t in {"dashboard", "mobile_ui", "image", "illustration", "motion", "video", "social_post", "brand_identity", "design_handoff"}:
        return "T1", "single generator/compiler; no rendered-candidate comparison is possible in-repo"
    if t == "logo":
        return "T2", "deterministic mark plus independent SVG/brand validation"
    explore = wants_exploration(mission, brief_text)
    budget_ok = mission.resource_budget.max_candidates > 1
    search_ok = registry.usable("cap.search.pareto") and registry.usable("cap.concept.direction")
    if explore and budget_ok and search_ok:
        return "T4", "mission requests distinctiveness/exploration and the budget allows a bounded population"
    if t == "marketing_site":
        return "T3", "landing generator composed with the design-system specialist"
    reason = "single candidate with independent critics"
    if explore and not budget_ok:
        reason += "; exploration requested but max_candidates=1"
    elif explore and not search_ok:
        reason += "; exploration requested but search capability unavailable"
    return "T2", reason


_GENERATOR = {
    "landing_page": ("cap.landing.generate", "cap.landing.render"),
    "marketing_site": ("cap.landing.generate", "cap.landing.render", "cap.design_system.spec"),
    "logo": ("cap.logo.svg",),
    "design_system": ("cap.design_system.spec",),
    "dashboard": ("cap.interface.spec",),
    "mobile_ui": ("cap.interface.spec",),
    "image": ("cap.visual.prompt",),
    "illustration": ("cap.visual.prompt",),
    "motion": ("cap.motion.prompt",),
    "video": ("cap.motion.prompt",),
    "social_post": ("cap.social.draft",),
    "brand_identity": ("cap.brand.identity",),
    "design_handoff": ("cap.handoff.spec",),
}
_CRITICS = {
    "landing_page": ("cap.validate.constraints", "cap.critic.accessibility", "cap.critic.brand", "cap.critic.implementation",
                     "cap.critic.design", "cap.critic.content"),
    "logo": ("cap.validate.constraints", "cap.critic.brand"),
    "design_system": ("cap.validate.constraints", "cap.critic.brand"),
}
_CRITICS["marketing_site"] = _CRITICS["landing_page"]


def compile_plan(mission: MissionIR, registry: RegistryLoad, *, brief_text: str = "") -> ExecutionPlan:
    topology, reason = select_topology(mission, registry, brief_text)
    budget = mission.resource_budget
    gens = _GENERATOR[mission.artifact_type]
    critics = _CRITICS.get(mission.artifact_type, ())
    blocked: list[str] = []
    for cap_id in (*gens, *critics):
        cap = registry.capabilities.get(cap_id)
        if cap is None or not registry.usable(cap_id):
            why = registry.quarantined.get(cap_id) or registry.degraded.get(cap_id) or "DEPENDENCY_VOID"
            blocked.append(f"{why.split(':', 1)[0]}:{cap_id}")
        elif cap.status == "provider_gap":
            blocked.append(f"PROVIDER_UNAVAILABLE:{cap_id}:{','.join(cap.model_requirements)}")
        elif cap.status in {"blocked", "guidance_only"}:
            blocked.append(f"BLOCKED_EXTERNAL:{cap_id}:{cap.status}")
    if registry.status == "DEGRADED" and registry.errors:
        blocked += [f"CORPUS_INVALID:{e}" for e in registry.errors]

    population = 1
    if topology == "T4":
        population = min(budget.max_candidates, mission.exploration_policy.candidates_requested or budget.max_candidates, 4)
    search = SearchPolicy(
        enabled=topology == "T4", reason=reason, population_size=population,
        generations=min(budget.max_generations, 2) if topology == "T4" else 1,
        mutation_budget=population if topology == "T4" else 0,
        diversity_floor=0.35, correction_limit=budget.max_corrections,
        model_call_cap=budget.max_model_calls, token_cap=budget.context_token_budget,
        wall_clock_cap=budget.max_wall_clock_seconds,
    )

    nodes = [
        _node("intake", "validate MissionIR and hard/soft zoning", ["cap.mission.compile"], ["brief"], ["mission_ir"], [], "RETRY_SAFE"),
        _node("context", "rights-safe context portfolio", ["cap.context.portfolio"], ["mission_ir"], ["context_portfolio"], ["intake"], "RETRY_SAFE"),
    ]
    gen_deps = ["context"]
    if topology == "T4":
        nodes.append(_node("concepts", "materially different concept specs", ["cap.concept.direction"], ["mission_ir"], ["concept_specs"], ["context"], "RETRY_SAFE"))
        gen_deps = ["concepts"]
    nodes.append(_node("generate", f"produce {population} candidate(s)", gens, ["mission_ir", "context_portfolio"], ["candidates"], gen_deps,
                       "RETRY_SAFE_VERSIONED", calls=population, blocked=blocked[0] if blocked else None))
    last = "generate"
    if critics:
        nodes.append(_node("feasibility", "hard gate: remove infeasible candidates", ["cap.validate.constraints"], ["candidates"], ["feasible"], [last], "RETRY_SAFE"))
        nodes.append(_node("critique", "independent specialist critics (blind to lineage)", [c for c in critics if c != "cap.validate.constraints"],
                           ["feasible"], ["evaluations"], ["feasibility"], "RETRY_SAFE"))
        last = "critique"
    if topology == "T4":
        nodes.append(_node("pareto", "nondominated front over soft objectives", ["cap.search.pareto"], ["evaluations"], ["pareto_front"], [last], "RETRY_SAFE"))
        last = "pareto"
    if mission.approval_policy.require_human_selection and critics:
        nodes.append(_node("human_select", "human selects, requests variation, rejects all or returns to brief", [], ["pareto_front" if topology == "T4" else "evaluations"],
                           ["selection"], [last], "HUMAN"))
        last = "human_select"
    if critics:
        nodes.append(_node("correct", "<=1 smallest-scope correction of the selected candidate", list(gens[:1]), ["selection"], ["corrected"], [last], "RETRY_SAFE_VERSIONED"))
        nodes.append(_node("tridiff", "MissionIR/ArtifactIR/render semantic diff and revalidation", ["cap.diff.tri", *critics], ["corrected"], ["tri_diff"], ["correct"], "RETRY_SAFE"))
        last = "tridiff"
    nodes.append(_node("approval", "existing HITL approval bound to the artifact hash", [], ["artifact_hash"], ["approval"], [last], "HUMAN"))

    edges = tuple((d, n.node_id) for n in nodes for d in n.deps)
    body = {
        "mission_hash": mission.mission_hash, "topology_class": topology,
        "nodes": [n.model_dump(mode="json") for n in nodes], "edges": [list(e) for e in edges],
        "validators": list(critics), "search_policy": search.model_dump(mode="json"),
        "degradation_policy": DEGRADATION_POLICY,
        "approval_policy": mission.approval_policy.model_dump(mode="json"),
        "status": "BLOCKED" if blocked else "READY", "blocked_reasons": sorted(set(blocked)),
    }
    plan_hash = canonical_hash(body)
    plan = ExecutionPlan(plan_id=f"plan-{plan_hash[:16]}", mission_hash=mission.mission_hash, topology_class=topology,
                         nodes=tuple(nodes), edges=edges, validators=tuple(critics), search_policy=search,
                         degradation_policy=DEGRADATION_POLICY, approval_policy=body["approval_policy"],
                         status=body["status"], blocked_reasons=tuple(body["blocked_reasons"]), plan_hash=plan_hash)
    validate_plan(plan, registry)
    return plan


def validate_plan(plan: ExecutionPlan, registry: RegistryLoad) -> None:
    ids = [n.node_id for n in plan.nodes]
    if len(ids) != len(set(ids)):
        raise PlanInvalid("duplicate node ids")
    known = set(ids)
    for node in plan.nodes:
        if set(node.deps) - known:
            raise PlanInvalid(f"{node.node_id}: dependency not in plan {sorted(set(node.deps) - known)}")
        for cap in node.capability_ids:
            if cap not in registry.capabilities and plan.status == "READY":
                raise PlanInvalid(f"{node.node_id}: unknown capability {cap}")
    for a, b in plan.edges:
        if a not in known or b not in known:
            raise PlanInvalid(f"edge {a}->{b} references a node outside the plan")
    # Kahn's algorithm over the edges: a cycle leaves nodes unvisited.
    indegree = {n.node_id: 0 for n in plan.nodes}
    children: dict[str, list[str]] = {}
    for a, b in plan.edges:
        children.setdefault(a, []).append(b)
        indegree[b] += 1
    queue = sorted(n for n, d in indegree.items() if d == 0)
    seen = 0
    while queue:
        current = queue.pop(0)
        seen += 1
        for child in children.get(current, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if seen != len(ids):
        raise PlanInvalid("plan graph has a cycle")
    if set(plan.edges) != {(d, n.node_id) for n in plan.nodes for d in n.deps}:
        raise PlanInvalid("plan edges disagree with node dependencies")
    if plan.nodes[-1].node_id != "approval" or plan.nodes[-1].idempotency_class != "HUMAN":
        raise PlanInvalid("plan must end at the human approval gate")
    if plan.search_policy.enabled and plan.topology_class != "T4":
        raise PlanInvalid("search enabled outside T4")


__all__ = ["ExecutionPlan", "NodeBudget", "PlanInvalid", "PlanNode", "SearchPolicy", "TOPOLOGY_RANK", "Topology",
           "compile_plan", "select_topology", "validate_plan"]
