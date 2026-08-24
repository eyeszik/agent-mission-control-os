from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from typing import Any

from .registry import RoleOSRegistry
from .resolver import RoleResolver, RoleResolutionError


class WorkOrderError(RuntimeError):
    pass


CONSEQUENTIAL = {"REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"}


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(blob).hexdigest()[:20]}"


class WorkOrderCompiler:
    """Compile a bounded, role-resolved Work Order without manufacturing authority."""

    def __init__(self, registry: RoleOSRegistry):
        self.registry = registry
        self.resolver = RoleResolver(registry)

    def compile(
        self,
        *,
        project_id: str,
        mission_id: str,
        phase_id: str,
        objective: str,
        required_capabilities: list[str],
        acceptance_criteria: list[str],
        input_refs: list[str] | None = None,
        dependency_refs: list[str] | None = None,
        required_artifact_refs: list[str] | None = None,
        required_evidence: list[str] | None = None,
        risk_level: str = "medium",
        side_effect_class: str = "PURE",
        department_hint: str | None = None,
        family_hint: str | None = None,
        authority_refs: list[str] | None = None,
        permission_refs: list[str] | None = None,
        approval_refs: list[str] | None = None,
        tool_plan: list[Any] | None = None,
        context_capsule_hash: str | None = None,
        expected_state_transition: str = "ACTIVE",
        next_route: str = "VALIDATE",
    ) -> dict[str, Any]:
        for label, value in {
            "project_id": project_id,
            "mission_id": mission_id,
            "phase_id": phase_id,
            "objective": objective,
        }.items():
            if not value or not str(value).strip():
                raise WorkOrderError(f"{label} is required")
        if risk_level not in {"low", "medium", "high", "critical"}:
            raise WorkOrderError(f"invalid risk_level: {risk_level}")
        if side_effect_class not in {"PURE", "DRAFT", "REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"}:
            raise WorkOrderError(f"invalid side_effect_class: {side_effect_class}")
        if not acceptance_criteria:
            raise WorkOrderError("acceptance_criteria must not be empty")

        try:
            phase = self.registry.get_phase(phase_id)
        except KeyError as exc:
            raise WorkOrderError(str(exc)) from exc

        try:
            match = self.resolver.resolve(
                required_capabilities,
                department_hint=department_hint,
                family_hint=family_hint,
                limit=1,
            )[0]
        except RoleResolutionError as exc:
            raise WorkOrderError(str(exc)) from exc

        authority_refs = list(authority_refs or [])
        permission_refs = list(permission_refs or [])
        approval_refs = list(approval_refs or [])

        # Consequential work can be compiled/planned without authority but cannot be execution-ready.
        execution_ready = True
        blockers: list[str] = []
        if side_effect_class in CONSEQUENTIAL and not authority_refs:
            execution_ready = False
            blockers.append("MISSING_AUTHORITY_REF")
        if side_effect_class == "IRREVERSIBLE_WRITE" and not approval_refs:
            execution_ready = False
            blockers.append("MISSING_EXACT_APPROVAL_REF")
        if risk_level in {"high", "critical"} and not approval_refs:
            execution_ready = False
            blockers.append("MISSING_HIGH_RISK_APPROVAL_REF")

        id_basis = {
            "project_id": project_id,
            "mission_id": mission_id,
            "phase_id": phase_id,
            "objective": objective,
            "accountable_role_id": match.role_id,
            "registry_hash": self.registry.registry_hash,
        }
        work_order_id = _stable_id("wo", id_basis)
        logical_operation_id = _stable_id("op", {**id_basis, "side_effect_class": side_effect_class})

        return {
            "work_order_id": work_order_id,
            "project_id": project_id,
            "mission_id": mission_id,
            "phase_id": phase_id,
            "objective": objective,
            "orchestrator_ids": list(phase.orchestrator_ids),
            "accountable_role_id": match.role_id,
            "contributor_role_ids": [],
            "dependency_refs": list(dependency_refs or []),
            "required_artifact_refs": list(required_artifact_refs or []),
            "input_refs": list(input_refs or []),
            "output_contract": {"phase_output": phase.output_contract},
            "acceptance_criteria": list(acceptance_criteria),
            "required_evidence": list(required_evidence or []),
            "risk_level": risk_level,
            "side_effect_class": side_effect_class,
            "tool_plan": list(tool_plan or []),
            "authority_refs": authority_refs,
            "permission_refs": permission_refs,
            "approval_refs": approval_refs,
            "verification_contract": [
                "validate output against acceptance_criteria",
                "verify dependency refs are current",
                "verify accountable role exists in registry",
                "verify authority immediately before consequential execution",
            ],
            "context_capsule_hash": context_capsule_hash,
            "idempotency": {
                "logical_operation_id": logical_operation_id,
                "strategy": "CONTENT_HASH" if side_effect_class != "PURE" else "NONE",
            },
            "retry_limit": 3,
            "stop_conditions": [
                "acceptance criteria pass",
                "retry limit exhausted",
                "required authority or approval missing",
                "dependency becomes stale",
            ],
            "expected_state_transition": expected_state_transition,
            "next_route": next_route,
            # Runtime-only execution guard; not part of external schema payload if strict schema is required.
            "_runtime": {
                "registry_hash": self.registry.registry_hash,
                "role_match": {**asdict(match), "matched_tokens": list(match.matched_tokens)},
                "execution_ready": execution_ready,
                "blockers": blockers,
            },
        }
