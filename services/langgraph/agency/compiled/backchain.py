"""T10 — DeliverableBackchain compiling the Causal Work Graph (CWG).

Planning starts from what was requested, not from departments or phases:

    deliverable ← accepted artifact ← validation obligation ← executable work
                ← material decision ← evidence requirement ← prerequisite

Expansion is driven by the N3 role contracts: the role that ``produces`` an
artifact is its producer, and every artifact in that role's ``consumes`` set is
a hard prerequisite (N3 refuses dispatch when an upstream input is missing).
A prerequisite the caller already holds becomes a ``VALID_EXISTING_REF`` leaf
and is not re-produced, which is what keeps a copy-only job from waking the
research and strategy departments.

Every leaf resolves to VALID_EXISTING_REF, EXECUTABLE_WORK, HUMAN_DECISION or
EXPLICIT_BLOCKER. Anything that cannot be modelled (an output type N1 does not
know) becomes an explicit blocker instead of an invented artifact.
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import Iterable, Mapping

from pydantic import BaseModel, Field

from services.langgraph.agency.kernel.ontology import ArtifactType
from services.langgraph.agency.kernel.roles import ROLE_REGISTRY, RoleContract

from .hashing import semantic_hash
from .ontology import ARTIFACT_STAGE, STAGES_BY_ID
from .validation import obligations_for

_FROZEN = {"frozen": True, "extra": "forbid"}


class NodeType(str, Enum):
    DELIVERABLE = "DELIVERABLE"
    ACCEPTED_ARTIFACT = "ACCEPTED_ARTIFACT"
    VALIDATION_OBLIGATION = "VALIDATION_OBLIGATION"
    EXECUTABLE_WORK = "EXECUTABLE_WORK"
    MATERIAL_DECISION = "MATERIAL_DECISION"
    EVIDENCE_REQUIREMENT = "EVIDENCE_REQUIREMENT"
    EXISTING_REF = "EXISTING_REF"
    EXTERNAL_ACTION = "EXTERNAL_ACTION"
    BLOCKER = "BLOCKER"


class Resolution(str, Enum):
    VALID_EXISTING_REF = "VALID_EXISTING_REF"
    EXECUTABLE_WORK = "EXECUTABLE_WORK"
    HUMAN_DECISION = "HUMAN_DECISION"
    EXPLICIT_BLOCKER = "EXPLICIT_BLOCKER"
    DERIVED = "DERIVED"


class NodeStatus(str, Enum):
    SATISFIED = "SATISFIED"
    PLANNED = "PLANNED"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    BLOCKED = "BLOCKED"


class DecisionKind(str, Enum):
    SCOPE = "scope"
    COMMERCIAL_CONSTRAINT = "commercial_constraint"
    STRATEGY = "strategy"
    POSITIONING = "positioning"
    AUDIENCE = "audience"
    BRAND_PLATFORM = "brand_platform"
    CREATIVE_DIRECTION = "creative_direction"
    ARCHITECTURE = "architecture"
    MATERIAL_BUDGET = "material_budget"
    LEGAL_SECURITY_POLICY = "legal_security_policy"
    RELEASE_GO_NO_GO = "release_go_no_go"


# Only material choices enter the DecisionSpine (spec §26).
MATERIAL_DECISIONS: dict[ArtifactType, DecisionKind] = {
    ArtifactType.positioning_statement: DecisionKind.POSITIONING,
    ArtifactType.business_model_spec: DecisionKind.COMMERCIAL_CONSTRAINT,
    ArtifactType.brand_platform: DecisionKind.BRAND_PLATFORM,
    ArtifactType.creative_concept: DecisionKind.CREATIVE_DIRECTION,
    ArtifactType.implementation_plan: DecisionKind.ARCHITECTURE,
    ArtifactType.product_spec: DecisionKind.SCOPE,
    ArtifactType.media_plan: DecisionKind.MATERIAL_BUDGET,
    ArtifactType.release_record: DecisionKind.RELEASE_GO_NO_GO,
}


class ExternalAction(str, Enum):
    PUBLISH = "publish"
    DEPLOY = "deploy"
    DISTRIBUTE = "distribute"
    SEND = "send"
    PAY = "pay"
    PURCHASE = "purchase"
    MEDIA_SPEND = "media_spend"
    PRODUCTION_MIGRATION = "production_migration"
    DELETE = "delete"
    CREDENTIAL_MUTATION = "credential_mutation"
    CLIENT_BINDING_COMMITMENT = "client_binding_commitment"


RESEARCH_ARTIFACTS = frozenset({ArtifactType.research_brief, ArtifactType.market_analysis})
REVERSIBLE_ACTIONS = frozenset({ExternalAction.DEPLOY})
SPEND_ACTIONS = frozenset({ExternalAction.PAY, ExternalAction.PURCHASE, ExternalAction.MEDIA_SPEND})
# N3 role whose contract declares ``external_side_effect`` for the action.
EXTERNAL_ACTION_ROLE: dict[ExternalAction, str] = {
    **{a: "release_manager" for a in ExternalAction},
    **{a: "media_planner" for a in SPEND_ACTIONS},
}


class DeliverableSpec(BaseModel):
    model_config = _FROZEN

    id: str
    requested_outcome: str
    output_contract: str
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    required_approvals: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    priority: int | None = None
    source_refs: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    external_action: ExternalAction | None = None
    live_service: bool = False


class EvidenceItem(BaseModel):
    model_config = _FROZEN

    ref: str
    supports: tuple[str, ...]
    verified: bool = False


class BackchainNode(BaseModel):
    model_config = _FROZEN

    id: str
    type: NodeType
    purpose: str
    satisfies: tuple[str, ...]
    dependencies: tuple[str, ...]
    hard_dependencies: tuple[str, ...]
    soft_dependencies: tuple[str, ...] = ()
    phase_compatibility: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    validation_obligations: tuple[str, ...] = ()
    side_effect_class: str = "PURE"
    mutation_targets: tuple[str, ...] = ()
    status: NodeStatus
    resolution: Resolution
    artifact_type: str | None = None
    runtime_role_id: str | None = None
    stage: str | None = None
    domains: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    semantic_hash: str


class BackchainCycleError(ValueError):
    pass


class CausalWorkGraph(BaseModel):
    model_config = _FROZEN

    nodes: dict[str, BackchainNode]
    roots: tuple[str, ...]
    topological_order: tuple[str, ...]
    eliminated: tuple[str, ...]
    redundant_candidates: tuple[str, ...]
    dedup_hits: int
    graph_hash: str

    def dependents(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {nid: set() for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.dependencies:
                out.setdefault(dep, set()).add(node.id)
        return out

    def descendants(self, refs: Iterable[str]) -> set[str]:
        """Causal closure downstream of ``refs`` (nodes that depend on them)."""
        forward = self.dependents()
        seen: set[str] = set()
        queue = deque(r for r in refs if r in self.nodes)
        while queue:
            current = queue.popleft()
            for nxt in forward.get(current, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    def ancestors(self, ref: str) -> set[str]:
        seen: set[str] = set()
        queue = deque([ref])
        while queue:
            node = self.nodes.get(queue.popleft())
            if node is None:
                continue
            for dep in node.dependencies:
                if dep not in seen:
                    seen.add(dep)
                    queue.append(dep)
        return seen

    def work_nodes(self) -> list[BackchainNode]:
        return [self.nodes[n] for n in self.topological_order if self.nodes[n].type is NodeType.EXECUTABLE_WORK]


def producer_for(artifact_type: ArtifactType) -> RoleContract | None:
    producers = sorted((r for r in ROLE_REGISTRY.values() if artifact_type in r.produces), key=lambda r: r.role_id)
    return producers[0] if producers else None


class _Builder:
    def __init__(
        self,
        *,
        existing_artifacts: Mapping[str, str],
        accepted_decisions: Mapping[str, str],
        evidence: Iterable[EvidenceItem],
    ):
        self.existing = dict(existing_artifacts)
        self.accepted_decisions = dict(accepted_decisions)
        self.evidence = tuple(evidence)
        self.nodes: dict[str, dict] = {}
        self.dedup_hits = 0
        self._expanding: set[str] = set()

    def add(self, node_id: str, **fields) -> str:
        if node_id in self.nodes:
            self.dedup_hits += 1
            existing = self.nodes[node_id]
            existing["satisfies"] = tuple(sorted(set(existing["satisfies"]) | set(fields.get("satisfies", ()))))
            existing["domains"] = tuple(sorted(set(existing["domains"]) | set(fields.get("domains", ()))))
            return node_id
        fields.setdefault("soft_dependencies", ())
        fields.setdefault("domains", ())
        fields["hard_dependencies"] = tuple(sorted(set(fields.get("hard_dependencies", ()))))
        self.nodes[node_id] = {"id": node_id, **fields}
        return node_id

    def accepted(self, artifact: ArtifactType, satisfies: str, domains: tuple[str, ...], live: bool) -> str:
        """Return the node id that proves ``artifact`` is available as an accepted input."""
        key = artifact.value
        if key in self.existing:
            return self.add(
                f"ref:{key}",
                type=NodeType.EXISTING_REF,
                purpose=f"Existing accepted {key} (content hash {self.existing[key][:12]})",
                satisfies=(satisfies,),
                hard_dependencies=(),
                status=NodeStatus.SATISFIED,
                resolution=Resolution.VALID_EXISTING_REF,
                artifact_type=key,
                domains=domains,
            )
        producer = producer_for(artifact)
        if producer is None:
            return self.blocker("NO_N3_PRODUCER", key, satisfies)
        accept_id = f"accept:{key}"
        if accept_id in self.nodes:
            return self.add(accept_id, satisfies=(satisfies,), domains=domains)

        if key in self._expanding:
            raise BackchainCycleError(f"N3 consumes/produces cycle through {key}")
        self._expanding.add(key)
        inputs = [self.accepted(c, f"work:{key}", domains, live) for c in sorted(producer.consumes, key=lambda a: a.value)]
        self._expanding.discard(key)
        stage = ARTIFACT_STAGE[artifact]
        work_id = self.add(
            f"work:{key}",
            type=NodeType.EXECUTABLE_WORK,
            purpose=f"Produce {key} ({producer.mandate})",
            satisfies=(f"validate:{key}",),
            hard_dependencies=tuple(inputs),
            phase_compatibility=(STAGES_BY_ID[stage].roleos_phase,),
            required_capabilities=tuple(sorted(c.value for c in producer.capabilities)),
            side_effect_class="DRAFT",
            mutation_targets=(f"artifact:{key}",),
            status=NodeStatus.PLANNED,
            resolution=Resolution.EXECUTABLE_WORK,
            artifact_type=key,
            runtime_role_id=producer.role_id,
            stage=stage,
            domains=domains,
        )
        validate_deps = [work_id]
        if producer.min_evidence:
            research_upstream = artifact in RESEARCH_ARTIFACTS or bool(
                {f"work:{r.value}" for r in RESEARCH_ARTIFACTS} & self.raw_ancestors(work_id)
            )
            validate_deps.append(self.evidence_node(artifact, producer.min_evidence, domains, research_upstream))
        validate_id = self.add(
            f"validate:{key}",
            type=NodeType.VALIDATION_OBLIGATION,
            purpose=f"Validate {key} against its obligations",
            satisfies=(accept_id,),
            hard_dependencies=tuple(validate_deps),
            validation_obligations=obligations_for(artifact, domains, live_service=live),
            status=NodeStatus.PLANNED,
            resolution=Resolution.DERIVED,
            artifact_type=key,
            stage="S17" if stage < "S17" else stage,
            domains=domains,
        )
        accept_deps = [validate_id]
        kind = MATERIAL_DECISIONS.get(artifact)
        if kind is not None:
            accept_deps.append(self.decision_node(kind, work_id, accept_id, domains))
        return self.add(
            accept_id,
            type=NodeType.ACCEPTED_ARTIFACT,
            purpose=f"Accepted {key}",
            satisfies=(satisfies,),
            hard_dependencies=tuple(accept_deps),
            status=NodeStatus.PLANNED,
            resolution=Resolution.DERIVED,
            artifact_type=key,
            runtime_role_id=producer.role_id,
            domains=domains,
        )

    def raw_ancestors(self, node_id: str) -> set[str]:
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            raw = self.nodes.get(stack.pop())
            for dep in (raw or {}).get("hard_dependencies", ()):
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        return seen

    def evidence_node(self, artifact: ArtifactType, floor: int, domains: tuple[str, ...], research_upstream: bool) -> str:
        """Evidence floor for accepting ``artifact``.

        A deficit that planned research work can still discharge is pending
        work (AWAITING_EVIDENCE); one with no research producer in its causal
        ancestry is an explicit blocker — nothing in the plan could supply it.
        """
        have = sum(1 for e in self.evidence if e.verified and artifact.value in e.supports)
        ok = have >= floor
        if ok:
            status, resolution, blockers = NodeStatus.SATISFIED, Resolution.VALID_EXISTING_REF, ()
        elif research_upstream:
            status, resolution = NodeStatus.PLANNED, Resolution.EXECUTABLE_WORK
            blockers = (f"AWAITING_EVIDENCE:{artifact.value}:{have}/{floor}",)
        else:
            status, resolution = NodeStatus.BLOCKED, Resolution.EXPLICIT_BLOCKER
            blockers = (f"EVIDENCE_DEFICIT:{artifact.value}:{have}/{floor}",)
        return self.add(
            f"evidence:{artifact.value}",
            type=NodeType.EVIDENCE_REQUIREMENT,
            purpose=f"At least {floor} verified evidence items supporting {artifact.value} (have {have})",
            satisfies=(f"validate:{artifact.value}",),
            hard_dependencies=(),
            status=status,
            resolution=resolution,
            artifact_type=artifact.value,
            blockers=blockers,
            domains=domains,
        )

    def decision_node(self, kind: DecisionKind, work_id: str, accept_id: str, domains: tuple[str, ...]) -> str:
        accepted = kind.value in self.accepted_decisions
        return self.add(
            f"decision:{kind.value}",
            type=NodeType.MATERIAL_DECISION,
            purpose=f"Material {kind.value} decision over produced options",
            satisfies=(accept_id,),
            hard_dependencies=(work_id,),
            status=NodeStatus.SATISFIED if accepted else NodeStatus.AWAITING_HUMAN,
            resolution=Resolution.VALID_EXISTING_REF if accepted else Resolution.HUMAN_DECISION,
            domains=domains,
        )

    def blocker(self, code: str, subject: str, satisfies: str) -> str:
        return self.add(
            f"blocker:{code}:{subject}",
            type=NodeType.BLOCKER,
            purpose=f"{code} for {subject}",
            satisfies=(satisfies,),
            hard_dependencies=(),
            status=NodeStatus.BLOCKED,
            resolution=Resolution.EXPLICIT_BLOCKER,
            blockers=(f"{code}:{subject}",),
        )

    def deliverable(self, spec: DeliverableSpec) -> str:
        root = f"deliverable:{spec.id}"
        domains = tuple(sorted(spec.domains))
        try:
            artifact = ArtifactType(spec.output_contract)
        except ValueError:
            dep = self.blocker("ARTIFACT_TYPE_UNMODELED", spec.output_contract, root)
        else:
            dep = self.accepted(artifact, root, domains, spec.live_service)
        deps = [dep]
        if spec.external_action is not None:
            deps = [self.external_node(spec, dep, domains)]
        return self.add(
            root,
            type=NodeType.DELIVERABLE,
            purpose=spec.requested_outcome,
            satisfies=(),
            hard_dependencies=tuple(deps),
            status=NodeStatus.PLANNED,
            resolution=Resolution.DERIVED,
            artifact_type=spec.output_contract,
            domains=domains,
        )

    def external_node(self, spec: DeliverableSpec, accepted_id: str, domains: tuple[str, ...]) -> str:
        action = spec.external_action
        assert action is not None
        side_effect = "REVERSIBLE_WRITE" if action in REVERSIBLE_ACTIONS else "IRREVERSIBLE_WRITE"
        deps = [accepted_id]
        # A consequential launch needs the release record chain (QA → release).
        if action not in SPEND_ACTIONS:
            deps.append(self.accepted(ArtifactType.release_record, f"external:{action.value}:{spec.id}", domains, spec.live_service))
        role = ROLE_REGISTRY[EXTERNAL_ACTION_ROLE[action]]
        return self.add(
            f"external:{action.value}:{spec.id}",
            type=NodeType.EXTERNAL_ACTION,
            purpose=f"{action.value} {spec.output_contract} externally (P12, distinct from P11 acceptance)",
            satisfies=(f"deliverable:{spec.id}",),
            hard_dependencies=tuple(deps),
            phase_compatibility=("P12",),
            required_capabilities=tuple(sorted(c.value for c in role.capabilities)),
            validation_obligations=obligations_for(ArtifactType.release_record, domains, external_action=True, live_service=spec.live_service),
            side_effect_class=side_effect,
            mutation_targets=(f"external:{action.value}",),
            status=NodeStatus.PLANNED,
            resolution=Resolution.EXECUTABLE_WORK,
            runtime_role_id=role.role_id,
            stage="S18",
            domains=domains,
        )


def _finalize(raw: dict) -> BackchainNode:
    body = dict(raw)
    body["dependencies"] = tuple(sorted(set(body["hard_dependencies"]) | set(body.get("soft_dependencies", ()))))
    body.setdefault("blockers", ())
    semantic = {k: v for k, v in body.items() if k not in {"purpose"}}
    return BackchainNode(**body, semantic_hash=semantic_hash(semantic))


def _topological(nodes: Mapping[str, BackchainNode]) -> tuple[str, ...]:
    indegree = {nid: 0 for nid in nodes}
    forward: dict[str, list[str]] = {nid: [] for nid in nodes}
    for node in nodes.values():
        for dep in node.dependencies:
            if dep not in nodes:
                raise BackchainCycleError(f"{node.id} depends on unknown node {dep}")
            indegree[node.id] += 1
            forward[dep].append(node.id)
    ready = sorted(nid for nid, d in indegree.items() if d == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for nxt in sorted(forward[current]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort()
    if len(order) != len(nodes):
        raise BackchainCycleError("causal work graph contains a cycle: " + ", ".join(sorted(set(nodes) - set(order))))
    return tuple(order)


def _reachable(nodes: Mapping[str, BackchainNode], roots: Iterable[str], *, hard_only: bool) -> set[str]:
    seen: set[str] = set()
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in seen or current not in nodes:
            continue
        seen.add(current)
        node = nodes[current]
        queue.extend(node.hard_dependencies if hard_only else node.dependencies)
    return seen


def compile_backchain(
    deliverables: Iterable[DeliverableSpec],
    *,
    existing_artifacts: Mapping[str, str] | None = None,
    accepted_decisions: Mapping[str, str] | None = None,
    evidence: Iterable[EvidenceItem] = (),
) -> CausalWorkGraph:
    """NORMALIZE → EXPAND(+CSE) → DEDUP → DEAD/ORPHAN ELIMINATION → CYCLE CHECK → NECESSITY."""
    specs = sorted(deliverables, key=lambda d: d.id)  # NORMALIZE
    if not specs:
        raise ValueError("at least one DeliverableSpec is required")
    if len({s.id for s in specs}) != len(specs):
        raise ValueError("deliverable ids must be unique")
    builder = _Builder(
        existing_artifacts=existing_artifacts or {},
        accepted_decisions=accepted_decisions or {},
        evidence=evidence,
    )
    roots = tuple(builder.deliverable(spec) for spec in specs)  # EXPAND with CSE by canonical id
    finalized = {nid: _finalize(raw) for nid, raw in builder.nodes.items()}

    live = _reachable(finalized, roots, hard_only=False)  # DEAD_NODE / ORPHAN elimination
    eliminated = tuple(sorted(set(finalized) - live))
    kept = {nid: finalized[nid] for nid in sorted(live)}
    order = _topological(kept)  # CYCLE_CHECK
    hard_live = _reachable(kept, roots, hard_only=True)  # COUNTERFACTUAL_NECESSITY
    redundant = tuple(sorted(set(kept) - hard_live))

    graph_hash = semantic_hash({
        "roots": roots,
        "nodes": {nid: n.semantic_hash for nid, n in kept.items()},
    })
    return CausalWorkGraph(
        nodes=kept,
        roots=roots,
        topological_order=order,
        eliminated=eliminated,
        redundant_candidates=redundant,
        dedup_hits=builder.dedup_hits,
        graph_hash=graph_hash,
    )


def unresolved_leaves(graph: CausalWorkGraph) -> list[str]:
    """Leaves must resolve to one of the four terminal resolutions."""
    allowed = {Resolution.VALID_EXISTING_REF, Resolution.EXECUTABLE_WORK, Resolution.HUMAN_DECISION, Resolution.EXPLICIT_BLOCKER}
    return sorted(n.id for n in graph.nodes.values() if not n.dependencies and n.resolution not in allowed)
