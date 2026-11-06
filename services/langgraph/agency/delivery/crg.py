"""Contract Requirement Graph: a derived, read-only view.

Requirement -> AcceptanceTest -> (MethodPlanNode) -> WorkOrder -> ArtifactVersion -> CheckResult

Everything here is computed from records other modules own: the contract, the
critic's result, the sealed release candidate, the live stage-to-role bindings
and ProjectOS dependency edges. There is no store and no mutation API, and an
inconsistency between those inputs is a compile failure, never repaired by
inventing an edge.

No MethodPlan exists in this codebase yet, so plan nodes are absent and
``plan_hash`` is ``None``. The live pipeline's stages stand in as work orders;
each is justified by the repository invariant ``AGENCY_PIPELINE_STAGES`` rather
than by a contract requirement.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from services.langgraph.agency.delivery.contract import DeliveryContract, contract_hash
from services.langgraph.agency.delivery.critic import ContractResult
from services.langgraph.agency.delivery.release import ReleaseCandidateManifest
from services.langgraph.agency.execution.canonical import canonical_hash

PIPELINE_INVARIANT = "AGENCY_PIPELINE_STAGES"


class CRGInconsistency(ValueError):
    """The canonical inputs disagree; the graph cannot be compiled."""


def build_crg(
    *,
    contract: DeliveryContract,
    result: ContractResult,
    candidate: ReleaseCandidateManifest,
    work_order_refs: Sequence[Mapping[str, Any]],
    dependency_edges: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    c_hash = contract_hash(contract)
    if result.contract_hash != c_hash or candidate.contract_hash != c_hash:
        raise CRGInconsistency("contract, result and candidate name different contracts")
    contract_ids = [r.requirement_id for r in contract.requirements]
    if [r.requirement_id for r in result.results] != contract_ids:
        raise CRGInconsistency("result does not cover exactly the contract's requirements")

    work_orders = []
    rejected = []
    for ref in work_order_refs:
        entry = {"stage": str(ref["stage"]), "role_id": str(ref["role_id"]), "justified_by": ref.get("justified_by")}
        # An executable task must trace to a requirement or a verified
        # repository invariant; anything else is rejected, not kept.
        (work_orders if entry["justified_by"] == PIPELINE_INVARIANT else rejected).append(entry)

    artifact_versions = [ref.version_ref for ref in candidate.artifact_refs]
    requirements = []
    incomplete = []
    for req, check in zip(contract.requirements, result.results):
        human_path = req.kind == "HUMAN_REVIEW"
        executable_path = artifact_versions if not human_path else []
        if req.blocking and not human_path and not executable_path:
            incomplete.append(req.requirement_id)
        requirements.append(
            {
                "requirement_id": req.requirement_id,
                "acceptance_test": req.kind,
                "blocking": req.blocking,
                "method_plan_nodes": [],
                "work_orders": [w["stage"] for w in work_orders] if executable_path else [],
                "artifact_versions": executable_path,
                "human_resolution": human_path,
                "check_result": check.verdict,
            }
        )

    edges = sorted(
        (
            {"artifact_id": str(e["artifact_id"]), "depends_on_artifact_id": str(e["depends_on_artifact_id"])}
            for e in dependency_edges
        ),
        key=lambda e: (e["artifact_id"], e["depends_on_artifact_id"]),
    )
    crg_hash = canonical_hash(
        {
            "contract_hash": c_hash,
            "plan_hash": None,
            "work_order_refs": work_orders,
            "artifact_dependency_refs": edges,
        }
    )
    return {
        "crg_hash": crg_hash,
        "status": "PLAN_INCOMPLETE" if incomplete or rejected else "COMPLETE",
        "plan_hash": None,
        "requirements": requirements,
        "work_orders": work_orders,
        "rejected_work_orders": rejected,
        "incomplete_requirements": incomplete,
        "artifact_dependency_refs": edges,
    }
