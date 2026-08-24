from services.langgraph.persistence.idempotency import generate_idempotency_key, verify_idempotency, record_idempotency

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

def test_record_and_verify_roundtrip():
    key = generate_idempotency_key("proj-1", "node-a", {"unique": "test-marker-1"})
    assert verify_idempotency(key) is False
    record_idempotency(key, {"status": "done"})
    assert verify_idempotency(key) is True

def test_record_idempotency_ttl_param_is_currently_a_no_op():
    # KNOWN LIMITATION: ttlSeconds is accepted but never enforced.
    # This test documents actual behavior, not intended behavior.
    key = generate_idempotency_key("proj-1", "node-a", {"unique": "ttl-marker"}, attempt=99)
    record_idempotency(key, {"status": "done"}, ttlSeconds=1)
    assert verify_idempotency(key) is True
