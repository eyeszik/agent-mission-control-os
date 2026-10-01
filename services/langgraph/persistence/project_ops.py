"""Project operations: conversations, content, calendar, scheduler, publishing.

One scheduler. Publish, refresh and CRM-lifecycle work are all
``scheduled_jobs`` rows driven by :func:`run_scheduler_tick`. A tick never
calls a provider: a job that clears the due gate becomes a trust-kernel outbox
message, and only the outbox handler reaches a publication adapter. Job claims
are compare-and-set updates, so two overlapping ticks cannot deliver the same
job twice.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from uuid import uuid4

from services.langgraph.agency.execution.models import DispatchPermit, ExecutionReceipt, ObservationReceipt
from services.langgraph.agency.project_os.calendar import (
    ContentTransitionError,
    GateInput,
    assert_content_transition,
    due_gate,
    parse_ts,
    plan_horizon,
    requires_rights,
)
from services.langgraph.agency.project_os.content import atom_hash, derive_variant
from services.langgraph.agency.project_os.models import (
    Calendar,
    Claim,
    ContentAtom,
    ContentItem,
    ConversationMessage,
    ConversationThread,
    MessageArtifactRef,
    PublicationAttempt,
    PublicationReceipt,
    ScheduleCadence,
    ScheduledJob,
    ScheduleSlot,
)
from services.langgraph.agency.project_os.publishing import (
    PublicationBlocked,
    PublicationRequest,
    ProviderUncertain,
    publication_mode,
    resolve_provider,
)
from services.langgraph.agency.project_os.storage import StorageAdapter
from services.langgraph.agency.project_os.vocabulary import (
    CONTENT_KIND_ARTIFACT,
    ActivityType,
    ProviderMode,
    PublicationState,
)
from services.langgraph.agency.project_os.workspace import canonical_json, sha256_bytes
from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError, get_artifact
from services.langgraph.persistence.database import decode_json, json_param, normalize_record, table, transaction
from services.langgraph.persistence.projects import (
    ProjectConflictError,
    ProjectNotFoundError,
    _append_event,
    create_project_artifact,
    require_project_workspace,
    revise_project_artifact,
    rights_status,
)

PUBLICATION_TOPIC = "project.publication"
CONTENT_REVIEW_STATES = {"REVIEW", "APPROVED", "READY", "SCHEDULED", "DUE"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list(value: Any) -> list:
    return list(decode_json(value, []) or [])


def _dict(value: Any) -> dict:
    return dict(decode_json(value, {}) or {})


def _ts(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------


def _thread(row: Any) -> ConversationThread:
    r = normalize_record(row)
    return ConversationThread(
        thread_id=r["thread_id"], tenant_id=r["tenant_id"], project_id=r["project_id"], campaign_id=r.get("campaign_id"),
        title=r["title"], status=r["status"], created_by=r["created_by"], created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def _message(row: Any) -> ConversationMessage:
    r = normalize_record(row)
    return ConversationMessage(
        message_id=r["message_id"], thread_id=r["thread_id"], tenant_id=r["tenant_id"], project_id=r["project_id"],
        author=r["author"], role=r["role"], activity_type=r["activity_type"], body=r["body"],
        artifact_refs=tuple(MessageArtifactRef(**ref) for ref in _list(r.get("artifact_refs"))),
        created_at=str(r["created_at"]),
    )


def create_thread(*, tenant_id: str, project_id: str, actor: str, title: str, campaign_id: Optional[str] = None) -> ConversationThread:
    require_project_workspace(project_id)
    thread_id = f"thr-{uuid4().hex}"
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('conversation_threads')} (thread_id, tenant_id, project_id, campaign_id, title, status, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)",
            (thread_id, tenant_id, project_id, campaign_id, title, actor, now, now),
        )
        _append_event(db, tenant_id=tenant_id, project_id=project_id, event_type=ActivityType.MESSAGE, actor=actor,
                      thread_id=thread_id, subject_ref=f"thread:{thread_id}", payload={"thread_created": title})
        row = db.execute(f"SELECT * FROM {table('conversation_threads')} WHERE thread_id = ?", (thread_id,)).fetchone()
    return _thread(row)


def get_thread(thread_id: str) -> Optional[ConversationThread]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('conversation_threads')} WHERE thread_id = ?", (thread_id,)).fetchone()
    return _thread(row) if row else None


def list_threads(project_id: str) -> list[ConversationThread]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('conversation_threads')} WHERE project_id = ? ORDER BY updated_at DESC, thread_id",
            (project_id,),
        ).fetchall()
    return [_thread(row) for row in rows]


def _validate_artifact_ref(project_id: str, ref: Mapping[str, Any]) -> MessageArtifactRef:
    artifact = get_artifact(str(ref.get("artifact_id") or ""))
    if artifact is None or artifact["project_id"] != project_id:
        raise ProjectNotFoundError("referenced artifact is not part of this project")
    version_ref = str(ref.get("version_ref") or f"{artifact['artifact_id']}:v{artifact['version']}")
    prefix, _, version = version_ref.rpartition(":v")
    if prefix != artifact["artifact_id"] or not version.isdigit() or not 1 <= int(version) <= int(artifact["version"]):
        raise ProjectConflictError(f"version_ref {version_ref!r} does not exist for this artifact")
    return MessageArtifactRef(artifact_id=artifact["artifact_id"], version_ref=version_ref, relation=ref.get("relation") or "referenced")


def post_message(
    *,
    thread_id: str,
    project_id: str,
    author: str,
    body: str,
    role: str = "user",
    activity_type: ActivityType | str = ActivityType.MESSAGE,
    artifact_refs: Iterable[Mapping[str, Any]] = (),
) -> ConversationMessage:
    """Append a message *and* a project event, so chat never holds state the
    project activity stream (and so the artifact graph) cannot see."""
    thread = get_thread(thread_id)
    if thread is None or thread.project_id != project_id:
        raise ProjectNotFoundError("thread not found in project")
    refs = [_validate_artifact_ref(project_id, ref) for ref in artifact_refs]
    message_id = f"msg-{uuid4().hex}"
    now = _now()
    with transaction(write=True) as db:
        event = _append_event(
            db, tenant_id=thread.tenant_id, project_id=project_id, event_type=activity_type, actor=author,
            thread_id=thread_id, subject_ref=refs[0].version_ref if refs else f"message:{message_id}",
            payload={"message_id": message_id, "artifact_refs": [ref.model_dump(mode="json") for ref in refs]},
        )
        db.execute(
            f"""
            INSERT INTO {table('conversation_messages')}
            (message_id, thread_id, tenant_id, project_id, author, role, activity_type, body, artifact_refs, event_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, thread_id, thread.tenant_id, project_id, author, role, ActivityType(activity_type).value, body,
             json_param([ref.model_dump(mode="json") for ref in refs]), event.event_id, now),
        )
        db.execute(f"UPDATE {table('conversation_threads')} SET updated_at = ? WHERE thread_id = ?", (now, thread_id))
        row = db.execute(f"SELECT * FROM {table('conversation_messages')} WHERE message_id = ?", (message_id,)).fetchone()
    return _message(row)


