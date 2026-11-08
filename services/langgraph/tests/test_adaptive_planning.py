"""Local-only adaptive previews; no providers, storage or execution fixtures."""
from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.langgraph.agency.compiled.adaptive import compile_adaptive_plan
from services.langgraph.agency.compiled.adaptive_contract import AdaptivePlanningRequest
from services.langgraph.agency.compiled.backchain import DeliverableSpec, compile_backchain
from services.langgraph.agency.compiled.planner import CompiledAgencyRequest, compile_agency_plan
from services.langgraph.agency.role_os import RoleOSRegistry

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def registry():
    return RoleOSRegistry(ROOT / "runtime" / "role_os")


def minimal(**updates):
    body = {
        "project_id": "project-a", "plan_id": "launch", "as_of": "2026-11-07T00:00:00Z",
        "requirements": [{"id": "r1", "purpose": "Draft one copy asset", "source_refs": ["brief:paragraph-1"]}],
        "deliverables": [{"id": "copy-a", "purpose": "Draft one copy asset", "requirement_ids": ["r1"],
                          "output_contract": "copy_variant", "acceptance_criteria": ["Exact supplied product name"]}],
    }
    return {**body, **updates}


def compile_body(body, registry, **kwargs):
    return compile_adaptive_plan(AdaptivePlanningRequest.model_validate(body), registry=registry, **kwargs)


def complex_brief():
    body = minimal()
    body["requirements"] = [
        {"id": f"r{i}", "purpose": purpose, "source_refs": [f"brief:{i}"], "category_hint": group}
        for i, (purpose, group) in enumerate([
            ("Establish brand", "Foundation"), ("Specify website", "Experience"),
            ("Launch campaign", "Launch"), ("Write supporting copy", "Launch"),
        ], 1)
    ]
    body["deliverables"] = [
        {"id": key, "purpose": key, "requirement_ids": [f"r{i}"], "output_contract": output,
         "acceptance_criteria": ["Meets source requirement"]}
        for i, (key, output) in enumerate([
            ("brand", "brand_platform"), ("site", "app_build_spec"),
            ("campaign", "campaign_package"), ("copy", "copy_variant"),
        ], 1)
    ]
    return body


def test_minimal_is_a_preview_of_the_canonical_plan(registry):
    result = compile_body(minimal(), registry)
    expected = compile_agency_plan(CompiledAgencyRequest(
        project_id="project-a", as_of="2026-11-07T00:00:00Z",
        deliverables=(DeliverableSpec(id="copy-a", requested_outcome="Draft one copy asset",
                                     output_contract="copy_variant", acceptance_criteria=("Exact supplied product name",),
                                     source_refs=("brief:paragraph-1",)),),
    ), registry=registry)
    assert result.status == "PREVIEW"
    assert len(result.categories) == len(result.deliverables) == 1
    assert result.compiled_projection.plan_hash == expected.plan_hash
    assert not result.execution_authorized
    assert result.runtime_readiness == "NOT_TESTED"
    assert result.compiled_projection.human_gates  # prerequisites were not fabricated


def test_multidisciplinary_structure_preserves_shared_canonical_work(registry):
    result = compile_body(complex_brief(), registry)
    assert result.status == "PREVIEW"
    assert len(result.categories) == 3 and len(result.deliverables) == 4
    assert result.compiled_projection.graph.dedup_hits > 0
    assert list(result.compiled_projection.graph.nodes).count("work:research_brief") == 1
    for item in result.deliverables:
        assert set(item.requirement_ids) <= {r.id for r in result.requirements}


@pytest.mark.parametrize("count", [1, 2, 7, 16])
def test_categories_come_only_from_justified_hints(registry, count):
    body = minimal()
    body["requirements"] = [{"id": f"r{i}", "purpose": f"Need {i}", "source_refs": [f"brief:{i}"],
                             "category_hint": f"Special discipline {i}"} for i in range(count)]
    body["deliverables"][0]["requirement_ids"] = [f"r{i}" for i in range(count)]
    result = compile_body(body, registry)
    assert len(result.categories) == count


