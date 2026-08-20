from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from services.langgraph.persistence.approvals import create_approval_request, get_approval, resolve_approval
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    hash_payload,
    reserve_idempotency,
)


def test_atomic_idempotency_reservation_allows_one_executor():
    scope = f"tenant:user:test:{uuid4()}"
    key = str(uuid4())
    request_hash = hash_payload({"value": 1})

    def reserve():
        return reserve_idempotency(scope, key, request_hash)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reserve(), range(2)))

    states = sorted(result["state"] for result in results)
    assert states == ["in_progress", "new"]


def test_completed_idempotency_returns_canonical_replay():
    scope = f"tenant:user:test:{uuid4()}"
    key = str(uuid4())
    request_hash = hash_payload({"value": 2})
    first = reserve_idempotency(scope, key, request_hash)
    assert first["state"] == "new"
    assert complete_idempotency(scope, key, {"answer": 42}) is True

    replay = reserve_idempotency(scope, key, request_hash)
    assert replay["state"] == "replay"
    assert replay["record"]["result"] == {"answer": 42}


def test_idempotency_key_reuse_with_different_input_is_conflict():
    scope = f"tenant:user:test:{uuid4()}"
    key = str(uuid4())
    first_hash = hash_payload({"value": "a"})
    second_hash = hash_payload({"value": "b"})
    assert reserve_idempotency(scope, key, first_hash)["state"] == "new"
    assert reserve_idempotency(scope, key, second_hash)["state"] == "conflict"


def test_concurrent_approval_decisions_produce_one_immutable_winner():
    approval = create_approval_request(
        f"run-{uuid4()}",
        "tenant-events-test",
        "proj-security",
        "review",
        0.5,
    )

    def decide(decision: str):
        return resolve_approval(approval["approval_id"], f"reviewer-{decision}", decision)

    with ThreadPoolExecutor(max_workers=2) as executor:
        approve_future = executor.submit(decide, "approve")
        reject_future = executor.submit(decide, "reject")
        results = [approve_future.result(), reject_future.result()]

    assert sum(result is not None for result in results) == 1
    persisted = get_approval(approval["approval_id"])
    assert persisted["decision"] in {"approve", "reject"}
    assert persisted["status"] == "resolved"