def list_messages(thread_id: str, *, limit: int = 500) -> list[ConversationMessage]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('conversation_messages')} WHERE thread_id = ? ORDER BY created_at, message_id LIMIT ?",
            (thread_id, max(1, min(limit, 2000))),
        ).fetchall()
    return [_message(row) for row in rows]


def add_artifact_comment(*, project_id: str, artifact_id: str, version_ref: str, author: str, body: str) -> dict:
    ref = _validate_artifact_ref(project_id, {"artifact_id": artifact_id, "version_ref": version_ref})
    artifact = get_artifact(artifact_id)
    comment_id = f"cmt-{uuid4().hex}"
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('artifact_comments')} (comment_id, tenant_id, project_id, artifact_id, version_ref, author, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (comment_id, artifact["tenant_id"], project_id, artifact_id, ref.version_ref, author, body, _now()),
        )
        _append_event(db, tenant_id=artifact["tenant_id"], project_id=project_id, event_type=ActivityType.COMMENT, actor=author,
                      subject_ref=ref.version_ref, payload={"comment_id": comment_id})
        row = db.execute(f"SELECT * FROM {table('artifact_comments')} WHERE comment_id = ?", (comment_id,)).fetchone()
    return normalize_record(row)


def request_artifact_edit(*, project_id: str, artifact_id: str, base_version_ref: str, instruction: str, actor: str) -> dict:
    artifact = get_artifact(artifact_id)
    if artifact is None or artifact["project_id"] != project_id:
        raise ProjectNotFoundError("artifact not found in project")
    head = f"{artifact_id}:v{artifact['version']}"
    if base_version_ref != head:
        raise StaleArtifactVersionError(f"edit requested against {base_version_ref}, head is {head}")
    request_id = f"edit-{uuid4().hex}"
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('artifact_edit_requests')}
            (request_id, tenant_id, project_id, artifact_id, base_version_ref, instruction, status, requested_by, created_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, NULL)
            """,
            (request_id, artifact["tenant_id"], project_id, artifact_id, head, instruction, actor, _now()),
        )
        _append_event(db, tenant_id=artifact["tenant_id"], project_id=project_id, event_type=ActivityType.EDIT_REQUESTED,
                      actor=actor, subject_ref=head, payload={"request_id": request_id})
        row = db.execute(f"SELECT * FROM {table('artifact_edit_requests')} WHERE request_id = ?", (request_id,)).fetchone()
    return normalize_record(row)


# --------------------------------------------------------------------------
# Content atoms + items
# --------------------------------------------------------------------------


def _atom(row: Any) -> ContentAtom:
    r = normalize_record(row)
    return ContentAtom(
        atom_id=r["atom_id"], tenant_id=r["tenant_id"], project_id=r["project_id"], campaign_id=r.get("campaign_id"),
        title=r["title"], claims=tuple(Claim(**claim) for claim in _list(r.get("claims"))),
        source_refs=tuple(_list(r.get("source_refs"))), version=int(r["version"]), content_hash=r["content_hash"],
        created_at=str(r["created_at"]),
    )


def save_content_atom(
    *,
    tenant_id: str,
    project_id: str,
    actor: str,
    title: str,
    claims: Iterable[Mapping[str, Any]],
    source_refs: Iterable[str] = (),
    atom_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> dict[str, Any]:
    require_project_workspace(project_id)
    parsed = tuple(Claim(**dict(claim)) for claim in claims)
    if not parsed:
        raise ValueError("a content atom needs at least one claim")
    if len({claim.claim_id for claim in parsed}) != len(parsed):
        raise ValueError("claim ids must be unique within an atom")
    refs = tuple(sorted(set(source_refs)))
    digest = atom_hash(title, parsed, refs)
    atom_id = atom_id or f"atom-{uuid4().hex[:16]}"
    with transaction(write=True) as db:
        latest = db.execute(
            f"SELECT * FROM {table('content_atoms')} WHERE atom_id = ? ORDER BY version DESC LIMIT 1", (atom_id,)
        ).fetchone()
        if latest is not None:
            current = _atom(latest)
            if current.project_id != project_id:
                raise ProjectConflictError("atom belongs to a different project")
            if current.content_hash == digest:
                return {"atom": current, "created": False}
            version = current.version + 1
        else:
            version = 1
        db.execute(
            f"""
            INSERT INTO {table('content_atoms')} (atom_id, version, tenant_id, project_id, campaign_id, title, claims, source_refs, content_hash, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (atom_id, version, tenant_id, project_id, campaign_id, title,
             json_param([claim.model_dump(mode="json") for claim in parsed]), json_param(list(refs)), digest, actor, _now()),
        )
        row = db.execute(f"SELECT * FROM {table('content_atoms')} WHERE atom_id = ? AND version = ?", (atom_id, version)).fetchone()
    return {"atom": _atom(row), "created": True}


def get_content_atom(atom_id: str, version: Optional[int] = None) -> Optional[ContentAtom]:
    with transaction() as db:
        if version is None:
            row = db.execute(f"SELECT * FROM {table('content_atoms')} WHERE atom_id = ? ORDER BY version DESC LIMIT 1", (atom_id,)).fetchone()
        else:
            row = db.execute(f"SELECT * FROM {table('content_atoms')} WHERE atom_id = ? AND version = ?", (atom_id, version)).fetchone()
    return _atom(row) if row else None


def list_content_atoms(project_id: str) -> list[ContentAtom]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('content_atoms')} WHERE project_id = ? ORDER BY atom_id, version", (project_id,)).fetchall()
    latest: dict[str, ContentAtom] = {}
    for row in rows:
        atom = _atom(row)
        latest[atom.atom_id] = atom
    return list(latest.values())


