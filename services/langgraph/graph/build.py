from langgraph.graph import StateGraph, END
from services.langgraph.graph.state import GraphState
from services.langgraph.graph.nodes.ingest import ingest_node
from services.langgraph.graph.nodes.planner import planner_node

def build_workflow() -> StateGraph:
    """
    Constructs the core execution DAG for Agent Mission Control.
    """
    workflow = StateGraph(GraphState)
    
    # Add Nodes
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("planner", planner_node)
    
    # Add Edges
    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "planner")
    workflow.add_edge("planner", END)
    
    # Compile
    # Note: checkpointer would be passed here during compilation in a real environment
    return workflow.compile()
