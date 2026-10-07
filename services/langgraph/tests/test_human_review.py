from uuid import uuid4
from datetime import datetime, timezone
from services.langgraph.graph.nodes.human_review import human_review_node
from services.langgraph.graph.models import AgentRun
from services.langgraph.persistence.approvals import list_pending_approvals
from services.langgraph.persistence.runs import create_run_record

def test_human_review_node_creates_approval_request():
    now = datetime.now(timezone.utc)
    run = AgentRun(
        id=uuid4(),
        tenant_id="tenant-interim-test",
        project_id="proj-interim-test",
        status="running",
        created_at=now,
        updated_at=now,
    )
    # The approval references the run, so the run must exist (Postgres enforces
    # the foreign key; in the real graph the run is created before any node).
    create_run_record(str(run.id), run.tenant_id, run.project_id, "default", "running", {})
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
