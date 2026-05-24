from fastapi import APIRouter
from pydantic import BaseModel
from uuid import uuid4
from datetime import datetime

router = APIRouter()

class CreateRunRequest(BaseModel):
    project_id: str
    tenant_id: str
    input_data: dict

@router.post("")
def create_run(req: CreateRunRequest):
    # Scaffold: Returns a mock run representation
    return {
        "id": str(uuid4()),
        "tenant_id": req.tenant_id,
        "project_id": req.project_id,
        "status": "idle",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }

@router.get("/{run_id}")
def get_run(run_id: str):
    return {"id": run_id, "status": "running"}
