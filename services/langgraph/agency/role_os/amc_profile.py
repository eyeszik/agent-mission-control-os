from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .mission_adapter import CompiledMissionWorkOrders, MissionWorkOrderAdapter
from .registry import RoleOSRegistry


@dataclass(frozen=True)
class AgencyStageBinding:
    stage_id: str
    phase_id: str
    role_skill_name: str
    objective: str
    verification: tuple[str, ...]
    execution_mode: str = "AGENT"


# This profile bridges the repository's fixed nine-stage LangGraph agency
# workflow to the sealed 1,097-role RoleOS registry. It is deliberately a
# governance projection: it compiles Work Orders and authority requirements,
# but does not replace LangGraph execution or manufacture permissions.
AGENCY_STAGE_BINDINGS: tuple[AgencyStageBinding, ...] = (
    AgencyStageBinding(
        "brief_intake",
        "P4",
        "account-manager",
        "Normalize the client brief, constraints, audience, goals, and source inputs.",
        ("brief is normalized and source constraints remain explicit",),
    ),
    AgencyStageBinding(
        "brand_strategy",
        "P5",
        "brand-strategist",
        "Produce evidence-traceable brand strategy from the approved brief.",
        ("strategy traces to the brief and preserves explicit assumptions",),
    ),
    AgencyStageBinding(
        "creative_concepting",
        "P7",
        "creative-director",
        "Develop campaign concepts consistent with the approved brand strategy.",
        ("concepts are distinct, on-strategy, and usable by downstream copy/design",),
    ),
    AgencyStageBinding(
        "copywriting",
        "P7",
        "copywriter",
        "Draft audience-relevant campaign copy for the approved creative concepts.",
        ("copy aligns with brand voice, concept intent, and channel constraints",),
    ),
    AgencyStageBinding(
        "design_brief",
        "P8",
        "art-director",
        "Compile the visual direction and production-ready design brief.",
        ("visual direction aligns with strategy, copy, audience, and accessibility constraints",),
    ),
    AgencyStageBinding(
        "campaign_assembly",
        "P9",
        "creative-producer",
        "Assemble the governed campaign package and internal production artifacts.",
        ("package contains the required strategy, copy, design, lineage, and review artifacts",),
    ),
    AgencyStageBinding(
        "brand_safety_qa",
        "P10",
        "qa-engineer",
        "Independently validate release criteria, provenance, brand safety, and technical integrity.",
        ("QA evidence is independent of creator outputs and release blockers are explicit",),
    ),
    AgencyStageBinding(
        "hitl_gate",
        "P11",
        "account-director",
        "Present the exact protected artifact version for authenticated human acceptance.",
        ("approval is bound to an authenticated reviewer and the exact artifact version",),
        execution_mode="HUMAN",
    ),
    AgencyStageBinding(
        "delivery",
        "P11",
        "project-manager",
        "Package and record approved client delivery without external publication or spend.",
        ("delivery references the approved artifact and records completion evidence",),
    ),
)

AGENCY_STAGE_IDS = tuple(binding.stage_id for binding in AGENCY_STAGE_BINDINGS)
AGENCY_PHASE_MAP = {binding.stage_id: binding.phase_id for binding in AGENCY_STAGE_BINDINGS}


def build_agency_role_os_mission(*, mission_id: str) -> dict[str, Any]:
    """Build a deterministic MissionWorkOrderAdapter payload for the live agency graph."""
    capabilities: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    previous: str | None = None
    for binding in AGENCY_STAGE_BINDINGS:
        capability_id = f"cap-{binding.stage_id}"
        capabilities.append(
            {
                "id": capability_id,
                "context_refs": [f"agency-role:{binding.role_skill_name}"],
                "skills": [],
            }
        )
        nodes.append(
            {
                "id": binding.stage_id,
                "capability": capability_id,
                "description": binding.objective,
                "dependencies": [previous] if previous else [],
                "produces": [f"agency:{binding.stage_id}"],
                "verification": list(binding.verification),
                "execution_mode": binding.execution_mode,
                "tool": "langgraph.workflow",
            }
        )
        previous = binding.stage_id
    return {
        "mission_id": mission_id,
        "capabilities": capabilities,
        "task_graph": {"nodes": nodes},
        "acceptance_contracts": [],
    }


def compile_agency_role_os_work_orders(
    registry: RoleOSRegistry,
    *,
    project_id: str,
    mission_id: str,
    authority_refs_by_task: Mapping[str, list[str]] | None = None,
    permission_refs_by_task: Mapping[str, list[str]] | None = None,
    approval_refs_by_task: Mapping[str, list[str]] | None = None,
    context_capsule_hash: str | None = None,
) -> CompiledMissionWorkOrders:
    """Compile the live agency stages into RoleOS Work Orders.

    Missing human authority/approval is intentionally preserved as a blocker.
    This function never invents grants and never executes a tool.
    """
    adapter = MissionWorkOrderAdapter(registry)
    return adapter.compile(
        build_agency_role_os_mission(mission_id=mission_id),
        project_id=project_id,
        phase_map=AGENCY_PHASE_MAP,
        authority_refs_by_task=authority_refs_by_task,
        permission_refs_by_task=permission_refs_by_task,
        approval_refs_by_task=approval_refs_by_task,
        context_capsule_hash=context_capsule_hash,
    )
