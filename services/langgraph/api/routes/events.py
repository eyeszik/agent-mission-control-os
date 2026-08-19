from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json

from services.langgraph.persistence.events import list_events_for_run

router = APIRouter()


async def _replay_event_stream(run_id: str):
    """
    Replays the real events persisted for this run (see
    api/routes/agency.py's _run_and_record_events, which records one
    node_start/node_complete pair per node as the graph actually executes).

    This used to be a fixed 3-event mock stream (node_start/node_complete
    "ingest", node_start "planner") sent identically for every run_id
    regardless of what actually ran or whether the run even existed.

    Note this is a replay of history, not a live push: the agency pipeline
    still executes synchronously inside the POST /agency/runs request, so
    by the time a client opens this SSE connection the run has already
    produced whatever events it's going to produce. A client connecting
    mid-run (there is no such window today, but a future async execution
    model could introduce one) would only see events recorded before it
    connected.
    """
    for event in list_events_for_run(run_id):
        payload = {
            "event_id": event["event_id"],
            "run_id": event["run_id"],
            "node_id": event["node_id"],
            "type": event["type"],
            "payload": event["payload"],
            "timestamp": event["timestamp"],
        }
        yield f"data: {json.dumps(payload)}\n\n"


@router.get("/{run_id}/events")
async def stream_events(run_id: str):
    """
    Contract: SSE Event Stream for Run Status
    """
    return StreamingResponse(_replay_event_stream(run_id), media_type="text/event-stream")
