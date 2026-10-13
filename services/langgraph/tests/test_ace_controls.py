"""ACE v100 opt-in contract, capability and provenance invariants."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from services.langgraph.agency.ace_controls import (
    Mission, Task, Capability, EvidenceItem, canonical_hash, effect_operation_key,
    topological_order, route_capability, confidence_gate, seal_record, verify_chain,
)


def test_strict_schema_blocks_unknown_fields_and_implicit_cast():
    data = dict(mission_id="m", tenant_id="t", project_id="p",
                goal="g", policy_version="v1")
    mission = Mission.model_validate(data)
    assert Mission.model_validate_json(mission.model_dump_json()) == mission
    with pytest.raises(ValidationError):
        Mission.model_validate({**data, "untrusted_authority": True})
    with pytest.raises(ValidationError):
        Mission.model_validate({**data, "goal": 19})


def test_timestamp_roundtrip_and_naive_date_rejected():
    task = Task(task_id="t", mission_id="m", capability="search",
                deadline=datetime.now(timezone.utc))
    assert Task.model_validate_json(task.model_dump_json()) == task
    with pytest.raises(ValidationError):
        Task(task_id="t", mission_id="m", capability="search",
             deadline=datetime(2020, 1, 1))


def test_topological_sort_cycle_unknown_and_duplicate_fail_closed():
    a = Task(task_id="a", mission_id="m", capability="x")
    b = Task(task_id="b", mission_id="m", capability="x", dependencies=("a",))
    assert topological_order((b, a)) == ("a", "b")
    with pytest.raises(ValueError):
        topological_order((a, a))
    with pytest.raises(ValueError):
        topological_order((Task(task_id="c", mission_id="m", capability="x",
                                dependencies=("missing",)),))
    with pytest.raises(ValueError):
        topological_order((b, Task(task_id="a", mission_id="m", capability="x",
                                   dependencies=("b",))))


def test_canonical_intent_is_retry_stable_and_tenant_scoped():
    params = dict(tenant_id="tenant-a", project_id="project", operation="send")
    x = effect_operation_key(**params, payload={"a": 1, "b": 2})
    assert x == effect_operation_key(**params, payload={"b": 2, "a": 1})
    assert x != effect_operation_key(**{**params, "tenant_id": "tenant-b"},
                                     payload={"a": 1, "b": 2})
    with pytest.raises(ValueError):
        canonical_hash({"bad": float("nan")})


def test_capability_router_enforces_scope_and_complexity():
    a = Capability(provider_id="a", model_id="one",
                   capabilities=frozenset({"json"}), complexity_ceiling=3,
                   priority=2, rate_limit_per_minute=10,
                   cost_per_million_tokens=1)
    b = a.model_copy(update={"provider_id": "b", "priority": 1,
                             "complexity_ceiling": 5})
    route = route_capability(required="json", complexity=2, providers=(a, b),
                             allowed_providers=frozenset({"a", "b"}))
    assert tuple(p.provider_id for p in route) == ("b", "a")
    assert route_capability(required="vision", complexity=2,
                            providers=(a, b),
                            allowed_providers=frozenset({"a", "b"})) == ()
    assert tuple(p.provider_id for p in route_capability(
        required="json", complexity=5, providers=(a, b),
        allowed_providers=frozenset({"b"}))) == ("b",)


def test_confidence_firewall_quarantines_missing_conflicting_or_low_evidence():
    args = dict(mandatory_claim_ids=frozenset({"critical"}), quality=1)
    assert confidence_gate(evidence=(), **args) == "QUARANTINE"
    item = EvidenceItem(claim_id="critical", source_ref="source",
                        observed_at=datetime.now(timezone.utc),
                        status="VERIFIED", metadata_digest="0" * 64)
    assert confidence_gate(evidence=(item,), **args) == "ACCEPT"
    assert confidence_gate(evidence=(item,), mandatory_claim_ids=frozenset({"critical"}),
                           quality=0.5) == "QUARANTINE"
    assert confidence_gate(evidence=(item, item.model_copy(update={"status": "VOID"})),
                           **args) == "QUARANTINE"


def test_authenticated_hash_chain_fails_for_tampering_or_wrong_key():
    key = b"test-only-key"
    first = seal_record(sequence=1, previous_hash="0" * 64,
                        payload={"step": 1}, signing_key=key)
    second = seal_record(sequence=2, previous_hash=first.record_hash,
                         payload={"step": 2}, signing_key=key)
    assert verify_chain((first, second), ({"step": 1}, {"step": 2}), key)
    assert not verify_chain((first, second), ({"step": 1}, {"step": 3}), key)
    assert not verify_chain((first, second), ({"step": 1}, {"step": 2}), b"wrong")
    assert not verify_chain((second, first), ({"step": 2}, {"step": 1}), key)
