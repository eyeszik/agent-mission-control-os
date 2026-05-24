from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID

class AgentRun(BaseModel):
    id: UUID
    tenant_id: str
    project_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

class RunEvent(BaseModel):
    event_id: UUID
    run_id: UUID
    node_id: str
    type: str
    payload: Dict[str, Any]
    timestamp: datetime
