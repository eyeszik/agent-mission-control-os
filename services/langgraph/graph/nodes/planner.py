import json
from services.langgraph.graph.state import GraphState
from langchain_core.messages import AIMessage
from services.langgraph.quality.evaluator import evaluate_quality

def planner_node(state: GraphState) -> dict:
    """
    Node: Planner
    Responsibilities: Construct the execution Task DAG based on constraints.
    Instead of calling an LLM right now, we simulate the structured output.
    """
    print(f"Running Planner for run {state['run'].id}")
    
    # 1. Read the messages created by Ingest
    last_message = state.get("messages", [])[-1].content if state.get("messages") else ""
    
    # 2. Simulate an LLM parsing the request and returning a JSON DAG
    simulated_dag = {
        "tasks": [
            {"id": "t1", "action": "Analyze Requirements"},
            {"id": "t2", "action": "Generate Code", "depends_on": ["t1"]},
            {"id": "t3", "action": "Review Quality", "depends_on": ["t2"]}
        ]
    }
    
    dag_string = json.dumps(simulated_dag)
    
    # 3. Evaluate the generated plan
    quality = evaluate_quality(dag_string)
    
    # 4. Generate the AI Response
    ai_msg = AIMessage(content=f"I have constructed the following DAG:\n{dag_string}")
    
    return {
        "current_node": "planner",
        "messages": [ai_msg],
        "validation_status": "passed" if quality["threshold_passed"] else "failed"
    }