def _item(row: Any) -> ContentItem:
    r = normalize_record(row)
    return ContentItem(
        content_item_id=r["content_item_id"], tenant_id=r["tenant_id"], project_id=r["project_id"], campaign_id=r.get("campaign_id"),
        atom_id=r.get("atom_id"), artifact_id=r.get("artifact_id"), kind=r["kind"], channel=r["channel"], title=r["title"],
        state=r["state"], version=int(r["version"]), claim_refs=tuple(_list(r.get("claim_refs"))), rights_ref=r.get("rights_ref"),
        approved_version=r.get("approved_version"), approval_ref=r.get("approval_ref"),
        evidence_fresh_until=_ts(r.get("evidence_fresh_until")), created_by=r["created_by"],
        created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def _item_body(item_id: str) -> dict:
    with transaction() as db:
        row = db.execute(f"SELECT body FROM {table('content_items')} WHERE content_item_id = ?", (item_id,)).fetchone()
    return _dict(normalize_record(row)["body"]) if row else {}


def get_content_item(item_id: str) -> Optional[ContentItem]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('content_items')} WHERE content_item_id = ?", (item_id,)).fetchone()
    return _item(row) if row else None


def _scoped_item(item_id: str, project_id: str) -> ContentItem:
    item = get_content_item(item_id)
    if item is None or item.project_id != project_id:
        raise ProjectNotFoundError("content item not found in project")
    return item


def list_content_items(project_id: str, *, state: Optional[str] = None) -> list[ContentItem]:
    query = f"SELECT * FROM {table('content_items')} WHERE project_id = ?"
    params: list[Any] = [project_id]
    if state:
        query += " AND state = ?"
        params.append(state)
    query += " ORDER BY updated_at DESC, content_item_id"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_item(row) for row in rows]


def create_content_item_from_atom(
    *,
    project_id: str,
    actor: str,
    atom_id: str,
    kind: str,
    channel: str,
    adapter: StorageAdapter,
    campaign_id: Optional[str] = None,
    evidence_fresh_until: Optional[str] = None,
) -> ContentItem:
    """Derive a channel-native variant and register it in the N4 registry."""
    atom = get_content_atom(atom_id)
    if atom is None or atom.project_id != project_id:
        raise ProjectNotFoundError("content atom not found in project")
    variant = derive_variant(atom, kind, channel)
    artifact_type, _ = CONTENT_KIND_ARTIFACT[variant.kind.value]
    item_id = f"cnt-{uuid4().hex[:16]}"
    evidence = sorted({ref for claim in atom.claims if claim.claim_id in variant.claim_refs for ref in claim.evidence_refs})
    artifact = create_project_artifact(
        tenant_id=atom.tenant_id,
        project_id=project_id,
        actor=actor,
        artifact_key=f"content-{item_id}",
        artifact_type=artifact_type,
        adapter=adapter,
        content_text=json.dumps(variant.model_dump(mode="json"), indent=2, sort_keys=True),
        subtype=variant.kind.value,
        v2={"channel": channel, "campaign_id": campaign_id or atom.campaign_id, "evidence_refs": evidence,
            "source_refs": list(atom.source_refs), "mime_type": "application/json"},
    )
    now = _now()
    body = {"variant": variant.model_dump(mode="json"), "release_blockers": list(variant.release_blockers)}
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('content_items')}
            (content_item_id, tenant_id, project_id, campaign_id, atom_id, atom_version, artifact_id, kind, channel, title, state, version,
             body, claim_refs, rights_ref, approved_version, approval_ref, evidence_fresh_until, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PLANNED', 1, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            (item_id, atom.tenant_id, project_id, campaign_id or atom.campaign_id, atom.atom_id, atom.version, artifact.artifact_id,
             variant.kind.value, channel, variant.title, json_param(body), json_param(list(variant.claim_refs)),
             evidence_fresh_until, actor, now, now),
        )
        _append_event(db, tenant_id=atom.tenant_id, project_id=project_id, event_type=ActivityType.VARIANT_READY, actor=actor,
                      subject_ref=artifact.version_ref, payload={"content_item_id": item_id, "kind": variant.kind.value, "channel": channel,
                                                                  "release_blockers": list(variant.release_blockers)})
    return get_content_item(item_id)


def transition_content_item(
    *,
    project_id: str,
    item_id: str,
    target: str,
    actor: str,
    expected_version: Optional[int] = None,
) -> ContentItem:
    """Move a content item through its lifecycle.

    Entering APPROVED is an approval decision: callers must already have run
    the separation-of-duties check (``approval_authority.assert_may_decide``).
    """
    item = _scoped_item(item_id, project_id)
    if expected_version is not None and expected_version != item.version:
        raise StaleArtifactVersionError(f"content item is at v{item.version}, request was for v{expected_version}")
    body = _item_body(item_id)
    assert_content_transition(
        item.state, target, version=item.version, approved_version=item.approved_version,
        release_blockers=body.get("release_blockers") or (),
    )
    approved_version = item.approved_version
    approval_ref = item.approval_ref
    event_type = ActivityType.MESSAGE
    if target == "APPROVED":
        approved_version = item.version
        approval_ref = f"content-approval:{item_id}:v{item.version}:{actor}"
        event_type = ActivityType.APPROVED
    elif target == "IN_PRODUCTION" and item.state in {"REVIEW", "APPROVED", "READY"}:
        approved_version, approval_ref = None, None
        event_type = ActivityType.REJECTED if item.state == "REVIEW" else ActivityType.MESSAGE
    elif target == "REVIEW":
        event_type = ActivityType.APPROVAL_REQUIRED
    with transaction(write=True) as db:
        cursor = db.execute(
            f"""
            UPDATE {table('content_items')} SET state = ?, approved_version = ?, approval_ref = ?, updated_at = ?
            WHERE content_item_id = ? AND state = ? AND version = ?
            """,
            (target, approved_version, approval_ref, _now(), item_id, item.state.value, item.version),
        )
        if cursor.rowcount != 1:
            raise ProjectConflictError("content item changed concurrently")
        if target in {"IN_PRODUCTION", "ARCHIVED", "READY"} and item.state.value in {"SCHEDULED", "DUE", "READY", "APPROVED"}:
            _cancel_item_jobs(db, item_id, "ITEM_LEFT_SCHEDULE")
        _append_event(db, tenant_id=item.tenant_id, project_id=project_id, event_type=event_type, actor=actor,
                      subject_ref=f"content:{item_id}:v{item.version}", payload={"from": item.state.value, "to": target})
    return get_content_item(item_id)


