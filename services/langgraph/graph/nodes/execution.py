from services.langgraph.graph.state import GraphState
from langchain_core.messages import AIMessage

def execution_node(state: GraphState) -> dict:
    """
    Node: Execution
    Responsibilities: Execute the plan, generate code/content, or interact with external tools.
    """
    print(f"Running Execution for run {state['run'].id}")
    ai_msg = AIMessage(content="Generated the requested artifacts and changes.")
    return {"current_node": "execution", "messages": [ai_msg]}
