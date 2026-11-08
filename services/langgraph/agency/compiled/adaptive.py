"""Pure structured-requirement preview over the canonical compiled planner.

No free-form brief inference, provider probes, persistence, dispatch or approval
creation. Unsupported projections are blocked as a whole: partial successful
lowering must never conceal omitted deliverables or unenforced dependencies.
"""
from __future__ import annotations

from graphlib import CycleError, TopologicalSorter

from services.langgraph.agency.kernel.ontology import ArtifactType
from services.langgraph.agency.role_os import RoleOSRegistry

from .adaptive_contract import (
    AdaptivePlanningRequest, AdaptivePlanningResult, CategoryRecord, StructuralChange,
)
from .backchain import DeliverableSpec
from .hashing import semantic_hash
from .planner import CompiledAgencyRequest, compile_agency_plan


def _unique(items, label: str) -> dict:
    indexed = {item.id: item for item in items}
    if len(indexed) != len(items):
        raise ValueError(f"duplicate {label} ids")
    return indexed


def _refs(refs, known, label: str) -> None:
    if len(refs) != len(set(refs)):
        raise ValueError(f"duplicate {label} references")
    missing = set(refs) - set(known)
    if missing:
        raise ValueError(f"unknown {label} references: {sorted(missing)}")


def _acyclic(edges: dict[str, set[str]], label: str) -> None:
    try:
        tuple(TopologicalSorter(edges).static_order())
    except CycleError as exc:
        raise ValueError(f"{label} contains a cycle") from exc


def derive_categories(request: AdaptivePlanningRequest) -> tuple[CategoryRecord, ...]:
    """Group by explicit structured hints, not a mandatory discipline catalog."""
    if request.categories:
        return tuple(category.model_copy(update={"requirement_ids": tuple(sorted(category.requirement_ids))})
                     for category in sorted(request.categories, key=lambda item: item.id))
    groups: dict[str, list[str]] = {}
    for requirement in request.requirements:
        groups.setdefault(requirement.category_hint, []).append(requirement.id)
    return tuple(CategoryRecord(
        id="category-" + semantic_hash(label)[:20], label=label,
        requirement_ids=tuple(sorted(refs)),
    ) for label, refs in sorted(groups.items()))


def _category_structure(categories, requirements, deliverables) -> None:
    known = _unique(categories, "category")
    edges: dict[str, set[str]] = {}
    for category in categories:
        _refs(category.requirement_ids, requirements, "category requirement")
        _refs((category.parent_id,) if category.parent_id else (), known, "parent category")
        edges[category.id] = {category.parent_id} if category.parent_id else set()
    _acyclic(edges, "category hierarchy")
    for item in deliverables:
        _refs(item.category_ids, known, "deliverable category")
        if any(not set(item.requirement_ids) & set(known[c].requirement_ids) for c in item.category_ids):
            raise ValueError("category membership must be justified by a source requirement")


def validate_structure(request: AdaptivePlanningRequest, categories: tuple[CategoryRecord, ...]) -> None:
    requirements = _unique(request.requirements, "requirement")
    deliverables = _unique(request.deliverables, "deliverable")
    for item in request.deliverables:
        _refs(item.requirement_ids, requirements, "deliverable requirement")
    _category_structure(categories, requirements, request.deliverables)
    edges: dict[str, set[str]] = {key: set() for key in deliverables}
    seen: set[tuple[str, str]] = set()
    for edge in request.dependencies:
        _refs((edge.upstream, edge.downstream), deliverables, "dependency endpoint")
        pair = (edge.upstream, edge.downstream)
        if pair in seen:
            raise ValueError("duplicate dependency")
        seen.add(pair)
        if edge.selected:
            edges[edge.downstream].add(edge.upstream)
    _acyclic(edges, "deliverable dependencies")


def _normalized(request: AdaptivePlanningRequest) -> dict:
    body = request.model_dump(mode="json")
    for name in ("requirements", "categories", "deliverables"):
        body[name].sort(key=lambda item: item["id"])
        for item in body[name]:
            for key in ("requirement_ids", "category_ids", "source_refs", "domains", "capability_requirements"):
                if key in item:
                    item[key] = sorted(item[key])
    body["dependencies"].sort(key=lambda item: (item["upstream"], item["downstream"]))
    body["ambiguities"].sort()
    return body


def _entities(request: AdaptivePlanningRequest) -> dict[tuple[str, str], str]:
    body = _normalized(request)
    body["categories"] = [c.model_dump(mode="json") for c in derive_categories(request)]
    out = {}
    for collection, kind in (("requirements", "requirement"), ("categories", "category"),
                             ("deliverables", "deliverable"), ("dependencies", "dependency")):
        for item in body[collection]:
            key = item.get("id") or f"{item['upstream']}->{item['downstream']}"
            out[(kind, key)] = semantic_hash(item)
    return out