def revise_content_item(*, project_id: str, item_id: str, actor: str, expected_version: int, body_patch: Mapping[str, Any], adapter: StorageAdapter) -> ContentItem:
    """Edit content. Any edit invalidates the approval (it was bound to the old
    version) and cancels pending publication of the old version."""
    item = _scoped_item(item_id, project_id)
    if expected_version != item.version:
        raise StaleArtifactVersionError(f"content item is at v{item.version}, edit was based on v{expected_version}")
    if item.state.value in {"PUBLISHING", "PUBLISHED", "ARCHIVED"}:
        raise ContentTransitionError(f"content in {item.state.value} cannot be edited in place")
    body = _item_body(item_id)
    body["draft"] = {**dict(body.get("draft") or {}), **dict(body_patch)}
    new_state = "IN_PRODUCTION" if item.state.value in CONTENT_REVIEW_STATES else item.state.value
    if item.artifact_id:
        artifact = get_artifact(item.artifact_id)
        revise_project_artifact(
            project_id=project_id, artifact_id=item.artifact_id, actor=actor, adapter=adapter,
            expected_version=int(artifact["version"]), content_text=json.dumps(body, indent=2, sort_keys=True),
        )
    with transaction(write=True) as db:
        cursor = db.execute(
            f"""
            UPDATE {table('content_items')} SET version = ?, body = ?, state = ?, updated_at = ?
            WHERE content_item_id = ? AND version = ?
            """,
            (item.version + 1, json_param(body), new_state, _now(), item_id, item.version),
        )
        if cursor.rowcount != 1:
            raise StaleArtifactVersionError("content item changed concurrently")
        _cancel_item_jobs(db, item_id, "CONTENT_REVISED")
        _append_event(db, tenant_id=item.tenant_id, project_id=project_id, event_type=ActivityType.ARTIFACT_UPDATED, actor=actor,
                      subject_ref=f"content:{item_id}:v{item.version + 1}", payload={"approval_invalidated": item.approved_version is not None})
    return get_content_item(item_id)


def _cancel_item_jobs(db: Any, item_id: str, reason: str) -> None:
    db.execute(
        f"""
        UPDATE {table('scheduled_jobs')} SET status = 'CANCELLED', block_reasons = ?, updated_at = ?
        WHERE content_item_id = ? AND status IN ('PENDING','BLOCKED')
        """,
        (json_param([reason]), _now(), item_id),
    )
    db.execute(
        f"UPDATE {table('schedule_slots')} SET state = 'released', content_item_id = NULL WHERE content_item_id = ? AND state = 'filled'",
        (item_id,),
    )


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------


def _calendar(row: Any) -> Calendar:
    r = normalize_record(row)
    return Calendar(calendar_id=r["calendar_id"], tenant_id=r["tenant_id"], project_id=r["project_id"], name=r["name"],
                    timezone=r["timezone"], created_at=str(r["created_at"]))


def _slot(row: Any) -> ScheduleSlot:
    r = normalize_record(row)
    return ScheduleSlot(slot_id=r["slot_id"], calendar_id=r["calendar_id"], tenant_id=r["tenant_id"], project_id=r["project_id"],
                        content_item_id=r.get("content_item_id"), channel=r["channel"], scheduled_for=str(r["scheduled_for"]),
                        state=r["state"], created_at=str(r["created_at"]))


def _job(row: Any) -> ScheduledJob:
    r = normalize_record(row)
    return ScheduledJob(
        job_id=r["job_id"], tenant_id=r["tenant_id"], project_id=r["project_id"], slot_id=r.get("slot_id"),
        content_item_id=r.get("content_item_id"), job_kind=r["job_kind"], due_at=str(r["due_at"]), status=r["status"],
        idempotency_key=r["idempotency_key"], outbox_message_id=r.get("outbox_message_id"),
        block_reasons=tuple(_list(r.get("block_reasons"))), payload=_dict(r.get("payload")), attempts=int(r["attempts"]),
        created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def create_calendar(*, tenant_id: str, project_id: str, name: str, timezone_name: str = "UTC") -> Calendar:
    require_project_workspace(project_id)
    calendar_id = f"cal-{uuid4().hex[:16]}"
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('calendars')} (calendar_id, tenant_id, project_id, name, timezone, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (calendar_id, tenant_id, project_id, name, timezone_name, _now()),
        )
        row = db.execute(f"SELECT * FROM {table('calendars')} WHERE calendar_id = ?", (calendar_id,)).fetchone()
    return _calendar(row)


def list_calendars(project_id: str) -> list[Calendar]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('calendars')} WHERE project_id = ? ORDER BY created_at", (project_id,)).fetchall()
    return [_calendar(row) for row in rows]


def _scoped_calendar(calendar_id: str, project_id: str) -> Calendar:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('calendars')} WHERE calendar_id = ?", (calendar_id,)).fetchone()
    if row is None or _calendar(row).project_id != project_id:
        raise ProjectNotFoundError("calendar not found in project")
    return _calendar(row)


def plan_calendar(*, project_id: str, calendar_id: str, horizon_days: int, cadences: Iterable[ScheduleCadence], start: datetime) -> list[ScheduleSlot]:
    """Materialize open slots months ahead. Re-planning is idempotent: a slot
    for the same calendar, channel and time is never duplicated."""
    calendar = _scoped_calendar(calendar_id, project_id)
    planned = plan_horizon(start=start, horizon_days=horizon_days, cadences=list(cadences))
    created: list[ScheduleSlot] = []
    with transaction(write=True) as db:
        for slot in planned:
            exists = db.execute(
                f"SELECT slot_id FROM {table('schedule_slots')} WHERE calendar_id = ? AND channel = ? AND scheduled_for = ? AND state <> 'cancelled'",
                (calendar_id, slot["channel"], slot["scheduled_for"]),
            ).fetchone()
            if exists:
                continue
            slot_id = f"slot-{uuid4().hex[:16]}"
            db.execute(
                f"INSERT INTO {table('schedule_slots')} (slot_id, calendar_id, tenant_id, project_id, content_item_id, channel, scheduled_for, state, created_at) VALUES (?, ?, ?, ?, NULL, ?, ?, 'open', ?)",
                (slot_id, calendar_id, calendar.tenant_id, project_id, slot["channel"], slot["scheduled_for"], _now()),
            )
            created.append(_slot(db.execute(f"SELECT * FROM {table('schedule_slots')} WHERE slot_id = ?", (slot_id,)).fetchone()))
    return created


