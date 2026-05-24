from services.langgraph.graph.state import GraphState

def ingest_node(state: GraphState) -> dict:
    """
    Node: Ingest
    Responsibilities: normalize inputs, detect/mask PII
    """
    print(f"Running Ingest for run {state['run'].id}")
    # Return partial state update
    return {"current_node": "ingest", "extracted_data": {}}
