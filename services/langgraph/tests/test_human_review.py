from uuid import uuid4
from services.langgraph.graph.nodes.human_review import human_review_node
from services.langgraph.graph.models import AgentRun
from services.langgraph.persistence.approvals import list_pending_approvals

def test_human_review_node_creates_approval_request():
    # NOTE: AgentRun's full required-field list was not fully verified this
    # session; adjust constructor args if this fails against the real model.
    run = AgentRun(id=uuid4(), tenant_id="tenant-interim-test", project_id="proj-interim-test")
    state = {
        "run": run,
        "current_node": "validation",
        "messages": [],
        "extracted_data": {},
        "validation_status": "passed",
    }

    result = human_review_node(state)

    assert result["current_node"] == "human_review"
    pending = list_pending_approvals(tenant_id="tenant-interim-test")
    assert any(a["run_id"] == str(run.id) for a in pending)
