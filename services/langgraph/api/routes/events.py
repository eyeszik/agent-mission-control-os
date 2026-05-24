from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()

async def mock_event_stream(run_id: str):
    # Scaffold: Simulate SSE stream of node completions
    events = [
        {"type": "node_start", "node_id": "ingest", "run_id": run_id},
        {"type": "node_complete", "node_id": "ingest", "run_id": run_id},
        {"type": "node_start", "node_id": "planner", "run_id": run_id}
    ]
    for event in events:
        yield f"data: {json.dumps(event)}\n\n"
        await asyncio.sleep(0.5)

@router.get("/{run_id}/events")
async def stream_events(run_id: str):
    """
    Contract: SSE Event Stream for Run Status
    """
    return StreamingResponse(mock_event_stream(run_id), media_type="text/event-stream")
