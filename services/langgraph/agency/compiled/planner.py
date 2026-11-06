"""Compiled Agency planner — composes every T04-T19 projection into one plan.

``compile_agency_plan`` is pure: no LLM call, no database write, no network,
no wall clock (``as_of`` is an input). Given the same canonical request, the
same sealed RoleOS registry and the same policy it returns the same
``plan_hash`` (spec §45 DETERMINISM).

It *plans* consequential actions but can never make one executable on its
own: external actions need a verified provider, an authority grant, an exact
approval and the N2 release guards, and publication/paid-media providers are
fail-closed in this repository.
"""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel, Field

from services.langgraph.agency.role_os import RoleOSRegistry, WorkOrderCompiler

from .authority import N3_SPECIALISTS, AuthorityBridge, AuthorityGrant, BindingStatus, SpecialistBinding, SpecialistQuery
from .autonomy import AutonomyDecision, classify, suitability_for_node
from .backchain import (
    CausalWorkGraph,
    DeliverableSpec,
    EvidenceItem,
    NodeStatus,
    NodeType,
    compile_backchain,
    unresolved_leaves,
)
from .change_control import ApprovalScope, ApprovalValidity, dependency_closure_hash, evaluate_scope
from .context import ContextCapsule, GenomeAssertion, capsule_freshness, hoist_shared_refs, project_capsule, project_genome
from .decisions import DecisionNode, DecisionSpine, uncertainty_priority
from .evidence import VolatileConstraint, volatile_release_blockers
from .execution import MissionCell, WavePlan, build_cell, schedule_waves
from .hashing import semantic_hash
from .ontology import select_overlays
from .role_sources import JITSkillLoader, RoleSourceIndex
from .validation import (
    PROFILES_BY_ID,
    ResultStatus,
    ValidationResult,
    evaluate_validation,
    release_blockers,
    volatile_keys_for,
)
from .work_orders import PCWO, compile_pcwo, risk_level_for

COMPILED_AGENCY_VERSION = "amc-compiled-agency/v1"
DEFAULT_POLICY_VERSION = "amc-approval/v1"
NODE_INVARIANT_DIMENSIONS = (
    "WHO", "WHY", "TRIGGER", "INPUT", "SOURCE", "EVIDENCE", "ACTION", "TOOL", "OUTPUT", "NEXT",
    "DEPENDENCY", "DECISION", "AUTHORITY", "AUTONOMY", "VALIDATION", "APPROVAL", "FAILURE", "RECOVERY", "PROVENANCE",
)


