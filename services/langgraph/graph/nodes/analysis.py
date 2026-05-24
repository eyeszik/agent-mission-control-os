from services.langgraph.graph.state import GraphState
from langchain_core.messages import AIMessage

def analysis_node(state: GraphState) -> dict:
    """
    Node: Analysis
    Responsibilities: Synthesize retrieved data and formulate the execution payload.
    """
    print(f"Running Analysis for run {state['run'].id}")
    ai_msg = AIMessage(content="Analysis complete. execution dependencies resolved.")
    return {"current_node": "analysis", "messages": [ai_msg]}
