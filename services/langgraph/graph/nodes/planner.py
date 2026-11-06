import os
import json
from services.langgraph.graph.state import GraphState
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from services.langgraph.quality.evaluator import evaluate_quality

def planner_node(state: GraphState) -> dict:
    """
    Node: Planner
    Responsibilities: Construct the execution Task DAG based on constraints.
    Uses ChatOpenAI if OPENAI_API_KEY is available, otherwise falls back to mock output.
    """
    print(f"Running Planner for run {state['run'].id}")

    # 1. Read the messages created by Ingest
    last_message = state.get("messages", [])[-1].content if state.get("messages") else ""

    api_key = os.environ.get("OPENAI_API_KEY")
    content = ""

    if api_key:
        try:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            prompt = (
                "You are an expert project planner. Given the user's request, "
                "return ONLY a JSON object representing a Task DAG with a 'tasks' array. "
                "Each task must have 'id', 'action', and an optional 'depends_on' array of IDs. "
                f"User request: {last_message}"
            )
            response = llm.invoke(prompt)
            content = response.content
        except Exception as e:
            print(f"LLM Error: {e}")
            content = json.dumps({"error": str(e), "tasks": []})

    if not content or "tasks" not in content.lower():
        # 2. Mock fallback
        simulated_dag = {
            "tasks": [
                {"id": "t1", "action": f"Analyze Requirements for: {last_message[:30]}..."},
                {"id": "t2", "action": "Generate Code", "depends_on": ["t1"]},
                {"id": "t3", "action": "Review Quality", "depends_on": ["t2"]}
            ]
        }
        content = json.dumps(simulated_dag)

    # 3. Evaluate the generated plan
    # NOTE: `context` here is state["extracted_data"] (the sanitized original
    # request from ingest_node) -- checks fidelity to the request, not
    # retrieval-grounded correctness. See risk R-013.
    extracted_data = state.get("extracted_data") or {}
    context = json.dumps(extracted_data) if extracted_data else None
    quality = evaluate_quality(content, context=context)

    # 4. Generate the AI Response
    ai_msg = AIMessage(content=f"I have constructed the following DAG:\n{content}")

    return {
        "current_node": "planner",
        "messages": [ai_msg],
        "validation_status": "passed" if quality["threshold_passed"] else "failed"
    }
