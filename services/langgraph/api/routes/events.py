import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.langgraph.persistence.events import latest_sequence, list_events_for_run
from services.langgraph.persistence.runs import get_run_record
from services.langgraph.security.auth import Principal, authorize_resource, get_principal

router = APIRouter()
TERMINAL_RUN_STATES = {"completed", "failed", "rejected", "cancelled"}


def _serialize_event(event: dict) -> str:
    payload = {
        "event_id": event["event_id"],
        "run_id": event["run_id"],
        "tenant_id": event["tenant_id"],
        "project_id": event["project_id"],
        "sequence": event["sequence"],
        "schema_version": event["schema_version"],
        "event_type": event["event_type"],
        "node_id": event["node_id"],
        "observed_at": event["observed_at"],
        "started_at": event["started_at"],
        "completed_at": event["completed_at"],
        "persisted_at": event["persisted_at"],
        "checkpoint_ref": event["checkpoint_ref"],
        "safe_payload": event["safe_payload"],
        "redactions_applied": event["redactions_applied"],
    }
    return f"id: {event['sequence']}\ndata: {json.dumps(payload)}\n\n"


def _resolve_cursor(cursor: int, last_event_id: Optional[str]) -> int:
    resolved = cursor
    if last_event_id is not None:
        try:
            resolved = max(resolved, int(last_event_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer event sequence") from exc
    return resolved


async def _event_stream(run_id: str, after_sequence: int, follow: bool):
    sequence = after_sequence
    yield "retry: 3000\n\n"

    while True:
        events = list_events_for_run(run_id, after_sequence=sequence)
        for event in events:
            sequence = event["sequence"]
            yield _serialize_event(event)

        if not follow:
            return

        record = get_run_record(run_id)
        if not record:
            return
        if record["status"] in TERMINAL_RUN_STATES and latest_sequence(run_id) <= sequence:
            return

        # Comment heartbeat keeps compatible proxies from treating an idle SSE
        # connection as dead while revealing no application payload.
        yield ": heartbeat\n\n"
        await asyncio.sleep(1.0)


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    cursor: int = Query(default=-1, ge=-1),
    follow: bool = Query(default=False),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: Principal = Depends(get_principal),
):
    """Replay persisted events after a monotonic cursor, optionally tailing new rows."""

    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    authorize_resource(principal, record["tenant_id"], record["project_id"])
    after_sequence = _resolve_cursor(cursor, last_event_id)

    return StreamingResponse(
        _event_stream(run_id, after_sequence, follow),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
