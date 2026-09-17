from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .registry import RoleOSRegistry
from .work_order import WorkOrderCompiler, WorkOrderError


class MissionAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledMissionWorkOrders:
    mission_id: str
    registry_hash: str
    work_orders: tuple[dict[str, Any], ...]
    task_to_work_order: dict[str, str]


class MissionWorkOrderAdapter:
    """Bind a validated Mission Contract payload to Role OS Work Orders.

    Phase routing is deliberately explicit: callers must supply a phase_map.
    This prevents the adapter from guessing organizational phase from prose.
    """

    def __init__(self, registry: RoleOSRegistry):
        self.registry = registry
        self.compiler = WorkOrderCompiler(registry)

    def compile(
        self,
        mission: Mapping[str, Any],
        *,
        project_id: str,
        phase_map: Mapping[str, str],
        authority_refs_by_task: Mapping[str, list[str]] | None = None,
        permission_refs_by_task: Mapping[str, list[str]] | None = None,
        approval_refs_by_task: Mapping[str, list[str]] | None = None,
        context_capsule_hash: str | None = None,
    ) -> CompiledMissionWorkOrders:
        mission_id = str(mission.get("mission_id") or "").strip()
        if not mission_id:
            raise MissionAdapterError("mission_id is required")
        task_graph = mission.get("task_graph")
        if not isinstance(task_graph, Mapping):
            raise MissionAdapterError("mission.task_graph must be an object")
        nodes = task_graph.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise MissionAdapterError("mission.task_graph.nodes must be a non-empty array")

        capabilities = mission.get("capabilities")
        if not isinstance(capabilities, list):
            raise MissionAdapterError("mission.capabilities must be an array")
        capability_by_id = {
            str(cap.get("id")): cap for cap in capabilities
            if isinstance(cap, Mapping) and cap.get("id")
        }

        acceptance = mission.get("acceptance_contracts")
        acceptance_by_artifact: dict[str, list[str]] = {}
        if isinstance(acceptance, list):
            for item in acceptance:
                if not isinstance(item, Mapping):
                    continue
                artifact_id = str(item.get("artifact_id") or "")
                criterion = str(item.get("criterion") or "")
                if artifact_id and criterion:
                    acceptance_by_artifact.setdefault(artifact_id, []).append(criterion)

        auth_map = authority_refs_by_task or {}
        perm_map = permission_refs_by_task or {}
        approval_map = approval_refs_by_task or {}

        known_task_ids = {str(node.get("id")) for node in nodes if isinstance(node, Mapping)}
        missing_phase = sorted(tid for tid in known_task_ids if tid not in phase_map)
        if missing_phase:
            raise MissionAdapterError(f"phase_map missing task ids: {missing_phase}")
        unknown_phase_keys = sorted(set(phase_map) - known_task_ids)
        if unknown_phase_keys:
            raise MissionAdapterError(f"phase_map contains unknown task ids: {unknown_phase_keys}")

        work_orders: list[dict[str, Any]] = []
        task_to_work_order: dict[str, str] = {}
        for node in nodes:
            if not isinstance(node, Mapping):
                raise MissionAdapterError("task node must be an object")
            task_id = str(node.get("id") or "").strip()
            if not task_id:
                raise MissionAdapterError("task id is required")
            capability_id = str(node.get("capability") or "").strip()
            cap = capability_by_id.get(capability_id)
            if cap is None:
                raise MissionAdapterError(f"task {task_id} references unknown capability {capability_id}")

            required_capabilities = self._role_resolution_terms(cap)
            produces = [str(x) for x in (node.get("produces") or [])]
            criteria = [c for artifact in produces for c in acceptance_by_artifact.get(artifact, [])]
            if not criteria:
                criteria = [str(x) for x in (node.get("verification") or []) if str(x).strip()]
            if not criteria:
                raise MissionAdapterError(f"task {task_id} has no acceptance/verification criteria")

            execution_mode = str(node.get("execution_mode") or "").upper()
            risk_level = "high" if execution_mode == "HUMAN" else "medium"
            side_effect_class = self._side_effect_class(node)
            tool = node.get("tool")

            try:
                wo = self.compiler.compile(
                    project_id=project_id,
                    mission_id=mission_id,
                    phase_id=phase_map[task_id],
                    objective=str(node.get("description") or task_id),
                    required_capabilities=required_capabilities,
                    acceptance_criteria=criteria,
                    dependency_refs=[str(x) for x in (node.get("dependencies") or [])],
                    required_artifact_refs=produces,
                    required_evidence=[str(x) for x in (node.get("verification") or [])],
                    risk_level=risk_level,
                    side_effect_class=side_effect_class,
                    authority_refs=list(auth_map.get(task_id, [])),
                    permission_refs=list(perm_map.get(task_id, [])),
                    approval_refs=list(approval_map.get(task_id, [])),
                    tool_plan=[str(tool)] if tool else [],
                    context_capsule_hash=context_capsule_hash,
                    expected_state_transition="VALIDATE",
                    next_route="VALIDATE",
                )
            except WorkOrderError as exc:
                raise MissionAdapterError(f"failed to compile task {task_id}: {exc}") from exc

            wo["_runtime"]["mission_task_id"] = task_id
            task_to_work_order[task_id] = wo["work_order_id"]
            work_orders.append(wo)

        # Convert mission task dependency IDs to concrete Work Order IDs for runtime execution,
        # while retaining the original task IDs for provenance.
        for wo in work_orders:
            original = list(wo["dependency_refs"])
            wo["_runtime"]["mission_dependency_task_ids"] = original
            wo["dependency_refs"] = [task_to_work_order[d] for d in original]

        return CompiledMissionWorkOrders(
            mission_id=mission_id,
            registry_hash=self.registry.registry_hash,
            work_orders=tuple(work_orders),
            task_to_work_order=task_to_work_order,
        )

    @staticmethod
    def _role_resolution_terms(capability: Mapping[str, Any]) -> list[str]:
        terms: list[str] = []
        for ref in capability.get("context_refs") or []:
            ref = str(ref)
            if ref.startswith("agency-role:"):
                role = ref.split(":", 1)[1].replace("_", "-")
                terms.append(role)
        for skill in capability.get("skills") or []:
            terms.append(str(skill).replace("_", "-"))
        if not terms:
            terms.append(str(capability.get("id") or ""))
        return [t for t in terms if t]

    @staticmethod
    def _side_effect_class(node: Mapping[str, Any]) -> str:
        mode = str(node.get("execution_mode") or "").upper()
        tool = str(node.get("tool") or "").lower()
        # Human approval requests are external/reversible workflow writes, not irreversible effects.
        if mode == "HUMAN" or tool.startswith("approval."):
            return "REVERSIBLE_WRITE"
        # The current Mission Contract compiler intentionally excludes publication/spend;
        # ordinary generation/validation/delivery preparation remains internal.
        return "PURE"
