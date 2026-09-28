"""T14 — Proof-Carrying Work Orders (PCWO).

A PCWO *wraps* the canonical ``role_os.WorkOrderCompiler`` output — it does not
re-implement role resolution, stable ids or the consequential-work blockers.
It adds the proof obligations the compiled control plane knows about: the
causal node, the authority binding, the context capsule, validation
obligations, idempotency class and completion checks. Without a valid PCWO a
node is not execution-ready.
"""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel

from services.langgraph.agency.role_os import WorkOrderCompiler, WorkOrderError

from .authority import N3_SPECIALISTS, SpecialistBinding
from .backchain import BackchainNode
from .hashing import semantic_hash

_FROZEN = {"frozen": True, "extra": "forbid"}

IDEMPOTENCY_CLASS = {
    "PURE": "RETRY_SAFE",
    "DRAFT": "RETRY_SAFE_VERSIONED",
    "REVERSIBLE_WRITE": "COMPENSATABLE",
    "IRREVERSIBLE_WRITE": "NON_RETRYABLE",
}


def retry_policy_for(side_effect_class: str) -> dict[str, Any]:
    """Retry ≤3; never blind-retry non-retryable work; unknown results reconcile."""
    if side_effect_class == "IRREVERSIBLE_WRITE":
        return {"max_attempts": 1, "on_unknown_result": "RECONCILE", "on_repeat_same_cause": "HUMAN_REVIEW_REQUIRED"}
    if side_effect_class == "REVERSIBLE_WRITE":
        return {"max_attempts": 3, "on_unknown_result": "RECONCILE", "on_partial": "COMPENSATE",
                "on_repeat_same_cause": "HUMAN_REVIEW_REQUIRED"}
    return {"max_attempts": 3, "on_repeat_same_cause": "HUMAN_REVIEW_REQUIRED"}


def risk_level_for(node: BackchainNode) -> str:
    if node.side_effect_class in {"REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"}:
        return "high"
    if node.artifact_type in {"positioning_statement", "brand_platform", "creative_concept", "release_record", "media_plan"}:
        return "medium"
    return "low"


class PCWO(BaseModel):
    model_config = _FROZEN

    work_order_id: str
    logical_operation_id: str
    plan_hash: str | None
    causal_node_id: str
    objective: str
    deliverable_refs: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    accountable_specialist: str | None
    contributor_specialists: tuple[str, ...]
    runtime_authority_binding: str
    capability_requirements: tuple[str, ...]
    context_capsule_ref: str | None
    input_refs: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    decision_refs: tuple[str, ...]
    artifact_contracts: tuple[str, ...]
    tool_plan: tuple[str, ...]
    validation_obligations: tuple[str, ...]
    side_effect_class: str
    idempotency_class: str
    mutation_targets: tuple[str, ...]
    resource_locks: tuple[str, ...]
    approval_scope: str | None
    retry_policy: dict[str, Any]
    provenance_refs: tuple[str, ...]
    source_skill_hashes: tuple[str, ...]
    output_schema: str
    completion_checks: tuple[str, ...]
    execution_ready: bool
    blockers: tuple[str, ...]
    work_order_hash: str


