from langgraph.graph import StateGraph, END
from services.langgraph.graph.state import GraphState
from services.langgraph.graph.nodes.ingest import ingest_node
from services.langgraph.graph.nodes.planner import planner_node
from services.langgraph.graph.nodes.retrieval import retrieval_node
from services.langgraph.graph.nodes.analysis import analysis_node
from services.langgraph.graph.nodes.execution import execution_node
from services.langgraph.graph.nodes.validation import validation_node
from services.langgraph.persistence.checkpoints import get_checkpointer

def build_workflow() -> StateGraph:
    """
    Constructs the core execution DAG for Agent Mission Control.
    """
    workflow = StateGraph(GraphState)
    
    # Add Nodes
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("retrieval", retrieval_node)
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("execution", execution_node)
    workflow.add_node("validation", validation_node)
    
    # Add Edges
    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "planner")
    workflow.add_edge("planner", "retrieval")
    workflow.add_edge("retrieval", "analysis")
    workflow.add_edge("analysis", "execution")
    workflow.add_edge("execution", "validation")
    workflow.add_edge("validation", END)
    
    # Compile with SQLite persistence checkpointer
    checkpointer = get_checkpointer()
    return workflow.compile(checkpointer=checkpointer)
