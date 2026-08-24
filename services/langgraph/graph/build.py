from langgraph.graph import StateGraph, END
from services.langgraph.graph.state import GraphState
from services.langgraph.graph.nodes.ingest import ingest_node
from services.langgraph.graph.nodes.planner import planner_node
from services.langgraph.graph.nodes.retrieval import retrieval_node
from services.langgraph.graph.nodes.analysis import analysis_node
from services.langgraph.graph.nodes.execution import execution_node
from services.langgraph.graph.nodes.validation import validation_node
from services.langgraph.graph.nodes.human_review import human_review_node
from services.langgraph.persistence.checkpoints import get_checkpointer

def build_workflow() -> StateGraph:
    """
    Builds and compiles the Agent Mission Control LangGraph workflow.

    INTERIM SAFETY MEASURE: auto-publish is disabled. Every run is routed
    through `human_review` before completion, regardless of validation_status,
    because `quality/evaluator.py` currently scores output quality purely as a
    function of string length and cannot yet be trusted to gate unattended
    completion. Restore `validation` -> END directly (or a real conditional
    edge on validation_status) once evaluator.py is upgraded to a real
    LLM-as-judge (LangSmith/DeepEval).
    """
    workflow = StateGraph(GraphState)

    # Add Nodes
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("execution", execution_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("human_review", human_review_node)

    # Add Edges
    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "planner")
    workflow.add_edge("planner", "retrieval")
    workflow.add_edge("retrieval", "analysis")
    workflow.add_edge("analysis", "execution")
    workflow.add_edge("execution", "validation")
    # INTERIM: was `workflow.add_edge("validation", END)`.
    # Auto-publish disabled until evaluator.py is upgraded (tracked follow-up).
    workflow.add_edge("validation", "human_review")
    workflow.add_edge("human_review", END)

    # Compile with SQLite persistence checkpointer
    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer)
