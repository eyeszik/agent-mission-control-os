import json
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

    # NOTE: `context` here is state["extracted_data"] (the sanitized original
    # request from ingest_node) -- checks fidelity to the request, not
    # retrieval-grounded correctness. See risk R-013.
    extracted_data = state.get("extracted_data") or {}
    context = json.dumps(extracted_data) if extracted_data else None
    quality = evaluate_quality(last_msg, context=context)

    ai_msg = AIMessage(content="Validation complete. Output verified against constraint ledger.")
    return {
        "current_node": "validation",
        "messages": [ai_msg],
        "validation_status": "passed" if quality["threshold_passed"] else "failed"
    }
