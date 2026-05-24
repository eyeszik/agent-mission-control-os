from services.langgraph.graph.state import GraphState
from services.langgraph.security.pii import quarantine_payload
from services.langgraph.security.sanitize import sanitize_input
from langchain_core.messages import SystemMessage, HumanMessage

def ingest_node(state: GraphState) -> dict:
    """
    Node: Ingest
    Responsibilities: normalize inputs, detect/mask PII, sanitize for prompt injection.
    """
    print(f"Running Ingest for run {state['run'].id}")
    
    # 1. Extract input data
    raw_input = state['run'].metadata.get('input_data', {}) if state['run'].metadata else {}
    
    # 2. Sanitize and Quarantine PII
    sanitized = sanitize_input(raw_input)
    quarantined = quarantine_payload(sanitized)
    
    # 3. Create initial LangChain message state
    system_msg = SystemMessage(content="You are the Planner Agent. Extract requirements and propose a DAG.")
    human_msg = HumanMessage(content=str(quarantined.get("command", "No command provided.")))
    
    return {
        "current_node": "ingest", 
        "extracted_data": quarantined,
        "messages": [system_msg, human_msg]
    }
