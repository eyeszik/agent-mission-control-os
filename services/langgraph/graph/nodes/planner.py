from services.langgraph.graph.state import GraphState

def planner_node(state: GraphState) -> dict:
    """
    Node: Planner
    Responsibilities: Construct the execution Task DAG based on constraints.
    """
    print(f"Running Planner for run {state['run'].id}")
    return {"current_node": "planner"}