def compare_structure(request: AdaptivePlanningRequest, previous: AdaptivePlanningRequest | None) -> tuple[StructuralChange, ...]:
    if previous is None:
        return ()
    if (request.project_id, request.plan_id, request.revision) != (
        previous.project_id, previous.plan_id, previous.revision + 1
    ):
        raise ValueError("revision must follow the same project and plan by exactly one")
    before, after = _entities(previous), _entities(request)
    changes = []
    for kind, key in sorted(before.keys() | after.keys()):
        old, new = before.get((kind, key)), after.get((kind, key))
        if old != new:
            changes.append(StructuralChange(kind="ADDED" if old is None else "REMOVED" if new is None else "CHANGED",
                                            entity=kind, id=key, previous_hash=old, current_hash=new))
    return tuple(changes)


def _proposal_blockers(request: AdaptivePlanningRequest) -> list[str]:
    blockers = [f"AMBIGUITY:{text}" for text in request.ambiguities]
    covered = {ref for item in request.deliverables for ref in item.requirement_ids}
    blockers += [f"UNSATISFIED_REQUIREMENT:{r.id}" for r in request.requirements if r.id not in covered]
    blockers += [f"CONFIRMATION_REQUIRED:{r.id}" for r in request.requirements if r.confirmation_required]
    types: dict[str, list[str]] = {}
    for item in request.deliverables:
        types.setdefault(item.output_contract, []).append(item.id)
        if item.external_action:
            blockers.append(f"EXTERNAL_OPERATION_NOT_AUTHORIZED:{item.id}")
        blockers += [f"CAPABILITY_BINDING_UNVERIFIED:{item.id}:{c}" for c in item.capability_requirements]
        try:
            ArtifactType(item.output_contract)
        except ValueError:
            blockers.append(f"UNSUPPORTED_OUTPUT_CONTRACT:{item.id}:{item.output_contract}")
    blockers += [f"UNSAFE_SAME_TYPE_COLLAPSE:{kind}:{','.join(sorted(ids))}"
                 for kind, ids in sorted(types.items()) if len(ids) > 1]
    return blockers


def _specs(request: AdaptivePlanningRequest) -> tuple[DeliverableSpec, ...]:
    requirements = {r.id: r for r in request.requirements}
    return tuple(DeliverableSpec(
        id=item.id, requested_outcome=item.purpose, output_contract=item.output_contract,
        acceptance_criteria=item.acceptance_criteria, constraints=item.constraints, domains=tuple(sorted(item.domains)),
        source_refs=tuple(sorted({ref for rid in item.requirement_ids for ref in requirements[rid].source_refs})),
    ) for item in sorted(request.deliverables, key=lambda item: item.id))


def lower_deliverables(request: AdaptivePlanningRequest, *, registry: RoleOSRegistry):
    validate_structure(request, derive_categories(request))
    blockers = _proposal_blockers(request)
    if blockers:
        return None, tuple(sorted(set(blockers)))
    plan = compile_agency_plan(CompiledAgencyRequest(
        project_id=request.project_id, as_of=request.as_of, deliverables=_specs(request),
    ), registry=registry)
    for edge in request.dependencies:
        if edge.selected and f"deliverable:{edge.upstream}" not in plan.graph.ancestors(f"deliverable:{edge.downstream}"):
            blockers.append(f"DEPENDENCY_NOT_REPRESENTABLE:{edge.upstream}->{edge.downstream}")
    # The legacy graph has no general instance-to-instance input binding. Keep
    # that limitation visible instead of adding an unenforced decorative edge.
    return (None if blockers else plan), tuple(sorted(set(blockers)))


def _grouped_deliverables(request: AdaptivePlanningRequest, categories: tuple[CategoryRecord, ...]):
    return tuple(item.model_copy(update={"category_ids": item.category_ids or tuple(
        category.id for category in categories if set(category.requirement_ids) & set(item.requirement_ids)
    )}) for item in sorted(request.deliverables, key=lambda item: item.id))


def compile_adaptive_plan(
    request: AdaptivePlanningRequest, *, registry: RoleOSRegistry,
    previous: AdaptivePlanningRequest | None = None,
) -> AdaptivePlanningResult:
    """Compile a preview, never an execution authorization or acceptance claim."""
    # Revalidate even Python model_copy/model_construct inputs: their convenience
    # APIs can bypass Pydantic validation. No bypass may create planner authority.
    request = AdaptivePlanningRequest.model_validate(request.model_dump(mode="json"))
    categories = derive_categories(request)
    validate_structure(request, categories)
    if previous is not None:
        previous = AdaptivePlanningRequest.model_validate(previous.model_dump(mode="json"))
        validate_structure(previous, derive_categories(previous))
    changes = compare_structure(request, previous)
    projection, blockers = lower_deliverables(request, registry=registry)
    return AdaptivePlanningResult(
        project_id=request.project_id, plan_id=request.plan_id, revision=request.revision,
        previous_revision_hash=semantic_hash(_normalized(previous)) if previous else None,
        content_hash=semantic_hash(_normalized(request)), status="BLOCKED" if blockers else "PREVIEW",
        categories=categories, requirements=tuple(sorted(request.requirements, key=lambda item: item.id)),
        deliverables=_grouped_deliverables(request, categories),
        dependencies=tuple(sorted(request.dependencies, key=lambda edge: (edge.upstream, edge.downstream))),
        changes=changes, lowering_blockers=blockers, compiled_projection=projection,
    )
