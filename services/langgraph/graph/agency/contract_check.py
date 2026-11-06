"""``contract_check``: the one node ``agency/v2-contract`` adds to the graph.

It runs after brand-safety QA and before the HITL gate, evaluates the run's
DeliveryContract with the deterministic critic, and records the verdict in the
agency payload. It calls no model and no tool, writes no artifact and holds no
N3 role: it is a measurement, not a production stage. In ``shadow`` mode the
verdict is only recorded; in ``enforce`` mode the API's release gate reads it.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from services.langgraph.agency.delivery.workflow import CONTRACT_CHECK_NODE
from services.langgraph.graph.state import GraphState
from services.langgraph.persistence.delivery import evaluate_run_contract


def contract_check_node(state: GraphState) -> dict:
    data = dict(state.get("extracted_data") or {})
    agency = dict(data.get("agency") or {})
    run = state["run"]
    evaluation = evaluate_run_contract(
        data.get("delivery_contract"),
        agency.get("campaign_package") or {},
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        contract_mode=str(data.get("contract_mode") or "shadow"),
    )
    agency["contract_evaluation"] = evaluation
    data["agency"] = agency
    verdict = evaluation["dod"] or evaluation["status"]
    return {
        "current_node": CONTRACT_CHECK_NODE,
        "extracted_data": data,
        "messages": [AIMessage(content=f"Delivery contract evaluated: {verdict}.")],
    }
