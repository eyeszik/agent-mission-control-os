"""Conversations, content atoms, calendar, the scheduler and publication."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from _project_os_support import as_user, client, export_root, new_project  # noqa: F401
from services.langgraph.agency.project_os import publishing
from services.langgraph.agency.project_os.content import ContentLineageError, assert_lineage, derive_variant, evidence_for
from services.langgraph.agency.project_os.publishing import ProviderResult, ProviderUncertain
from services.langgraph.agency.project_os.vocabulary import ProviderMode
from services.langgraph.persistence.project_ops import get_content_atom, run_scheduler_tick

CLAIMS = [
    {"claim_id": "c1", "text": "Our beans are roasted within 48 hours of shipping.", "evidence_refs": ["ev:roast-log"], "verification": "VERIFIED"},
    {"claim_id": "c2", "text": "Single-origin from Huila, Colombia.", "evidence_refs": ["ev:supplier-cert"], "verification": "VERIFIED"},
]


@pytest.fixture(autouse=True)
def _env(monkeypatch, export_root):  # noqa: F811
    as_user(monkeypatch, "writer-1")
    monkeypatch.setenv("AMC_PUBLICATION_MODE", "dry_run")


def _atom(pid: str, claims=CLAIMS) -> dict:
    response = client.post(f"/projects/{pid}/content/atoms", json={"title": "Fresh roast", "claims": claims, "source_refs": ["src:ops"]})
    assert response.status_code == 201, response.text
    return response.json()["atom"]


def _item(pid: str, atom_id: str, kind: str = "social_post", channel: str = "linkedin") -> dict:
    response = client.post(f"/projects/{pid}/content/items", json={"atom_id": atom_id, "kind": kind, "channel": channel})
    assert response.status_code == 201, response.text
    return response.json()["item"]


def _move(pid: str, item_id: str, target: str, **body):
    return client.post(f"/projects/{pid}/content/items/{item_id}/transition", json={"target": target, **body})


def _approve(monkeypatch, pid: str, item_id: str) -> dict:
    for target in ("IN_PRODUCTION", "REVIEW"):
        assert _move(pid, item_id, target).status_code == 200
    as_user(monkeypatch, "editor-1", role="reviewer")
    approved = _move(pid, item_id, "APPROVED")
    assert approved.status_code == 200, approved.text
    as_user(monkeypatch, "writer-1")
    ready = _move(pid, item_id, "READY")
    assert ready.status_code == 200, ready.text
    return ready.json()["item"]


def test_conversation_messages_enter_the_project_activity_stream():
    pid = new_project()["project_id"]
    art = client.post(f"/projects/{pid}/artifacts", json={"artifact_key": "brief", "artifact_type": "creative_concept", "content_text": "x"}).json()["artifact"]
    thread = client.post(f"/projects/{pid}/threads", json={"title": "Launch planning"}).json()["thread"]
    message = client.post(
        f"/projects/{pid}/threads/{thread['thread_id']}/messages",
        json={"body": "Here is the brief", "activity_type": "ARTIFACT_CREATED", "artifact_refs": [{"artifact_id": art["artifact_id"], "relation": "created"}]},
    )
    assert message.status_code == 201, message.text
    events = client.get(f"/projects/{pid}/events", params={"thread_id": thread["thread_id"]}).json()["events"]
    assert [e["event_type"] for e in events][-1] == "ARTIFACT_CREATED"
    assert events[-1]["subject_ref"] == f"{art['artifact_id']}:v1"
    bad_version = client.post(f"/projects/{pid}/threads/{thread['thread_id']}/messages",
                              json={"body": "x", "artifact_refs": [{"artifact_id": art["artifact_id"], "version_ref": f"{art['artifact_id']}:v9"}]})
    assert bad_version.status_code == 409
    other = new_project("Other")["project_id"]
    foreign = client.post(f"/projects/{other}/threads/{thread['thread_id']}/messages", json={"body": "x"})
    assert foreign.status_code == 404


def test_edit_request_against_stale_version_is_rejected():
    pid = new_project()["project_id"]
    art = client.post(f"/projects/{pid}/artifacts", json={"artifact_key": "c", "artifact_type": "copy_variant", "content_text": "a"}).json()["artifact"]
    client.post(f"/projects/{pid}/artifacts/{art['artifact_id']}/revisions", json={"expected_version": 1, "content_text": "b"})
    stale = client.post(f"/projects/{pid}/artifacts/{art['artifact_id']}/edit-requests", json={"base_version_ref": f"{art['artifact_id']}:v1", "instruction": "shorter"})
    assert stale.status_code == 409
    fresh = client.post(f"/projects/{pid}/artifacts/{art['artifact_id']}/edit-requests", json={"base_version_ref": f"{art['artifact_id']}:v2", "instruction": "shorter"})
    assert fresh.status_code == 201


def test_content_atom_preserves_claim_evidence_across_derivatives():
    pid = new_project()["project_id"]
    atom = _atom(pid)
    model = get_content_atom(atom["atom_id"])
    for kind, channel in (("article", "web"), ("email", "email"), ("carousel", "instagram"), ("faq", "web"), ("ai_search_answer", "web")):
        variant = derive_variant(model, kind, channel)
        assert_lineage(model, variant)
        assert set(variant.claim_refs) <= {"c1", "c2"}
        assert all(evidence_for(model, variant)[ref] for ref in variant.claim_refs)
    tampered = derive_variant(model, "article", "web").model_copy(update={"claim_refs": ("c1", "c-invented")})
    with pytest.raises(ContentLineageError):
        assert_lineage(model, tampered)
    unchanged = client.post(f"/projects/{pid}/content/atoms", json={"title": "Fresh roast", "claims": CLAIMS, "source_refs": ["src:ops"], "atom_id": atom["atom_id"]}).json()
    assert unchanged["created"] is False


def test_unverified_claims_block_release_and_paid_formats_drop_them(monkeypatch):
    pid = new_project()["project_id"]
    claims = [*CLAIMS, {"claim_id": "c3", "text": "The best coffee in the world.", "evidence_refs": [], "verification": "UNVERIFIED"}]
    atom = _atom(pid, claims)
    model = get_content_atom(atom["atom_id"])
    assert "c3" not in derive_variant(model, "paid_creative", "meta").claim_refs
    article = _item(pid, atom["atom_id"], "article", "web")
    for target in ("IN_PRODUCTION", "REVIEW"):
        _move(pid, article["content_item_id"], target)
    as_user(monkeypatch, "editor-1", role="reviewer")
    assert _move(pid, article["content_item_id"], "APPROVED").status_code == 200
    blocked = _move(pid, article["content_item_id"], "READY")
    assert blocked.status_code == 409 and "UNVERIFIED_CLAIM:c3" in blocked.json()["detail"]


def test_creator_cannot_approve_their_own_content(monkeypatch):
    pid = new_project()["project_id"]
    item = _item(pid, _atom(pid)["atom_id"])
    for target in ("IN_PRODUCTION", "REVIEW"):
        _move(pid, item["content_item_id"], target)
    as_user(monkeypatch, "writer-1", role="reviewer")
    own = _move(pid, item["content_item_id"], "APPROVED")
    assert own.status_code == 403 and "cannot approve" in own.json()["detail"]
    as_user(monkeypatch, "intern-1", role="operator")
    assert _move(pid, item["content_item_id"], "APPROVED").status_code == 403
    as_user(monkeypatch, "editor-1", role="reviewer")
    approved = _move(pid, item["content_item_id"], "APPROVED").json()["item"]
    assert approved["approved_version"] == 1 and approved["approval_ref"].endswith(":editor-1")


def test_ready_requires_approval_bound_to_current_version(monkeypatch):
    pid = new_project()["project_id"]
    item = _item(pid, _atom(pid)["atom_id"])
    ready = _approve(monkeypatch, pid, item["content_item_id"])
    revised = client.post(f"/projects/{pid}/content/items/{item['content_item_id']}/revise", json={"expected_version": ready["version"], "body_patch": {"hook": "new"}})
    assert revised.status_code == 200
    body = revised.json()["item"]
    assert body["state"] == "IN_PRODUCTION" and body["version"] == 2 and body["approved_version"] == 1
    assert _move(pid, item["content_item_id"], "REVIEW").status_code == 200
    assert _move(pid, item["content_item_id"], "READY").status_code == 409


def test_calendar_plans_months_ahead_idempotently():
    pid = new_project()["project_id"]
    cal = client.post(f"/projects/{pid}/calendars", json={"name": "Editorial"}).json()["calendar"]
    body = {"horizon_days": 365, "start": "2026-01-05T00:00:00+00:00", "cadences": [
        {"channel": "linkedin", "kind": "social_post", "posts_per_week": 3, "weekdays": [0, 2, 4]},
        {"channel": "web", "kind": "article", "posts_per_week": 0.5, "weekdays": [1]},
    ]}
    first = client.post(f"/projects/{pid}/calendars/{cal['calendar_id']}/plan", json=body).json()
    # 365 days from Monday 2026-01-05 holds 53 Mondays (the last is 2027-01-04):
    # 53 + 52 + 52 posts, plus an article every other Tuesday.
    assert first["created_slots"] == 157 + 26
    again = client.post(f"/projects/{pid}/calendars/{cal['calendar_id']}/plan", json=body).json()
    assert again["created_slots"] == 0
    window = client.get(f"/projects/{pid}/calendar", params={"start": "2026-01-05T00:00:00+00:00", "end": "2026-01-19T00:00:00+00:00"}).json()["slots"]
    assert len(window) == 7


def test_forecast_reports_unknown_costs_instead_of_inventing_them():
    pid = new_project()["project_id"]
    result = client.post(f"/projects/{pid}/forecast", json={"horizon_days": 90, "cadences": [
        {"channel": "linkedin", "kind": "social_post", "posts_per_week": 3},
        {"channel": "web", "kind": "article", "posts_per_week": 1},
    ], "unit_costs": {"social_post": 0.5}}).json()
    assert result["estimated_cost_by_kind"]["article"] == "UNKNOWN"
    assert result["estimated_total_cost"] == "UNKNOWN"
    assert result["required_master_assets"] > 0 and result["items_by_kind"]["social_post"] > 0


def _scheduled(monkeypatch, pid: str, *, when: datetime) -> dict:
    item = _item(pid, _atom(pid)["atom_id"])
    _approve(monkeypatch, pid, item["content_item_id"])
    job = client.post(f"/projects/{pid}/content/items/{item['content_item_id']}/schedule", json={"scheduled_for": when.isoformat()})
    assert job.status_code == 201, job.text
    return {"item": item, "job": job.json()["job"]}


def test_scheduler_dry_run_goes_through_outbox_and_records_receipts(monkeypatch):
    pid = new_project()["project_id"]
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    sched = _scheduled(monkeypatch, pid, when=due)
    assert run_scheduler_tick(now=datetime.now(timezone.utc), worker_id="w1", project_id=pid)["processed"] == 0
    result = run_scheduler_tick(now=due + timedelta(seconds=1), worker_id="w1", project_id=pid)
    assert result["results"][0]["status"] == "DELIVERED"
    publications = client.get(f"/projects/{pid}/publications").json()
    attempt = publications["attempts"][0]
    assert attempt["mode"] == "DRY_RUN" and attempt["state"] == "VERIFIED"
    assert [r["kind"] for r in attempt["receipts"]] == ["dispatch_permit", "execution", "observation"]
    # A dry run proves the path but never claims the item was published.
    items = client.get(f"/projects/{pid}/content/items").json()["items"]
    assert next(i for i in items if i["content_item_id"] == sched["item"]["content_item_id"])["state"] == "SCHEDULED"


def test_concurrent_ticks_deliver_a_job_exactly_once(monkeypatch):
    pid = new_project()["project_id"]
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    _scheduled(monkeypatch, pid, when=past)
    outcomes: list[dict] = []

    def tick(worker: str) -> None:
        outcomes.append(run_scheduler_tick(now=datetime.now(timezone.utc), worker_id=worker, project_id=pid))

    threads = [threading.Thread(target=tick, args=(f"w{i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    statuses = [r["status"] for outcome in outcomes for r in outcome["results"]]
    assert statuses.count("DELIVERED") == 1
    assert len(client.get(f"/projects/{pid}/publications").json()["attempts"]) == 1


def test_publication_disabled_blocks_at_the_gate(monkeypatch):
    pid = new_project()["project_id"]
    _scheduled(monkeypatch, pid, when=datetime.now(timezone.utc) - timedelta(minutes=1))
    monkeypatch.setenv("AMC_PUBLICATION_MODE", "disabled")
    result = run_scheduler_tick(now=datetime.now(timezone.utc), worker_id="w", project_id=pid)["results"][0]
    assert result["status"] == "BLOCKED" and result["reasons"][0].startswith("PUBLICATION_UNAVAILABLE")
    assert client.get(f"/projects/{pid}/publications").json()["attempts"] == []


def test_expired_rights_block_media_release(monkeypatch):
    pid = new_project()["project_id"]
    atom = _atom(pid)
    item = _item(pid, atom["atom_id"], kind="reel", channel="instagram")
    artifact_id = item["artifact_id"]
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    client.post(f"/projects/{pid}/artifacts/{artifact_id}/rights", json={"license": "music-sync", "expires_at": past})
    _approve(monkeypatch, pid, item["content_item_id"])
    client.post(f"/projects/{pid}/content/items/{item['content_item_id']}/schedule", json={"scheduled_for": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    result = run_scheduler_tick(now=datetime.now(timezone.utc), worker_id="w", project_id=pid)["results"][0]
    assert result["status"] == "BLOCKED" and "RIGHTS_EXPIRED" in result["reasons"]


def test_revising_scheduled_content_cancels_the_stale_job(monkeypatch):
    pid = new_project()["project_id"]
    sched = _scheduled(monkeypatch, pid, when=datetime.now(timezone.utc) + timedelta(hours=2))
    item_id = sched["item"]["content_item_id"]
    client.post(f"/projects/{pid}/content/items/{item_id}/revise", json={"expected_version": 1, "body_patch": {"cta": "Buy"}})
    jobs = client.get(f"/projects/{pid}/calendar").json()["jobs"]
    assert jobs[0]["status"] == "CANCELLED" and jobs[0]["block_reasons"] == ["CONTENT_REVISED"]


class _FakeLive:
    """A reviewed-provider stand-in for exercising the LIVE path in tests."""

    name = "fake-live"
    mode = ProviderMode.LIVE

    def __init__(self, *, uncertain: bool = False, lands: bool = True):
        self.uncertain = uncertain
        self.lands = lands
        self.ledger: dict[str, ProviderResult] = {}
        self.publish_calls = 0

    def prepare(self, request):
        return publishing.DryRunProvider().prepare(request)

    def validate(self, prepared):
        return []

    def preview(self, prepared):
        return {}

    def publish(self, prepared, *, idempotency_key):
        self.publish_calls += 1
        if self.lands:
            self.ledger[idempotency_key] = ProviderResult(external_ref="live:1", observed={"request_hash": prepared["request_hash"]})
        if self.uncertain:
            raise ProviderUncertain("timeout")
        return self.ledger[idempotency_key]

    def verify(self, *, idempotency_key):
        return self.ledger.get(idempotency_key)

    def update(self, external_ref, prepared):
        raise NotImplementedError

    def remove(self, external_ref):
        return False


def _live(monkeypatch, provider: _FakeLive) -> None:
    monkeypatch.setenv("AMC_PUBLICATION_MODE", "live")
    monkeypatch.setitem(publishing._LIVE_PROVIDERS, "linkedin", provider)


def test_live_path_publishes_verifies_and_moves_lifecycle(monkeypatch):
    pid = new_project()["project_id"]
    sched = _scheduled(monkeypatch, pid, when=datetime.now(timezone.utc) - timedelta(minutes=1))
    provider = _FakeLive()
    _live(monkeypatch, provider)
    run_scheduler_tick(now=datetime.now(timezone.utc), worker_id="w", project_id=pid)
    item = next(i for i in client.get(f"/projects/{pid}/content/items").json()["items"] if i["content_item_id"] == sched["item"]["content_item_id"])
    assert item["state"] == "VERIFIED"
    events = [e["event_type"] for e in client.get(f"/projects/{pid}/events").json()["events"]]
    assert "PUBLISHED" in events and "VERIFIED" in events


def test_uncertain_publication_is_reconciled_by_readback_not_retry(monkeypatch):
    pid = new_project()["project_id"]
    _scheduled(monkeypatch, pid, when=datetime.now(timezone.utc) - timedelta(minutes=1))
    provider = _FakeLive(uncertain=True, lands=True)
    _live(monkeypatch, provider)
    run_scheduler_tick(now=datetime.now(timezone.utc), worker_id="w", project_id=pid)
    attempt = client.get(f"/projects/{pid}/publications").json()["attempts"][0]
    assert attempt["state"] == "VERIFIED" and provider.publish_calls == 1
    assert "RECOVERING" in [e["event_type"] for e in client.get(f"/projects/{pid}/events").json()["events"]]


def test_uncertain_publication_that_never_landed_fails_safely(monkeypatch):
    pid = new_project()["project_id"]
    sched = _scheduled(monkeypatch, pid, when=datetime.now(timezone.utc) - timedelta(minutes=1))
    provider = _FakeLive(uncertain=True, lands=False)
    _live(monkeypatch, provider)
    result = run_scheduler_tick(now=datetime.now(timezone.utc), worker_id="w", project_id=pid)["results"][0]
    assert result["status"] == "FAILED"
    attempt = client.get(f"/projects/{pid}/publications").json()["attempts"][0]
    assert attempt["state"] == "FAILED" and attempt["error"] == "READBACK_NOT_FOUND"
    item = next(i for i in client.get(f"/projects/{pid}/content/items").json()["items"] if i["content_item_id"] == sched["item"]["content_item_id"])
    assert item["state"] == "SCHEDULED"


def test_journeys_and_refresh_reuse_the_single_scheduler(monkeypatch):
    pid = new_project()["project_id"]
    item = _item(pid, _atom(pid)["atom_id"], kind="email", channel="email")
    _approve(monkeypatch, pid, item["content_item_id"])
    start = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    jobs = client.post(f"/projects/{pid}/journeys", json={"journey": "welcome", "start": start, "steps": [
        {"content_item_id": item["content_item_id"], "delay_days": 0},
        {"content_item_id": item["content_item_id"], "delay_days": 30},
    ]}).json()["jobs"]
    assert [j["job_kind"] for j in jobs] == ["LIFECYCLE", "LIFECYCLE"]
    results = run_scheduler_tick(now=datetime.now(timezone.utc), worker_id="w", project_id=pid)["results"]
    assert [r["status"] for r in results] == ["DELIVERED"]
    attempts = client.get(f"/projects/{pid}/publications").json()["attempts"]
    assert attempts[0]["mode"] == "DRY_RUN", "lifecycle messages are never sent for real"
