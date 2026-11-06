"""Idempotency persistence: key derivation and the reservation lifecycle.

The reservation API is ``reserve_idempotency`` -> ``complete_idempotency`` /
``fail_idempotency``; a second reservation of the same key reports
``replay`` (completed), ``in_progress`` (still executing) or ``conflict``
(same key, different request).
"""

from datetime import timedelta
from uuid import uuid4

from services.langgraph.persistence import idempotency
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    fail_idempotency,
    generate_idempotency_key,
    get_idempotency_record,
    reserve_idempotency,
)


def _scope() -> str:
    return f"test-idempotency-{uuid4().hex}"


def test_generate_idempotency_key_deterministic():
    k1 = generate_idempotency_key("proj-1", "node-a", {"x": 1}, attempt=1)
    k2 = generate_idempotency_key("proj-1", "node-a", {"x": 1}, attempt=1)
    assert k1 == k2


def test_generate_idempotency_key_sensitive_to_all_inputs():
    base = generate_idempotency_key("proj-1", "node-a", {"x": 1}, attempt=1)
    variants = [
        generate_idempotency_key("proj-2", "node-a", {"x": 1}, attempt=1),
        generate_idempotency_key("proj-1", "node-b", {"x": 1}, attempt=1),
        generate_idempotency_key("proj-1", "node-a", {"x": 2}, attempt=1),
        generate_idempotency_key("proj-1", "node-a", {"x": 1}, attempt=2),
    ]
    assert len({base, *variants}) == 5


def test_generate_idempotency_key_input_order_invariant():
    assert generate_idempotency_key("p", "n", {"a": 1, "b": 2}) == generate_idempotency_key("p", "n", {"b": 2, "a": 1})


def test_reserve_complete_then_replay_roundtrip():
    scope, key = _scope(), generate_idempotency_key("proj-1", "node-a", {"unique": uuid4().hex})
    assert reserve_idempotency(scope, key, "hash-1")["state"] == "new"
    assert reserve_idempotency(scope, key, "hash-1")["state"] == "in_progress"
    assert complete_idempotency(scope, key, {"status": "done"}) is True
    replay = reserve_idempotency(scope, key, "hash-1")
    assert replay["state"] == "replay" and replay["record"]["result"] == {"status": "done"}


def test_same_key_with_a_different_request_conflicts():
    scope, key = _scope(), uuid4().hex
    reserve_idempotency(scope, key, "hash-1")
    assert reserve_idempotency(scope, key, "hash-2")["state"] == "conflict"


def test_failed_reservation_can_be_retried():
    scope, key = _scope(), uuid4().hex
    reserve_idempotency(scope, key, "hash-1")
    assert fail_idempotency(scope, key, "boom") is True
    retry = reserve_idempotency(scope, key, "hash-1")
    assert retry["state"] == "new" and retry["record"]["attempt_count"] == 2


def test_ttl_is_enforced_and_an_expired_record_is_replaced(monkeypatch):
    scope, key = _scope(), uuid4().hex
    reserve_idempotency(scope, key, "hash-1", ttl_seconds=1)
    complete_idempotency(scope, key, {"status": "done"})
    later = idempotency._utcnow() + timedelta(seconds=5)
    monkeypatch.setattr(idempotency, "_utcnow", lambda: later)
    fresh = reserve_idempotency(scope, key, "hash-1", ttl_seconds=1)
    assert fresh["state"] == "new"
    assert get_idempotency_record(scope, key)["status"] == "executing"
