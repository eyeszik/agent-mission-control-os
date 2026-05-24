from services.langgraph.graph.state import GraphState
from langchain_core.messages import AIMessage

def retrieval_node(state: GraphState) -> dict:
    """
    Node: Retrieval
    Responsibilities: Gather necessary context based on the plan.
    """
    print(f"Running Retrieval for run {state['run'].id}")
    ai_msg = AIMessage(content="Retrieved relevant documentation and source data.")
    return {"current_node": "retrieval", "messages": [ai_msg]}
