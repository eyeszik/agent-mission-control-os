import pytest
from uuid import uuid4
from datetime import datetime
from services.langgraph.graph.models import AgentRun

def test_agent_run_creation():
    run = AgentRun(
        id=uuid4(),
        tenant_id="tenant_123",
        project_id="proj_456",
        status="idle",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    assert run.status == "idle"
    assert run.tenant_id == "tenant_123"