def test_category_rename_merge_split_preserves_production_identity(registry):
    body = minimal()
    body["categories"] = [{"id": "c1", "label": "First grouping", "requirement_ids": ["r1"]}]
    body["deliverables"][0]["category_ids"] = ["c1"]
    previous = AdaptivePlanningRequest.model_validate(body)
    initial = compile_adaptive_plan(previous, registry=registry)
    for revision, categories in enumerate([
        [{"id": "c1", "label": "Renamed", "requirement_ids": ["r1"]}],
        [{"id": "c1", "label": "Part A", "requirement_ids": ["r1"]},
         {"id": "c2", "label": "Part B", "requirement_ids": ["r1"], "parent_id": "c1"}],
        [{"id": "merged", "label": "Together", "requirement_ids": ["r1"]}],
    ], 2):
        body = {**body, "revision": revision, "categories": categories}
        body["deliverables"][0]["category_ids"] = [c["id"] for c in categories]
        current = AdaptivePlanningRequest.model_validate(body)
        result = compile_adaptive_plan(current, registry=registry, previous=previous)
        assert result.compiled_projection.plan_hash == initial.compiled_projection.plan_hash
        assert result.deliverables[0].id == "copy-a"
        assert result.previous_revision_hash and result.changes
        previous = current


def test_reordered_collections_hash_identically(registry):
    body = complex_brief()
    first = compile_body(body, registry)
    body["requirements"].reverse()
    body["deliverables"].reverse()
    second = compile_body(body, registry)
    assert first.content_hash == second.content_hash
    assert first.compiled_projection.plan_hash == second.compiled_projection.plan_hash


@pytest.mark.parametrize("mutation,match", [
    ("duplicate_id", "duplicate deliverable"), ("missing_requirement", "unknown deliverable requirement"),
    ("missing_dependency", "unknown dependency endpoint"), ("self_dependency", "duplicate dependency endpoint"),
    ("cycle", "contains a cycle"), ("category_cycle", "contains a cycle"),
    ("unjustified_membership", "justified"),
])
def test_invalid_structures_are_rejected(registry, mutation, match):
    body = complex_brief()
    if mutation == "duplicate_id":
        body["deliverables"].append(body["deliverables"][0])
    elif mutation == "missing_requirement":
        body["deliverables"][0]["requirement_ids"] = ["missing"]
    elif mutation in {"missing_dependency", "self_dependency", "cycle"}:
        target = "missing" if mutation == "missing_dependency" else "brand" if mutation == "self_dependency" else "site"
        body["dependencies"] = [{"upstream": "brand", "downstream": target}]
        if mutation == "cycle":
            body["dependencies"].append({"upstream": "site", "downstream": "brand"})
    else:
        body["categories"] = [{"id": "c1", "label": "One", "requirement_ids": ["r1"]}]
        if mutation == "category_cycle":
            body["categories"][0]["parent_id"] = "c1"
        else:
            body["deliverables"][1]["category_ids"] = ["c1"]
    with pytest.raises(ValueError, match=match):
        compile_body(body, registry)


def test_distinct_same_type_outputs_never_silently_collapse(registry):
    body = minimal()
    body["deliverables"].append({**body["deliverables"][0], "id": "copy-b", "purpose": "A different email"})
    result = compile_body(body, registry)
    assert result.compiled_projection is None and len(result.deliverables) == 2
    assert any(b.startswith("UNSAFE_SAME_TYPE_COLLAPSE") for b in result.lowering_blockers)


def test_explicit_instance_dependency_is_not_a_decorative_execution_edge(registry):
    body = complex_brief()
    body["dependencies"] = [{"upstream": "brand", "downstream": "site"}]
    result = compile_body(body, registry)
    assert result.compiled_projection is None
    assert "DEPENDENCY_NOT_REPRESENTABLE:brand->site" in result.lowering_blockers
    body["dependencies"][0].update(mandatory=False, selected=False)
    assert compile_body(body, registry).compiled_projection is not None