class CompiledAgencyRequest(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    project_id: str = Field(min_length=1, max_length=200)
    as_of: str = Field(min_length=10, max_length=40)
    deliverables: tuple[DeliverableSpec, ...] = Field(min_length=1, max_length=50)
    genome: tuple[GenomeAssertion, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    existing_artifacts: dict[str, str] = Field(default_factory=dict)
    decisions: tuple[DecisionNode, ...] = ()
    approvals: tuple[ApprovalScope, ...] = ()
    grants: tuple[AuthorityGrant, ...] = ()
    volatile_constraints: tuple[VolatileConstraint, ...] = ()
    validation_results: tuple[ValidationResult, ...] = ()
    generation_modes: dict[str, str] = Field(default_factory=dict)
    # action → "VERIFIED" only when a real provider adapter is installed and verified.
    provider_status: dict[str, str] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    policy_version: str = DEFAULT_POLICY_VERSION


class NodeCard(BaseModel):
    model_config = {"frozen": True}

    node_id: str
    dimensions: dict[str, Any]
    unresolved: tuple[str, ...]


class CompiledAgencyPlan(BaseModel):
    model_config = {"frozen": True}

    version: str
    project_id: str
    as_of: str
    registry_hash: str
    overlays: tuple[str, ...]
    genome_hash: str
    graph: CausalWorkGraph
    bindings: dict[str, SpecialistBinding]
    capsules: dict[str, ContextCapsule]
    shared_genome_refs: tuple[str, ...]
    work_orders: dict[str, PCWO]
    cells: dict[str, MissionCell]
    waves: WavePlan
    autonomy: dict[str, AutonomyDecision]
    executable: dict[str, bool]
    blocked: dict[str, tuple[str, ...]]
    human_gates: tuple[str, ...]
    release_readiness: dict[str, tuple[str, ...]]
    uncertainty_first: tuple[tuple[str, int], ...]
    activated_specialists: tuple[str, ...]
    dormant_specialist_count: int
    jit_skills: dict[str, str]
    node_cards: dict[str, NodeCard]
    plan_hash: str

    def summary(self) -> dict[str, Any]:
        by_level: dict[str, int] = {}
        for decision in self.autonomy.values():
            by_level[decision.level.value] = by_level.get(decision.level.value, 0) + 1
        return {
            "plan_hash": self.plan_hash,
            "nodes": len(self.graph.nodes),
            "work_nodes": len(self.work_orders),
            "cells": len(self.cells),
            "waves": len(self.waves.waves),
            "held_cells": len(self.waves.held),
            "dedup_hits": self.graph.dedup_hits,
            "activated_specialists": len(self.activated_specialists),
            "dormant_specialists": self.dormant_specialist_count,
            "human_gates": list(self.human_gates),
            "by_autonomy_level": dict(sorted(by_level.items())),
            "blocked_nodes": len(self.blocked),
            "release_ready": sorted(d for d, b in self.release_readiness.items() if not b),
        }


def _validators_for(obligations: Iterable[str], bridge: AuthorityBridge) -> list[str]:
    out: list[str] = []
    for ob in obligations:
        if ob.startswith("PROFILE:"):
            profile = PROFILES_BY_ID[ob.split(":", 1)[1]]
            role_id = bridge.resolve_specialist(SpecialistQuery(profile.validator_skill, profile.validator_department))
            out.append(role_id or f"CAPABILITY_GAP:{profile.validator_skill}")
    return sorted(set(out))


def compile_agency_plan(
    request: CompiledAgencyRequest,
    *,
    registry: RoleOSRegistry,
    source_index: RoleSourceIndex | None = None,
    jit_loader: JITSkillLoader | None = None,
) -> CompiledAgencyPlan:
    spine = DecisionSpine(request.decisions)
    accepted_decisions = spine.accepted_by_kind()
    graph = compile_backchain(
        request.deliverables,
        existing_artifacts=request.existing_artifacts,
        accepted_decisions=accepted_decisions,
        evidence=request.evidence,
    )
    if unresolved_leaves(graph):
        raise ValueError(f"unresolved backchain leaves: {unresolved_leaves(graph)}")

    domains = sorted({d for spec in request.deliverables for d in spec.domains})
    overlays = select_overlays(domains, live_service=any(s.live_service for s in request.deliverables))
    genome = project_genome(request.genome)

    source_hashes: dict[str, str] = {}
    bridge = AuthorityBridge(registry)
    if source_index is not None:
        resolved = {q.skill_name: bridge.resolve_specialist(q) for q in N3_SPECIALISTS.values()}
        for role_id in resolved.values():
            entry = source_index.get(role_id) if role_id else None
            if entry is not None:
                source_hashes[role_id] = entry.source_hash
        bridge = AuthorityBridge(registry, source_hashes=source_hashes)

    compiler = WorkOrderCompiler(registry)
    # Canonical order: deliverable input order must not change identity.
    mission_id = "mission-" + semantic_hash({
        "project": request.project_id,
        "deliverables": sorted(request.deliverables, key=lambda d: d.id),
    })[:20]
    current_hashes = {**{nid: n.semantic_hash for nid, n in graph.nodes.items()}, **request.artifact_hashes}

    bindings: dict[str, SpecialistBinding] = {}
    capsules: dict[str, ContextCapsule] = {}
    work_orders: dict[str, PCWO] = {}
    cells: dict[str, MissionCell] = {}
    cell_for_node: dict[str, str] = {}
    autonomy: dict[str, AutonomyDecision] = {}
    blocked: dict[str, tuple[str, ...]] = {}
    node_cards: dict[str, NodeCard] = {}
    forward = graph.dependents()

    roots_for: dict[str, set[str]] = {}
    for root in graph.roots:
        for anc in graph.ancestors(root) | {root}:
            roots_for.setdefault(anc, set()).add(root)
    spec_by_root = {f"deliverable:{s.id}": s for s in request.deliverables}

    for node in graph.work_nodes() + [n for n in graph.nodes.values() if n.type is NodeType.EXTERNAL_ACTION]:
        nid = node.id
        deliverable_refs = sorted(roots_for.get(nid, ()))
        is_external = node.type is NodeType.EXTERNAL_ACTION
        action = nid.split(":")[1] if is_external else "produce"
        target = node.mutation_targets[0] if node.mutation_targets else nid
        approval_refs = sorted(
            s.approval_id for s in request.approvals
            if (set(s.subject_refs) & ({nid} | set(deliverable_refs)))
            and evaluate_scope(
                s,
                current_subject_hashes=current_hashes,
                current_closure_hash=dependency_closure_hash(graph, s.subject_refs, request.artifact_hashes),
                current_policy_version=request.policy_version,
            ) is ApprovalValidity.VALID
        )
        binding = bridge.bind(
            runtime_role_id=node.runtime_role_id or "",
            side_effect_class=node.side_effect_class,
            operation=action,
            target=target,
            grants=request.grants,
            approval_refs=approval_refs,
            as_of=request.as_of,
        )
        bindings[nid] = binding

        validate_id = f"validate:{node.artifact_type}"
        obligations = graph.nodes[validate_id].validation_obligations if validate_id in graph.nodes and not is_external else node.validation_obligations
        validators = _validators_for(obligations, bridge)
        extra: list[str] = [v for v in validators if v.startswith("CAPABILITY_GAP")]
        extra += volatile_release_blockers(
            [c for c in request.volatile_constraints if c.key in volatile_keys_for(obligations)], request.as_of
        )
        missing_volatile = set(volatile_keys_for(obligations)) - {c.key for c in request.volatile_constraints}
        extra += [f"VOLATILE_UNVERIFIED:{k}" for k in sorted(missing_volatile)]
        if is_external:
            provider = request.provider_status.get(action)
            if provider != "VERIFIED":
                extra.append(f"PROVIDER_UNAVAILABLE:{action}")

        dep_hashes = {d: current_hashes[d] for d in node.hard_dependencies}
        capsule = project_capsule(
            genome,
            objective=node.purpose,
            acceptance_criteria=[c for r in deliverable_refs if r in spec_by_root for c in spec_by_root[r].acceptance_criteria],
            domains=node.domains,
            approved_decision_refs=[f"{k}@{h[:16]}" for k, h in accepted_decisions.items()],
            artifact_refs=[d for d in node.hard_dependencies if d.startswith(("ref:", "accept:"))],
            dependency_hashes=dep_hashes,
            hard_constraints=[c for r in deliverable_refs if r in spec_by_root for c in spec_by_root[r].constraints],
            authority_refs=[binding.binding_hash],
            tool_permissions=binding.permitted_tools,
        )
        if capsule_freshness(capsule, current_hashes).value != "FRESH":
            extra.append("INVALIDATED_CONTEXT")
        capsules[nid] = capsule

        ancestry = graph.ancestors(nid)
        decision_refs = sorted(a for a in ancestry | set(forward.get(nid, ())) if a.startswith("decision:"))
        evidence_reqs = sorted(
            b for a in ancestry | {f"evidence:{node.artifact_type}"} if a in graph.nodes for b in graph.nodes[a].blockers
        )
        pcwo, pcwo_blockers = compile_pcwo(
            compiler,
            project_id=request.project_id,
            mission_id=mission_id,
            node=node,
            binding=binding,
            deliverable_refs=deliverable_refs,
            acceptance_criteria=capsule.acceptance_criteria,
            validation_obligations=obligations,
            evidence_requirements=evidence_reqs,
            decision_refs=decision_refs,
            contributor_specialists=[v for v in validators if not v.startswith("CAPABILITY_GAP")],
            context_capsule_hash=capsule.capsule_hash,
            authority_refs=[g.grant_id for g in request.grants if g.target == target],
            approval_refs=approval_refs,
            approval_scope_hash=next((s.scope_hash for s in request.approvals if s.approval_id in approval_refs), None),
            extra_blockers=extra,
        )
        if pcwo is not None:
            work_orders[nid] = pcwo

        evidence_ok = not any(graph.nodes[a].type is NodeType.EVIDENCE_REQUIREMENT and graph.nodes[a].status is NodeStatus.BLOCKED
                              for a in ancestry | {f"evidence:{node.artifact_type}"} if a in graph.nodes)
        autonomy[nid] = classify(suitability_for_node(
            artifact_type=node.artifact_type,
            side_effect_class=node.side_effect_class,
            evidence_sufficient=evidence_ok,
            rights_uncertain=any(v.startswith("CAPABILITY_GAP") for v in validators),
        ))

        # Continuous validation of any results already reported for this node.
        if validate_id in graph.nodes and not is_external:
            verdict = evaluate_validation(
                validate_id, obligations, request.validation_results,
                creator_ref=binding.specialist_role_id or "", risk_level=risk_level_for(node), graph_nodes=graph.nodes,
            )
            if verdict.escalation:
                pcwo_blockers.append(verdict.escalation)
            pcwo_blockers += list(verdict.independence_violations)

        # §21 Executable(node): structural predicates that execution cannot discharge by itself.
        gating = sorted(
            f"WAIT_HUMAN_DECISION:{a}" if graph.nodes[a].type is NodeType.MATERIAL_DECISION else f"UPSTREAM_BLOCKED:{a}"
            for a in ancestry
            if graph.nodes[a].status in {NodeStatus.AWAITING_HUMAN, NodeStatus.BLOCKED}
        )
        all_blockers = tuple(sorted(set(pcwo_blockers) | set(gating) | ({"NO_VALID_PCWO"} if pcwo is None else set())))

        card = _node_card(node, binding, pcwo, capsule, autonomy[nid], obligations, forward, decision_refs, evidence_reqs,
                          source_hashes, registry.registry_hash)
        node_cards[nid] = card
        if card.unresolved:
            all_blockers = tuple(sorted(set(all_blockers) | {f"NODE_INVARIANT_UNRESOLVED:{d}" for d in card.unresolved}))
        if all_blockers:
            blocked[nid] = all_blockers

        cell = build_cell(
            graph=graph,
            work_node_id=nid,
            accountable_specialist=binding.specialist_role_id,
            contributor_specialists=[v for v in validators if not v.startswith("CAPABILITY_GAP")],
            binding_hash=binding.binding_hash,
            work_order_ids=[pcwo.work_order_id] if pcwo else [],
            capsule_hash=capsule.capsule_hash,
            validators=validators,
            resource_locks=pcwo.resource_locks if pcwo else node.mutation_targets,
            risk_class=risk_level_for(node),
            approval_refs=approval_refs,
            # Waiting on a human decision is scheduling state, not a cell defect.
            blockers=[b for b in all_blockers if not b.startswith(("WAIT_HUMAN_DECISION", "UPSTREAM_BLOCKED"))],
        )
        cells[cell.cell_id] = cell
        for ref in cell.node_refs:
            cell_for_node[ref] = cell.cell_id

    waves = schedule_waves(graph, cells, cell_for_node=cell_for_node)
    executable = {nid: nid not in blocked and cell_for_node.get(nid) not in waves.held for nid in work_orders}

    # Release readiness per deliverable, delegated to the N2 guards.
    release: dict[str, tuple[str, ...]] = {}
    for root in graph.roots:
        spec = spec_by_root[root]
        ancestry = graph.ancestors(root)
        modes = {request.generation_modes.get(graph.nodes[a].artifact_type or "") for a in ancestry | {root}}
        mode = "FALLBACK_DEGRADED" if "FALLBACK_DEGRADED" in modes else ("PROVIDER_SUCCESS" if "PROVIDER_SUCCESS" in modes else None)
        approved = [
            s for s in request.approvals
            if set(s.subject_refs) & {root, f"accept:{spec.output_contract}", f"ref:{spec.output_contract}"}
            and evaluate_scope(
                s,
                current_subject_hashes=current_hashes,
                current_closure_hash=dependency_closure_hash(graph, s.subject_refs, request.artifact_hashes),
                current_policy_version=request.policy_version,
            ) is ApprovalValidity.VALID
        ]
        results = [r for r in request.validation_results if r.node_id in ancestry and r.obligation == "PROFILE:BRAND_COHESION"]
        brand_ok: bool | None = None
        if results:
            brand_ok = all(r.status is ResultStatus.PASS for r in results)
        external = spec.external_action is not None
        ext_id = f"external:{spec.external_action.value}:{spec.id}" if external else None
        unmet = sorted(a for a in ancestry if graph.nodes[a].status is not NodeStatus.SATISFIED
                       # The external node *is* the release being gated; validation and
                       # acceptance nodes are derived from their producers.
                       and graph.nodes[a].type not in {NodeType.VALIDATION_OBLIGATION, NodeType.ACCEPTED_ARTIFACT,
                                                       NodeType.EXTERNAL_ACTION})
        codes = release_blockers(
            generation_mode=mode,
            approval_decision="approve" if approved else None,
            brand_safety_passed=brand_ok,
            external_side_effect=external,
            # N2's spend guard covers any spend/publication side effect; only a
            # fully resolved, provider-verified external node discharges it.
            spend_authorized=bool(external and ext_id not in blocked),
            unmet_hard_dependencies=unmet,
        )
        if external and ext_id in blocked:
            codes.append("external_action_blocked")
        release[root] = tuple(codes)

    human_gates = tuple(sorted(
        {n.id for n in graph.nodes.values() if n.type is NodeType.MATERIAL_DECISION and n.status is NodeStatus.AWAITING_HUMAN}
        | {f"approval:{r}" for r, codes in release.items() if "approval_missing" in codes}
        | {nid for nid, n in graph.nodes.items() if n.type is NodeType.EXTERNAL_ACTION}
    ))
    activated = tuple(sorted({b.specialist_role_id for b in bindings.values() if b.specialist_role_id}
                             | {c for cell in cells.values() for c in cell.contributor_specialists}))
    jit: dict[str, str] = {}
    if jit_loader is not None:
        for loaded in jit_loader.load_selected(activated):
            jit[loaded.role_id] = loaded.status.value

    body = {
        "version": COMPILED_AGENCY_VERSION,
        "project_id": request.project_id,
        "as_of": request.as_of,
        "registry_hash": registry.registry_hash,
        "overlays": overlays,
        "genome_hash": genome.genome_hash,
        "graph_hash": graph.graph_hash,
        "bindings": {k: v.binding_hash for k, v in sorted(bindings.items())},
        "capsules": {k: v.capsule_hash for k, v in sorted(capsules.items())},
        "work_orders": {k: v.work_order_hash for k, v in sorted(work_orders.items())},
        "cells": {k: v.cell_hash for k, v in sorted(cells.items())},
        "waves": waves.wave_hash,
        "blocked": {k: list(v) for k, v in sorted(blocked.items())},
        "release": {k: list(v) for k, v in sorted(release.items())},
    }
    return CompiledAgencyPlan(
        version=COMPILED_AGENCY_VERSION,
        project_id=request.project_id,
        as_of=request.as_of,
        registry_hash=registry.registry_hash,
        overlays=overlays,
        genome_hash=genome.genome_hash,
        graph=graph,
        bindings=bindings,
        capsules=capsules,
        shared_genome_refs=hoist_shared_refs(capsules.values()),
        work_orders=work_orders,
        cells=cells,
        waves=waves,
        autonomy=autonomy,
        executable=executable,
        blocked=blocked,
        human_gates=human_gates,
        release_readiness=release,
        uncertainty_first=tuple(uncertainty_priority(graph)),
        activated_specialists=activated,
        dormant_specialist_count=len(registry.roles) - len(activated),
        jit_skills=jit,
        node_cards=node_cards,
        plan_hash=semantic_hash(body),
    )


def _node_card(node, binding, pcwo, capsule, autonomy, obligations, forward, decision_refs, evidence_reqs,
               source_hashes, registry_hash) -> NodeCard:
    specialist = binding.specialist_role_id
    dims: dict[str, Any] = {
        "WHO": specialist,
        "WHY": list(node.satisfies),
        "TRIGGER": "all hard dependencies accepted" if node.hard_dependencies else "plan admitted",
        # A leaf's input is its context capsule; "no upstream artifact" is an answer.
        "INPUT": list(node.hard_dependencies) or [f"capsule:{capsule.capsule_hash[:16]}"],
        "SOURCE": source_hashes.get(specialist or "", f"roleos:{registry_hash}"),
        "EVIDENCE": list(evidence_reqs) or ["none required"],
        "ACTION": node.purpose,
        "TOOL": list(pcwo.tool_plan) if pcwo else [],
        "OUTPUT": node.artifact_type or (node.mutation_targets[0] if node.mutation_targets else None),
        "NEXT": sorted(forward.get(node.id, ())),
        "DEPENDENCY": list(node.dependencies) or ["none (leaf)"],
        "DECISION": decision_refs or ["none material"],
        "AUTHORITY": binding.binding_hash if binding.status is BindingStatus.RESOLVED else None,
        "AUTONOMY": autonomy.level.value,
        "VALIDATION": list(obligations),
        "APPROVAL": list(binding.approval_requirements) or ["none"],
        "FAILURE": "route to smallest causal producer",
        "RECOVERY": pcwo.idempotency_class if pcwo else None,
        "PROVENANCE": pcwo.work_order_id if pcwo else None,
    }
    unresolved = tuple(d for d in NODE_INVARIANT_DIMENSIONS if dims.get(d) in (None, [], ""))
    return NodeCard(node_id=node.id, dimensions=dims, unresolved=unresolved)
