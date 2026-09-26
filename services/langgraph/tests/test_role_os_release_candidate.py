from pathlib import Path

from services.langgraph.agency.role_os.amc_profile import (
    AGENCY_PHASE_MAP,
    AGENCY_STAGE_BINDINGS,
    AGENCY_STAGE_IDS,
    compile_agency_role_os_work_orders,
)
from services.langgraph.agency.role_os.registry import RoleOSRegistry
from services.langgraph.graph.agency.build import AGENCY_PIPELINE_STAGES


RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "runtime" / "role_os"


def _registry() -> RoleOSRegistry:
    return RoleOSRegistry(RUNTIME_ROOT)


def test_amc_profile_covers_the_exact_live_pipeline_in_order():
    assert AGENCY_STAGE_IDS == tuple(AGENCY_PIPELINE_STAGES)
    assert len(AGENCY_STAGE_BINDINGS) == 9
    assert set(AGENCY_PHASE_MAP.values()) <= {f"P{i}" for i in range(16)}


def test_amc_profile_compiles_all_stages_to_sealed_role_os_roles():
    compiled = compile_agency_role_os_work_orders(
        _registry(),
        project_id="proj_1",
        mission_id="mission-roleos-staging",
    )
    assert len(compiled.work_orders) == len(AGENCY_PIPELINE_STAGES)
    expected_skills = [binding.role_skill_name for binding in AGENCY_STAGE_BINDINGS]
    for index, (work_order, expected_skill) in enumerate(zip(compiled.work_orders, expected_skills, strict=True)):
        assert work_order["accountable_role_id"].endswith(f".{expected_skill}")
        assert work_order["phase_id"] == AGENCY_STAGE_BINDINGS[index].phase_id
        if index == 0:
            assert work_order["dependency_refs"] == []
        else:
            previous_stage = AGENCY_PIPELINE_STAGES[index - 1]
            assert work_order["dependency_refs"] == [compiled.task_to_work_order[previous_stage]]


def test_human_gate_is_not_execution_ready_without_real_authority_and_approval():
    compiled = compile_agency_role_os_work_orders(
        _registry(),
        project_id="proj_1",
        mission_id="mission-roleos-unapproved",
    )
    hitl = next(item for item in compiled.work_orders if item["_runtime"]["mission_task_id"] == "hitl_gate")
    assert hitl["side_effect_class"] == "REVERSIBLE_WRITE"
    assert hitl["_runtime"]["execution_ready"] is False
    assert set(hitl["_runtime"]["blockers"]) == {
        "MISSING_AUTHORITY_REF",
        "MISSING_HIGH_RISK_APPROVAL_REF",
    }


def test_human_gate_becomes_ready_only_with_explicit_authority_and_exact_approval_ref():
    compiled = compile_agency_role_os_work_orders(
        _registry(),
        project_id="proj_1",
        mission_id="mission-roleos-approved",
        authority_refs_by_task={"hitl_gate": ["human-review"]},
        approval_refs_by_task={"hitl_gate": ["approval-staging-1"]},
    )
    hitl = next(item for item in compiled.work_orders if item["_runtime"]["mission_task_id"] == "hitl_gate")
    assert hitl["authority_refs"] == ["human-review"]
    assert hitl["approval_refs"] == ["approval-staging-1"]
    assert hitl["_runtime"]["execution_ready"] is True
    assert hitl["_runtime"]["blockers"] == []
