from langgraph.graph import StateGraph, END

from services.langgraph.agency.delivery.workflow import (
    CONTRACT_CHECK_NODE,
    INTERRUPT_POINTS,
    LEGACY_WORKFLOW,
    topology,
)
from services.langgraph.graph.agency.contract_check import contract_check_node
from services.langgraph.graph.state import GraphState
from services.langgraph.persistence.checkpoints import get_checkpointer
from services.langgraph.graph.agency.nodes import (
    AGENCY_PIPELINE_STAGES,
    brief_intake_node,
    brand_strategy_node,
    creative_concepting_node,
    copywriting_node,
    design_brief_node,
    campaign_assembly_node,
    brand_safety_qa_node,
    hitl_gate_node,
    delivery_node,
)

__all__ = ["build_agency_workflow", "AGENCY_PIPELINE_STAGES"]


_NODE_FUNCTIONS = {
    "brief_intake": brief_intake_node,
    "brand_strategy": brand_strategy_node,
    "creative_concepting": creative_concepting_node,
    "copywriting": copywriting_node,
    "design_brief": design_brief_node,
    "campaign_assembly": campaign_assembly_node,
    "brand_safety_qa": brand_safety_qa_node,
    CONTRACT_CHECK_NODE: contract_check_node,
    "hitl_gate": hitl_gate_node,
    "delivery": delivery_node,
}


def build_agency_workflow(workflow_version: str = LEGACY_WORKFLOW) -> StateGraph:
    """
    Constructs the autonomous AI branding and marketing agency production pipeline:

        brief_intake -> brand_strategy -> creative_concepting -> copywriting ->
        design_brief -> campaign_assembly -> brand_safety_qa -> hitl_gate -> delivery

    Compiled with interrupt_before=["delivery"] so every run pauses for human
    approval (via the HITL gate node's approval request) before the campaign is
    delivered/exported. A run resumes by invoking the compiled graph again with
    the same thread_id (run_id) and input=None, which LangGraph's SqliteSaver
    checkpointer replays from the paused state.

    ``workflow_version`` selects the topology from
    ``agency.delivery.workflow`` (the single definition both this builder and
    the run's pinned graph fingerprint use). ``agency/v2-contract`` inserts
    ``contract_check`` between brand_safety_qa and hitl_gate. A resumed run
    must pass the version it was created with, never the current default.
    """
    graph_shape = topology(workflow_version)
    workflow = StateGraph(GraphState)
    for node_id in graph_shape["node_ids"]:
        workflow.add_node(node_id, _NODE_FUNCTIONS[node_id])
    workflow.set_entry_point(graph_shape["node_ids"][0])
    for source, target in graph_shape["edges"]:
        workflow.add_edge(source, target)
    workflow.add_edge(graph_shape["node_ids"][-1], END)

    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer, interrupt_before=list(INTERRUPT_POINTS))
