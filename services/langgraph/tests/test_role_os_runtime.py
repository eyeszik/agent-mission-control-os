from pathlib import Path

from services.langgraph.agency.role_os import NextBestActionEngine, ProjectExecutionState, RoleOSRegistry, WorkOrderCompiler


RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "runtime" / "role_os"


def test_role_os_registry_is_sealed_to_1097_roles():
    registry = RoleOSRegistry(RUNTIME_ROOT)
    assert len(registry.roles) == 1097
    assert len(registry.phases) >= 1


def test_work_order_compiler_resolves_role_and_blocks_consequential_without_authority():
    registry = RoleOSRegistry(RUNTIME_ROOT)
    compiler = WorkOrderCompiler(registry)
    work_order = compiler.compile(
        project_id="proj_1",
        mission_id="mission-1",
        phase_id=next(iter(registry.phases.keys())),
        objective="Compile brand strategy",
        required_capabilities=["brand-strategy"],
        acceptance_criteria=["strategy traces to evidence"],
        side_effect_class="IRREVERSIBLE_WRITE",
    )
    assert work_order["retry_limit"] == 3
    assert work_order["_runtime"]["execution_ready"] is False
    assert "MISSING_AUTHORITY_REF" in work_order["_runtime"]["blockers"]


def test_next_best_action_engine_is_deterministic():
    engine = NextBestActionEngine()
    orders = [
        {"work_order_id": "wo-1", "dependency_refs": [], "_runtime": {"execution_ready": True, "blockers": []}, "tool_plan": [], "side_effect_class": "PURE"},
        {"work_order_id": "wo-2", "dependency_refs": ["wo-1"], "_runtime": {"execution_ready": True, "blockers": []}, "tool_plan": [], "side_effect_class": "PURE"},
    ]
    selection = engine.select(orders, ProjectExecutionState())
    assert selection.selected_work_order_id == "wo-1"
    assert selection.terminal_hint == "CONTINUE"