@pytest.mark.parametrize("field,value,prefix", [
    ("output_contract", "native_ios_binary", "UNSUPPORTED_OUTPUT_CONTRACT"),
    ("external_action", "publish", "EXTERNAL_OPERATION_NOT_AUTHORIZED"),
    ("capability_requirements", ["t2i"], "CAPABILITY_BINDING_UNVERIFIED"),
])
def test_unsupported_or_consequential_work_remains_visible(registry, field, value, prefix):
    body = minimal()
    body["deliverables"][0][field] = value
    result = compile_body(body, registry)
    assert result.status == "BLOCKED" and result.compiled_projection is None
    assert any(b.startswith(prefix) for b in result.lowering_blockers)
    assert result.deliverables[0].id == "copy-a"


def test_ambiguity_and_unconfirmed_inference_block_without_guessing(registry):
    body = minimal(ambiguities=["Audience requirements conflict"])
    body["requirements"][0].update(origin="INFERRED", rationale="Required by the stated objective", confirmation_required=True)
    result = compile_body(body, registry)
    assert "CONFIRMATION_REQUIRED:r1" in result.lowering_blockers
    assert "AMBIGUITY:Audience requirements conflict" in result.lowering_blockers
    assert result.compiled_projection is None


@pytest.mark.parametrize("field,value", [
    ("grants", []), ("approvals", []), ("existing_artifacts", {"brand_platform": "a" * 64}),
    ("provider_status", {"t2i": "VERIFIED"}), ("status", "DEPLOYED"), ("max_attempts", 99),
    ("cost", {"total": 0}),
])
def test_request_cannot_mint_authority_acceptance_cost_or_retry_policy(field, value):
    with pytest.raises(ValidationError):
        AdaptivePlanningRequest.model_validate(minimal(**{field: value}))


def test_malformed_inference_and_nested_completion_claim_are_refused():
    body = minimal()
    body["requirements"][0]["origin"] = "INFERRED"
    with pytest.raises(ValidationError, match="rationale"):
        AdaptivePlanningRequest.model_validate(body)
    body = minimal()
    body["deliverables"][0]["status"] = "ACCEPTED"
    with pytest.raises(ValidationError):
        AdaptivePlanningRequest.model_validate(body)


def test_semantic_revision_has_lineage_without_claiming_approval_mutation(registry):
    before = AdaptivePlanningRequest.model_validate(minimal())
    body = minimal(revision=2)
    body["deliverables"][0]["acceptance_criteria"] = ["A materially different acceptance contract"]
    result = compile_body(body, registry, previous=before)
    original = compile_adaptive_plan(before, registry=registry)
    assert result.previous_revision_hash == original.content_hash
    assert result.compiled_projection.plan_hash != original.compiled_projection.plan_hash
    assert any(c.entity == "deliverable" and c.kind == "CHANGED" for c in result.changes)
    with pytest.raises(ValueError, match="revision"):
        compile_body(minimal(project_id="other", revision=2), registry, previous=before)


def test_unknown_production_cost_is_never_a_zero_total(registry):
    result = compile_body(minimal(), registry)
    assert result.cost.classification == "NOT PRICED" and result.cost.total is None
    assert result.cost.external_planner_fee == "$0 EXT"
    assert "not measured" in result.cost.basis


