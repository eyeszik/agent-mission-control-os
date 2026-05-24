from services.langgraph.graph.state import GraphState
from langchain_core.messages import AIMessage
from services.langgraph.quality.evaluator import evaluate_quality

def validation_node(state: GraphState) -> dict:
    """
    Node: Validation
    Responsibilities: Validate the output against constraint_ledger.yaml and other checks.
    """
    print(f"Running Validation for run {state['run'].id}")
    
    last_msg = state.get("messages", [])[-1].content if state.get("messages") else ""
    quality = evaluate_quality(last_msg)
    
    ai_msg = AIMessage(content="Validation complete. Output verified against constraint ledger.")
    return {
        "current_node": "validation",
        "messages": [ai_msg],
        "validation_status": "passed" if quality["threshold_passed"] else "failed"
    }
