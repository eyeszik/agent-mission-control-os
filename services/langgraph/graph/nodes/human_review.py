from services.langgraph.graph.state import GraphState
from services.langgraph.persistence.approvals import create_approval_request
from langchain_core.messages import AIMessage

def human_review_node(state: GraphState) -> dict:
    """
    Node: Human Review
    Responsibilities: File a HITL approval request instead of letting the run
    auto-complete. Reached unconditionally after validation while
    quality/evaluator.py remains a length-based heuristic (interim safety
    measure -- see build.py for context).
    """
    run = state["run"]
    quality_status = state.get("validation_status", "unknown")
    reason = (
        f"Auto-publish disabled: quality evaluator is a length-based heuristic, "
        f"not yet trustworthy for unattended approval. validation_status={quality_status}."
    )
    create_approval_request(
        run_id=str(run.id),
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        reason=reason,
        confidence=0.0,
    )
    ai_msg = AIMessage(content="Run held for human review pending quality evaluator upgrade.")
    return {
        "current_node": "human_review",
        "messages": [ai_msg],
    }