def test_planning_has_no_effects_and_preserves_canonical_retry_ceiling(registry, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("planning attempted an external effect")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    result = compile_body(minimal(), registry)
    assert all(wo.retry_policy["max_attempts"] <= 3 for wo in result.compiled_projection.work_orders.values())
    # No imports of execution, storage, database or action-plane owners.
    from services.langgraph.agency.compiled import adaptive
    tree = ast.parse(Path(adaptive.__file__).read_text())
    imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(part in name for name in imports for part in ("persistence", "execution_fabric", "actions", "delivery"))


def test_legacy_same_type_dedup_is_unchanged_and_explains_adaptive_refusal():
    specs = [DeliverableSpec(id=key, requested_outcome=f"Email {key}", output_contract="copy_variant",
                             acceptance_criteria=(f"Acceptance for {key}",)) for key in ("a", "b")]
    graph = compile_backchain(specs)
    assert set(graph.roots) == {"deliverable:a", "deliverable:b"}
    assert graph.nodes["deliverable:a"].hard_dependencies == ("accept:copy_variant",)
    assert graph.nodes["deliverable:b"].hard_dependencies == ("accept:copy_variant",)
    assert sum(node.id == "work:copy_variant" for node in graph.work_nodes()) == 1


def test_uncovered_requirement_is_not_silently_omitted(registry):
    body = minimal()
    body["requirements"].append({"id": "uncovered", "purpose": "Another mandatory output", "source_refs": ["brief:2"]})
    result = compile_body(body, registry)
    assert "UNSATISFIED_REQUIREMENT:uncovered" in result.lowering_blockers
    assert result.compiled_projection is None


def test_implicit_category_memberships_are_materialized(registry):
    result = compile_body(complex_brief(), registry)
    for item in result.deliverables:
        assert item.category_ids
        for key in item.category_ids:
            category = next(c for c in result.categories if c.id == key)
            assert set(category.requirement_ids) & set(item.requirement_ids)


def test_revision_removal_preserves_previous_snapshot_and_records_tombstones(registry):
    body = complex_brief()
    previous = AdaptivePlanningRequest.model_validate(body)
    body["requirements"] = body["requirements"][:-1]
    body["deliverables"] = body["deliverables"][:-1]
    body["revision"] = 2
    result = compile_body(body, registry, previous=previous)
    assert len(previous.deliverables) == 4 and len(result.deliverables) == 3
    assert any(c.entity == "deliverable" and c.id == "copy" and c.kind == "REMOVED" for c in result.changes)
    assert any(c.entity == "requirement" and c.id == "r4" and c.kind == "REMOVED" for c in result.changes)


def test_resource_limit_and_mandatory_dependency_deselection_are_refused():
    body = minimal()
    body["requirements"] *= 101
    with pytest.raises(ValidationError):
        AdaptivePlanningRequest.model_validate(body)
    body = minimal(dependencies=[{"upstream": "copy-a", "downstream": "other", "selected": False}])
    with pytest.raises(ValidationError, match="mandatory"):
        AdaptivePlanningRequest.model_validate(body)


def test_model_copy_cannot_smuggle_unvalidated_authority(registry):
    request = AdaptivePlanningRequest.model_validate(minimal())
    forged = request.model_copy(update={"grants": ({"issued_by": "attacker"},)})
    # Pydantic drops undeclared attributes from model_dump for this frozen
    # contract, so they cannot enter the canonical request or mint a grant.
    result = compile_adaptive_plan(forged, registry=registry)
    assert not result.execution_authorized
    assert all(not cell.approval_refs for cell in result.compiled_projection.cells.values())


@pytest.mark.parametrize("stamp", ["not-a-date", "2026-11-07T00:00:00", "2026-99-99T00:00:00Z"])
def test_malformed_or_naive_planning_time_is_rejected(stamp):
    with pytest.raises(ValidationError):
        AdaptivePlanningRequest.model_validate(minimal(as_of=stamp))


def test_equivalent_instants_have_the_same_preview_identity(registry):
    first = compile_body(minimal(), registry)
    second = compile_body(minimal(as_of="2026-11-06T16:00:00-08:00"), registry)
    assert first.content_hash == second.content_hash
    assert first.compiled_projection.plan_hash == second.compiled_projection.plan_hash
