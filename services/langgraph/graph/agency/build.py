from langgraph.graph import StateGraph, END

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


def build_agency_workflow() -> StateGraph:
    """
    Constructs the autonomous AI branding and marketing agency production pipeline:

        brief_intake -> brand_strategy -> creative_concepting -> copywriting ->
        design_brief -> campaign_assembly -> brand_safety_qa -> hitl_gate -> delivery

    Compiled with interrupt_before=["delivery"] so every run pauses for human
    approval (via the HITL gate node's approval request) before the campaign is
    delivered/exported. A run resumes by invoking the compiled graph again with
    the same thread_id (run_id) and input=None, which LangGraph's SqliteSaver
    checkpointer replays from the paused state.
    """
    workflow = StateGraph(GraphState)

    workflow.add_node("brief_intake", brief_intake_node)
    workflow.add_node("brand_strategy", brand_strategy_node)
    workflow.add_node("creative_concepting", creative_concepting_node)
    workflow.add_node("copywriting", copywriting_node)
    workflow.add_node("design_brief", design_brief_node)
    workflow.add_node("campaign_assembly", campaign_assembly_node)
    workflow.add_node("brand_safety_qa", brand_safety_qa_node)
    workflow.add_node("hitl_gate", hitl_gate_node)
    workflow.add_node("delivery", delivery_node)

    workflow.set_entry_point("brief_intake")
    workflow.add_edge("brief_intake", "brand_strategy")
    workflow.add_edge("brand_strategy", "creative_concepting")
    workflow.add_edge("creative_concepting", "copywriting")
    workflow.add_edge("copywriting", "design_brief")
    workflow.add_edge("design_brief", "campaign_assembly")
    workflow.add_edge("campaign_assembly", "brand_safety_qa")
    workflow.add_edge("brand_safety_qa", "hitl_gate")
    workflow.add_edge("hitl_gate", "delivery")
    workflow.add_edge("delivery", END)

    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer, interrupt_before=["delivery"])