def list_slots(project_id: str, *, calendar_id: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None) -> list[ScheduleSlot]:
    query = f"SELECT * FROM {table('schedule_slots')} WHERE project_id = ?"
    params: list[Any] = [project_id]
    if calendar_id:
        query += " AND calendar_id = ?"
        params.append(calendar_id)
    if start:
        query += " AND scheduled_for >= ?"
        params.append(start)
    if end:
        query += " AND scheduled_for < ?"
        params.append(end)
    query += " ORDER BY scheduled_for, slot_id"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_slot(row) for row in rows]


def list_jobs(project_id: str, *, status: Optional[str] = None) -> list[ScheduledJob]:
    query = f"SELECT * FROM {table('scheduled_jobs')} WHERE project_id = ?"
    params: list[Any] = [project_id]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY due_at, job_id"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_job(row) for row in rows]


def _insert_job(db: Any, *, tenant_id: str, project_id: str, kind: str, due_at: str, idempotency_key: str,
                content_item_id: Optional[str], slot_id: Optional[str], payload: Mapping[str, Any]) -> str:
    existing = db.execute(f"SELECT job_id FROM {table('scheduled_jobs')} WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    if existing is not None:
        return normalize_record(existing)["job_id"]
    job_id = f"job-{uuid4().hex[:20]}"
    now = _now()
    db.execute(
        f"""
        INSERT INTO {table('scheduled_jobs')}
        (job_id, tenant_id, project_id, slot_id, content_item_id, job_kind, due_at, status, idempotency_key, outbox_message_id, block_reasons, payload, attempts, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, NULL, ?, ?, 0, ?, ?)
        """,
        (job_id, tenant_id, project_id, slot_id, content_item_id, kind, due_at, idempotency_key, json_param([]), json_param(dict(payload)), now, now),
    )
    return job_id


def schedule_content_item(*, project_id: str, item_id: str, actor: str, scheduled_for: Optional[str] = None, slot_id: Optional[str] = None) -> ScheduledJob:
    item = _scoped_item(item_id, project_id)
    if slot_id:
        with transaction() as db:
            row = db.execute(f"SELECT * FROM {table('schedule_slots')} WHERE slot_id = ?", (slot_id,)).fetchone()
        if row is None or _slot(row).project_id != project_id:
            raise ProjectNotFoundError("slot not found in project")
        slot = _slot(row)
        if slot.state != "open":
            raise ProjectConflictError("slot is not open")
        scheduled_for = slot.scheduled_for
    if not scheduled_for:
        raise ValueError("scheduled_for or slot_id is required")
    body = _item_body(item_id)
    assert_content_transition(item.state, "SCHEDULED", version=item.version, approved_version=item.approved_version,
                              release_blockers=body.get("release_blockers") or ())
    key = f"publish:{item_id}:v{item.version}:{parse_ts(scheduled_for).isoformat()}"
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('content_items')} SET state = 'SCHEDULED', updated_at = ? WHERE content_item_id = ? AND state = ? AND version = ?",
            (_now(), item_id, item.state.value, item.version),
        )
        if cursor.rowcount != 1:
            raise ProjectConflictError("content item changed concurrently")
        if slot_id:
            db.execute(f"UPDATE {table('schedule_slots')} SET state = 'filled', content_item_id = ? WHERE slot_id = ? AND state = 'open'", (item_id, slot_id))
        job_id = _insert_job(db, tenant_id=item.tenant_id, project_id=project_id, kind="PUBLISH", due_at=parse_ts(scheduled_for).isoformat(),
                             idempotency_key=key, content_item_id=item_id, slot_id=slot_id,
                             payload={"version": item.version, "channel": item.channel})
        _append_event(db, tenant_id=item.tenant_id, project_id=project_id, event_type=ActivityType.SCHEDULED, actor=actor,
                      subject_ref=f"content:{item_id}:v{item.version}", payload={"job_id": job_id, "scheduled_for": scheduled_for})
        row = db.execute(f"SELECT * FROM {table('scheduled_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
    return _job(row)


def schedule_refresh(*, project_id: str, item_id: str, due_at: str) -> ScheduledJob:
    """EvergreenRefreshEngine: one refresh job per item version."""
    item = _scoped_item(item_id, project_id)
    with transaction(write=True) as db:
        job_id = _insert_job(db, tenant_id=item.tenant_id, project_id=project_id, kind="REFRESH", due_at=parse_ts(due_at).isoformat(),
                             idempotency_key=f"refresh:{item_id}:v{item.version}", content_item_id=item_id, slot_id=None,
                             payload={"version": item.version})
        row = db.execute(f"SELECT * FROM {table('scheduled_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
    return _job(row)


def schedule_journey(*, tenant_id: str, project_id: str, journey: str, start: datetime, steps: Iterable[Mapping[str, Any]]) -> list[ScheduledJob]:
    """CRM/lifecycle journeys reuse the scheduler: each step is a LIFECYCLE job
    that delivers an approved content item through the same publication path."""
    from datetime import timedelta

    require_project_workspace(project_id)
    jobs: list[ScheduledJob] = []
    with transaction(write=True) as db:
        for index, step in enumerate(steps):
            item_id = str(step["content_item_id"])
            item_row = db.execute(f"SELECT * FROM {table('content_items')} WHERE content_item_id = ?", (item_id,)).fetchone()
            if item_row is None or _item(item_row).project_id != project_id:
                raise ProjectNotFoundError(f"journey step {index} references an unknown content item")
            due = (start + timedelta(days=float(step.get("delay_days", 0)))).isoformat()
            job_id = _insert_job(
                db, tenant_id=tenant_id, project_id=project_id, kind="LIFECYCLE", due_at=due,
                idempotency_key=f"journey:{journey}:{index}:{item_id}:{due}", content_item_id=item_id, slot_id=None,
                payload={"journey": journey, "step": index, "trigger": step.get("trigger") or "time", "channel": step.get("channel") or _item(item_row).channel},
            )
            jobs.append(_job(db.execute(f"SELECT * FROM {table('scheduled_jobs')} WHERE job_id = ?", (job_id,)).fetchone()))
    return jobs


# --------------------------------------------------------------------------
# Scheduler tick
# --------------------------------------------------------------------------


def _gate_for(item: ContentItem, *, now: datetime) -> list[str]:
    body = _item_body(item.content_item_id)
    dependency_statuses: dict[str, str] = {}
    rights = None
    media_rights = False
    if item.artifact_id:
        artifact = get_artifact(item.artifact_id)
        if artifact is not None:
            if artifact["status"] in {"invalidated", "review_required", "archived"}:
                dependency_statuses[artifact["artifact_id"]] = artifact["status"]
            v2 = (artifact.get("metadata") or {}).get("v2") or {}
            media_rights = v2.get("media_type") in {"image", "video", "audio"}
            if media_rights or v2.get("rights_ref") or item.rights_ref:
                rights = rights_status(item.artifact_id, at=now.isoformat())
    return due_gate(
        GateInput(
            state=item.state.value,
            version=item.version,
            approved_version=item.approved_version,
            approval_ref=item.approval_ref,
            release_blockers=tuple(body.get("release_blockers") or ()),
            evidence_fresh_until=item.evidence_fresh_until,
            dependency_statuses=dependency_statuses,
            rights_required=media_rights or (requires_rights(item.kind) and rights is not None),
            rights=rights,
        ),
        now=now,
    )


def _set_job(db: Any, job_id: str, *, status: str, from_statuses: tuple[str, ...], reasons: Iterable[str] = (), outbox_message_id: Optional[str] = None, bump_attempt: bool = False) -> bool:
    placeholders = ",".join("?" for _ in from_statuses)
    cursor = db.execute(
        f"""
        UPDATE {table('scheduled_jobs')}
        SET status = ?, block_reasons = ?, outbox_message_id = COALESCE(?, outbox_message_id),
            attempts = attempts + ?, updated_at = ?
        WHERE job_id = ? AND status IN ({placeholders})
        """,
        (status, json_param(list(reasons)), outbox_message_id, 1 if bump_attempt else 0, _now(), job_id, *from_statuses),
    )
    return cursor.rowcount == 1


def _move_item(db: Any, item: ContentItem, target: str) -> None:
    db.execute(
        f"UPDATE {table('content_items')} SET state = ?, updated_at = ? WHERE content_item_id = ? AND version = ?",
        (target, _now(), item.content_item_id, item.version),
    )


def run_scheduler_tick(*, now: datetime, worker_id: str, project_id: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    """Process due jobs. Safe to run concurrently and repeatedly."""
    query = f"SELECT * FROM {table('scheduled_jobs')} WHERE status IN ('PENDING','BLOCKED') AND due_at <= ?"
    params: list[Any] = [now.isoformat()]
    if project_id:
        query += " AND project_id = ?"
        params.append(project_id)
    query += " ORDER BY due_at, job_id LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with transaction() as db:
        due = [_job(row) for row in db.execute(query, params).fetchall()]
    results = []
    for job in due:
        if job.job_kind.value == "REFRESH":
            results.append(_run_refresh(job))
        else:
            results.append(_run_delivery(job, now=now, worker_id=worker_id))
    return {"processed": len(results), "results": results, "tick_at": now.isoformat()}


def _run_refresh(job: ScheduledJob) -> dict[str, Any]:
    item = get_content_item(job.content_item_id or "")
    with transaction(write=True) as db:
        if item is None or item.version != job.payload.get("version") or item.state.value not in {"VERIFIED", "MEASURED"}:
            _set_job(db, job.job_id, status="CANCELLED", from_statuses=("PENDING", "BLOCKED"), reasons=["ITEM_NOT_REFRESHABLE"])
            return {"job_id": job.job_id, "status": "CANCELLED"}
        if not _set_job(db, job.job_id, status="DELIVERED", from_statuses=("PENDING", "BLOCKED"), bump_attempt=True):
            return {"job_id": job.job_id, "status": "ALREADY_CLAIMED"}
        _move_item(db, item, "REFRESH_DUE")
        _append_event(db, tenant_id=item.tenant_id, project_id=item.project_id, event_type=ActivityType.WORK_STARTED, actor="system:scheduler",
                      subject_ref=f"content:{item.content_item_id}:v{item.version}", payload={"refresh_due": True, "job_id": job.job_id})
    return {"job_id": job.job_id, "status": "DELIVERED"}


def _run_delivery(job: ScheduledJob, *, now: datetime, worker_id: str) -> dict[str, Any]:
    item = get_content_item(job.content_item_id or "")
    lifecycle = job.job_kind.value == "LIFECYCLE"
    stale = item is None or (not lifecycle and (item.version != job.payload.get("version") or item.state.value not in {"SCHEDULED", "DUE"}))
    if stale:
        with transaction(write=True) as db:
            _set_job(db, job.job_id, status="CANCELLED", from_statuses=("PENDING", "BLOCKED"), reasons=["ITEM_CHANGED_SINCE_SCHEDULING"])
        return {"job_id": job.job_id, "status": "CANCELLED"}

    reasons = _gate_for(item, now=now)
    channel = str(job.payload.get("channel") or item.channel)
    if not reasons:
        try:
            resolve_provider(channel)
        except PublicationBlocked as exc:
            reasons = [f"PUBLICATION_UNAVAILABLE:{exc}"]
    if reasons:
        with transaction(write=True) as db:
            changed = list(reasons) != list(job.block_reasons)
            _set_job(db, job.job_id, status="BLOCKED", from_statuses=("PENDING", "BLOCKED"), reasons=reasons)
            if changed:
                _append_event(db, tenant_id=item.tenant_id, project_id=item.project_id, event_type=ActivityType.QA_BLOCKED, actor="system:scheduler",
                              subject_ref=f"content:{item.content_item_id}:v{item.version}", payload={"job_id": job.job_id, "reasons": reasons})
        return {"job_id": job.job_id, "status": "BLOCKED", "reasons": reasons}

    live = publication_mode() is ProviderMode.LIVE
    message_id = f"outbox-{job.job_id}"
    with transaction(write=True) as db:
        if not _set_job(db, job.job_id, status="ENQUEUED", from_statuses=("PENDING", "BLOCKED"), outbox_message_id=message_id, bump_attempt=True):
            # Another tick claimed it first: duplicate delivery prevented.
            return {"job_id": job.job_id, "status": "ALREADY_CLAIMED"}
        if live and not lifecycle and item.state.value == "SCHEDULED":
            _move_item(db, item, "DUE")

    from services.langgraph.agency.reliability.outbox import OutboxDispatcher
    from services.langgraph.app.runtime_support import trust_kernel

    kernel = trust_kernel()
    kernel.bind_project(tenant_id=item.tenant_id, project_id=item.project_id)
    kernel.enqueue_outbox(
        tenant_id=item.tenant_id, project_id=item.project_id, message_id=message_id, topic=PUBLICATION_TOPIC,
        payload={"job_id": job.job_id, "content_item_id": item.content_item_id, "version": item.version, "channel": channel},
        payload_ref=f"scheduled_job:{job.job_id}", idempotency_key=job.idempotency_key,
    )
    dispatcher = OutboxDispatcher(
        kernel,
        authorize_delivery=lambda message: message.topic == PUBLICATION_TOPIC and message.project_id == item.project_id and message.tenant_id == item.tenant_id,
    )
    dispatcher.register(PUBLICATION_TOPIC, lambda message: execute_publication(job_id=job.job_id, worker_id=worker_id))
    delivery = dispatcher.dispatch_one(message_id=message_id, worker_id=worker_id)
    with transaction(write=True) as db:
        if delivery.status in {"DELIVERED", "ALREADY_DELIVERED"}:
            _set_job(db, job.job_id, status="DELIVERED", from_statuses=("ENQUEUED",))
        else:
            _set_job(db, job.job_id, status="FAILED", from_statuses=("ENQUEUED",), reasons=[delivery.error or delivery.status])
    return {"job_id": job.job_id, "status": delivery.status, "attempt_id": delivery.result_ref}


# --------------------------------------------------------------------------
# Publication pipeline
# --------------------------------------------------------------------------


def _attempt(row: Any) -> PublicationAttempt:
    r = normalize_record(row)
    return PublicationAttempt(
        attempt_id=r["attempt_id"], tenant_id=r["tenant_id"], project_id=r["project_id"], job_id=r.get("job_id"),
        content_item_id=r["content_item_id"], provider=r["provider"], mode=r["mode"], state=r["state"], request_hash=r["request_hash"],
        idempotency_key=r["idempotency_key"], external_ref=r.get("external_ref"), readback=_dict(r.get("readback")), error=r.get("error"),
        created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def _set_attempt(attempt_id: str, state: PublicationState, **fields: Any) -> None:
    columns = ["state = ?", "updated_at = ?"]
    params: list[Any] = [state.value, _now()]
    for key, value in fields.items():
        columns.append(f"{key} = ?")
        params.append(json_param(value) if key == "readback" else value)
    params.append(attempt_id)
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('publication_attempts')} SET {', '.join(columns)} WHERE attempt_id = ?", params)


def _receipt(attempt: PublicationAttempt, kind: str, payload: Mapping[str, Any]) -> None:
    data = json.loads(json.dumps(payload, default=str))
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('publication_receipts')} (receipt_id, attempt_id, tenant_id, project_id, kind, payload, receipt_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"rcpt-{uuid4().hex}", attempt.attempt_id, attempt.tenant_id, attempt.project_id, kind, json_param(data), sha256_bytes(canonical_json(data)), _now()),
        )


def list_publication_attempts(project_id: str, *, content_item_id: Optional[str] = None) -> list[PublicationAttempt]:
    query = f"SELECT * FROM {table('publication_attempts')} WHERE project_id = ?"
    params: list[Any] = [project_id]
    if content_item_id:
        query += " AND content_item_id = ?"
        params.append(content_item_id)
    query += " ORDER BY created_at, attempt_id"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_attempt(row) for row in rows]