def compile_pcwo(
    compiler: WorkOrderCompiler,
    *,
    project_id: str,
    mission_id: str,
    node: BackchainNode,
    binding: SpecialistBinding,
    deliverable_refs: Iterable[str],
    acceptance_criteria: Iterable[str],
    validation_obligations: Iterable[str],
    evidence_requirements: Iterable[str],
    decision_refs: Iterable[str],
    contributor_specialists: Iterable[str],
    context_capsule_hash: str | None,
    authority_refs: Iterable[str],
    approval_refs: Iterable[str],
    approval_scope_hash: str | None,
    extra_blockers: Iterable[str] = (),
) -> tuple[PCWO | None, list[str]]:
    """Return ``(pcwo, blockers)``. ``pcwo`` is None when no valid order can be compiled."""
    query = N3_SPECIALISTS.get(node.runtime_role_id or "")
    blockers = list(extra_blockers)
    if query is None or not node.phase_compatibility:
        return None, blockers + ["NO_VALID_PCWO:no specialist query or phase"]
    acceptance = tuple(acceptance_criteria) or (f"{node.artifact_type or node.id} passes its validation obligations",)
    tool_plan = tuple(binding.permitted_tools) or (("provider:" + node.mutation_targets[0].split(":", 1)[1]),)
    try:
        wo = compiler.compile(
            project_id=project_id,
            mission_id=mission_id,
            phase_id=node.phase_compatibility[0],
            objective=node.purpose,
            required_capabilities=[query.skill_name],
            acceptance_criteria=list(acceptance),
            input_refs=list(node.hard_dependencies),
            dependency_refs=list(node.dependencies),
            required_artifact_refs=[d.split(":", 1)[1] for d in node.hard_dependencies if d.startswith(("accept:", "ref:"))],
            required_evidence=list(evidence_requirements),
            risk_level=risk_level_for(node),
            side_effect_class=node.side_effect_class,
            department_hint=query.department,
            authority_refs=list(authority_refs),
            approval_refs=list(approval_refs),
            tool_plan=list(tool_plan),
            context_capsule_hash=context_capsule_hash,
            next_route="VALIDATE",
        )
    except WorkOrderError as exc:
        return None, blockers + [f"NO_VALID_PCWO:{exc}"]

    runtime = wo["_runtime"]
    blockers += list(runtime["blockers"])
    if wo["accountable_role_id"] != binding.specialist_role_id:
        blockers.append("PCWO_SPECIALIST_MISMATCH")
    blockers += list(binding.blockers)
    if context_capsule_hash is None:
        blockers.append("MISSING_CONTEXT_CAPSULE")

    locks = tuple(sorted(set(node.mutation_targets) | ({f"provider:{t.split(':', 1)[1]}" for t in node.mutation_targets if t.startswith("external:")})))
    body = {
        "work_order_id": wo["work_order_id"],
        "logical_operation_id": wo["idempotency"]["logical_operation_id"],
        "plan_hash": None,
        "causal_node_id": node.id,
        "objective": node.purpose,
        "deliverable_refs": tuple(sorted(deliverable_refs)),
        "acceptance_criteria": acceptance,
        "accountable_specialist": binding.specialist_role_id,
        "contributor_specialists": tuple(sorted(set(contributor_specialists))),
        "runtime_authority_binding": binding.binding_hash,
        "capability_requirements": binding.required_capabilities,
        "context_capsule_ref": context_capsule_hash,
        "input_refs": node.hard_dependencies,
        "dependency_refs": node.dependencies,
        "evidence_requirements": tuple(evidence_requirements),
        "decision_refs": tuple(sorted(decision_refs)),
        "artifact_contracts": (node.artifact_type,) if node.artifact_type else (),
        "tool_plan": tool_plan,
        "validation_obligations": tuple(validation_obligations),
        "side_effect_class": node.side_effect_class,
        "idempotency_class": IDEMPOTENCY_CLASS[node.side_effect_class],
        "mutation_targets": node.mutation_targets,
        "resource_locks": locks,
        "approval_scope": approval_scope_hash,
        "retry_policy": retry_policy_for(node.side_effect_class),
        "provenance_refs": (f"roleos:{runtime['registry_hash']}", f"cwg:{node.semantic_hash}"),
        "source_skill_hashes": binding.source_skill_hashes,
        "output_schema": f"n1:{node.artifact_type}" if node.artifact_type else "n2:release_record",
        "completion_checks": (
            "all validation obligations PASS",
            "independent reviewer for medium/high risk",
            "output hash recorded in N4 registry",
            "execution receipt/proof recorded",
        ),
        "execution_ready": not blockers and bool(runtime["execution_ready"]),
        "blockers": tuple(sorted(set(blockers))),
    }
    return PCWO(**body, work_order_hash=semantic_hash(body)), sorted(set(blockers))