def list_publication_receipts(attempt_id: str) -> list[PublicationReceipt]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('publication_receipts')} WHERE attempt_id = ? ORDER BY created_at, receipt_id", (attempt_id,)).fetchall()
    receipts = []
    for row in rows:
        r = normalize_record(row)
        receipts.append(PublicationReceipt(receipt_id=r["receipt_id"], attempt_id=r["attempt_id"], tenant_id=r["tenant_id"], project_id=r["project_id"],
                                           kind=r["kind"], payload=_dict(r.get("payload")), receipt_hash=r["receipt_hash"], created_at=str(r["created_at"])))
    return receipts


def execute_publication(*, job_id: str, worker_id: str) -> str:
    """The outbox handler: drive one attempt through the provider contract."""
    with transaction() as db:
        job_row = db.execute(f"SELECT * FROM {table('scheduled_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
    job = _job(job_row)
    item = get_content_item(job.content_item_id or "")
    channel = str(job.payload.get("channel") or item.channel)
    provider = resolve_provider(channel)
    live = provider.mode is ProviderMode.LIVE
    lifecycle = job.job_kind.value == "LIFECYCLE"
    body = _item_body(item.content_item_id)
    request = PublicationRequest(
        tenant_id=item.tenant_id, project_id=item.project_id, content_item_id=item.content_item_id, version=item.version,
        channel=channel, body={"variant": body.get("variant"), "draft": body.get("draft")}, idempotency_key=job.idempotency_key,
    )
    with transaction(write=True) as db:
        existing = db.execute(
            f"SELECT * FROM {table('publication_attempts')} WHERE provider = ? AND idempotency_key = ?",
            (provider.name, job.idempotency_key),
        ).fetchone()
        if existing is None:
            attempt_id = f"pub-{uuid4().hex[:20]}"
            db.execute(
                f"""
                INSERT INTO {table('publication_attempts')}
                (attempt_id, tenant_id, project_id, job_id, content_item_id, provider, mode, state, request_hash, idempotency_key, external_ref, readback, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'SPEC', ?, ?, NULL, ?, NULL, ?, ?)
                """,
                (attempt_id, item.tenant_id, item.project_id, job.job_id, item.content_item_id, provider.name, provider.mode.value,
                 request.request_hash(), job.idempotency_key, json_param({}), _now(), _now()),
            )
            existing = db.execute(f"SELECT * FROM {table('publication_attempts')} WHERE attempt_id = ?", (attempt_id,)).fetchone()
    attempt = _attempt(existing)
    if attempt.state is PublicationState.VERIFIED:
        return attempt.attempt_id
    if attempt.state is PublicationState.UNCERTAIN:
        return _reconcile(attempt, provider, item=item, live=live and not lifecycle)

    prepared = provider.prepare(request)
    problems = provider.validate(prepared)
    if problems:
        _set_attempt(attempt.attempt_id, PublicationState.FAILED, error=",".join(problems))
        raise RuntimeError("PUBLICATION_VALIDATION_FAILED")
    _set_attempt(attempt.attempt_id, PublicationState.VALIDATED)

    permit = DispatchPermit(
        permit_id=f"permit-{attempt.attempt_id}",
        work_order_id=job.job_id,
        project_snapshot_hash=sha256_bytes(canonical_json({"item": item.content_item_id, "version": item.version, "request": request.request_hash()})),
        causal_epoch=item.version,
        dependency_version_refs=((f"{item.artifact_id}:v{get_artifact(item.artifact_id)['version']}",) if item.artifact_id else ()),
        authority_refs=(f"scheduler:{worker_id}",),
        approval_refs=((item.approval_ref,) if item.approval_ref else ()),
        tool_contract_refs=(f"publication-provider:{provider.name}",),
        eligibility_policy_version="amc-project-os/v1",
    )
    _receipt(attempt, "dispatch_permit", permit.model_dump(mode="json"))
    _set_attempt(attempt.attempt_id, PublicationState.AUTHORIZED)
    if item.approved_version != item.version or not item.approval_ref:
        _set_attempt(attempt.attempt_id, PublicationState.BLOCKED, error="APPROVAL_NOT_BOUND_TO_CURRENT_VERSION")
        raise RuntimeError("PUBLICATION_APPROVAL_STALE")
    _set_attempt(attempt.attempt_id, PublicationState.APPROVED)

    if live and not lifecycle:
        with transaction(write=True) as db:
            _move_item(db, item, "PUBLISHING")
    _set_attempt(attempt.attempt_id, PublicationState.EXECUTING)
    started = datetime.now(timezone.utc)
    try:
        result = provider.publish(prepared, idempotency_key=job.idempotency_key)
    except ProviderUncertain as exc:
        _set_attempt(attempt.attempt_id, PublicationState.UNCERTAIN, error=f"UNCERTAIN:{type(exc).__name__}")
        _event_for(item, ActivityType.RECOVERING, {"attempt_id": attempt.attempt_id, "reason": "provider outcome unknown"})
        return _reconcile(_reload_attempt(attempt.attempt_id), provider, item=item, live=live and not lifecycle)
    except Exception as exc:
        _set_attempt(attempt.attempt_id, PublicationState.FAILED, error=type(exc).__name__)
        _after_failure(item, live=live and not lifecycle, attempt_id=attempt.attempt_id)
        raise
    _receipt(attempt, "execution", ExecutionReceipt(
        operation_id=attempt.attempt_id, work_order_id=job.job_id, actor_role_id="publisher", tool=provider.name,
        tool_contract_ref=f"publication-provider:{provider.name}", args_hash=request.request_hash(), target=channel,
        idempotency_key=job.idempotency_key, attempt=min(max(job.attempts, 1), 3), started_at=started,
        ended_at=datetime.now(timezone.utc), returned_state="PUBLISHED", result_ref=result.external_ref,
    ).model_dump(mode="json"))
    _set_attempt(attempt.attempt_id, PublicationState.READBACK, external_ref=result.external_ref)
    if live and not lifecycle:
        with transaction(write=True) as db:
            _move_item(db, item, "PUBLISHED")
    return _reconcile(_reload_attempt(attempt.attempt_id), provider, item=item, live=live and not lifecycle)


def _reload_attempt(attempt_id: str) -> PublicationAttempt:
    with transaction() as db:
        return _attempt(db.execute(f"SELECT * FROM {table('publication_attempts')} WHERE attempt_id = ?", (attempt_id,)).fetchone())


def _event_for(item: ContentItem, event_type: ActivityType, payload: dict) -> None:
    with transaction(write=True) as db:
        _append_event(db, tenant_id=item.tenant_id, project_id=item.project_id, event_type=event_type, actor="system:publisher",
                      subject_ref=f"content:{item.content_item_id}:v{item.version}", payload=payload)


def _after_failure(item: ContentItem, *, live: bool, attempt_id: str) -> None:
    if live:
        current = get_content_item(item.content_item_id)
        if current is not None and current.state.value in {"DUE", "PUBLISHING"}:
            with transaction(write=True) as db:
                _move_item(db, current, "SCHEDULED")
    _event_for(item, ActivityType.FAILED, {"attempt_id": attempt_id})


def _reconcile(attempt: PublicationAttempt, provider: Any, *, item: ContentItem, live: bool) -> str:
    """Read back by idempotency key. Never re-publishes to resolve doubt."""
    observed = provider.verify(idempotency_key=attempt.idempotency_key)
    if observed is None:
        _set_attempt(attempt.attempt_id, PublicationState.FAILED, error="READBACK_NOT_FOUND")
        _after_failure(item, live=live, attempt_id=attempt.attempt_id)
        raise RuntimeError("PUBLICATION_NOT_FOUND_ON_READBACK")
    matches = observed.observed.get("request_hash") == attempt.request_hash
    _receipt(attempt, "observation", ObservationReceipt(
        operation_id=attempt.attempt_id, target=attempt.provider,
        expected_postcondition={"request_hash": attempt.request_hash},
        observed_postcondition=dict(observed.observed), observation_method="provider.verify(idempotency_key)",
        evidence_refs=(observed.external_ref,), matches=matches,
    ).model_dump(mode="json"))
    if not matches:
        _set_attempt(attempt.attempt_id, PublicationState.FAILED, error="READBACK_MISMATCH", readback=dict(observed.observed))
        _after_failure(item, live=live, attempt_id=attempt.attempt_id)
        raise RuntimeError("PUBLICATION_READBACK_MISMATCH")
    _set_attempt(attempt.attempt_id, PublicationState.RECONCILED, external_ref=observed.external_ref, readback=dict(observed.observed))
    _set_attempt(attempt.attempt_id, PublicationState.VERIFIED)
    if live:
        current = get_content_item(item.content_item_id)
        with transaction(write=True) as db:
            if current is not None and current.state.value == "PUBLISHING":
                _move_item(db, current, "PUBLISHED")
                current = get_content_item(item.content_item_id)
            if current is not None and current.state.value == "PUBLISHED":
                _move_item(db, current, "VERIFIED")
        _event_for(item, ActivityType.PUBLISHED, {"attempt_id": attempt.attempt_id, "external_ref": observed.external_ref})
        _event_for(item, ActivityType.VERIFIED, {"attempt_id": attempt.attempt_id})
    else:
        # A dry run proves the path; it does not publish, so the item's
        # lifecycle state is left alone and the event says so.
        _event_for(item, ActivityType.MESSAGE, {"attempt_id": attempt.attempt_id, "dry_run": True, "attempt_state": "VERIFIED"})
    return attempt.attempt_id
