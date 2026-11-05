"""STATE_VERIFICATION_CONTRACT: valid handoffs, tampering, rollback, placeholders, schema."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.state_contract import (
    Payload,
    PayloadChain,
    PayloadIntegrityError,
    PayloadSequenceError,
    PlaceholderError,
    content_digest,
    find_placeholders,
    make_payload,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _p(agent: str, counter: int, content: dict, **kw) -> Payload:
    return make_payload(agent=agent, counter=counter, content=content, schema_ref="amc.test.v1",
                        now=NOW, **kw)


def _chain_with(*contents: dict, agent: str = "analyzer") -> PayloadChain:
    chain = PayloadChain()
    for i, content in enumerate(contents):
        chain.accept(_p(agent, i, content))
    return chain


# --- valid verification -------------------------------------------------------------

def test_valid_chain_accepts_in_order_and_advances_head():
    chain = PayloadChain()
    chain.accept(_p("analyzer", 0, {"spec": "a"}))
    chain.accept(_p("analyzer", 1, {"spec": "b"}))
    assert chain.head is not None and chain.head.payload_id == "payload_analyzer_1"
    assert [p.counter for p in chain.accepted] == [0, 1]
    assert chain.quarantine == ()


def test_content_hash_is_the_canonical_digest_of_content_and_key_order_independent():
    a = _p("synth", 0, {"x": 1, "y": ["p", "q"]})
    b = _p("synth", 0, {"y": ["p", "q"], "x": 1})
    assert a.content_hash == canonical_hash({"x": 1, "y": ["p", "q"]}) == content_digest({"x": 1, "y": ["p", "q"]})
    assert a.content_hash == b.content_hash


def test_timestamp_is_utc_iso8601_and_hash_is_lowercase_hex():
    p = _p("synth", 0, {"x": 1})
    assert p.timestamp_utc == "2026-11-04T12:00:00Z"
    assert len(p.content_hash) == 64 and p.content_hash == p.content_hash.lower()


# --- tampered payloads --------------------------------------------------------------

def test_tampered_content_raises_integrity_error_and_rolls_back_to_prior_head():
    chain = _chain_with({"step": "one"}, {"step": "two"})
    forged = _p("analyzer", 2, {"step": "three"})
    forged.content["step"] = "THREE-TAMPERED"  # content changed after its hash was declared
    with pytest.raises(PayloadIntegrityError) as info:
        chain.accept(forged)
    assert info.value.rolled_back_to == "payload_analyzer_1"
    assert chain.head is not None and chain.head.payload_id == "payload_analyzer_1"
    assert len(chain.accepted) == 2
    assert chain.quarantine[-1].reason == "HASH_MISMATCH"


def test_forged_hash_with_mismatched_content_is_rejected():
    chain = _chain_with({"a": 1})
    good = _p("analyzer", 1, {"a": 2})
    forged = good.model_copy(update={"content_hash": content_digest({"a": 1})})
    with pytest.raises(PayloadIntegrityError):
        chain.accept(forged)
    assert chain.head is not None and chain.head.counter == 0


def test_in_place_edit_of_an_accepted_head_is_detected_and_rolled_back():
    chain = _chain_with({"spec": "one"}, {"spec": "two"})
    assert chain.head is not None and chain.head.counter == 1
    chain.head.content["spec"] = "edited-after-acceptance"  # memory corruption or tampering
    with pytest.raises(PayloadIntegrityError) as info:
        chain.verify_head()
    assert info.value.rolled_back_to == "payload_analyzer_0"
    assert chain.head is not None and chain.head.payload_id == "payload_analyzer_0"
    assert chain.quarantine[-1].reason == "HEAD_CORRUPTED"
    assert chain.verify_head() is chain.head  # the rolled-back head verifies cleanly


def test_rollback_then_recompute_produces_a_verified_next_payload():
    chain = _chain_with({"step": "one"})

    def producer(head):
        assert head is not None and head.payload_id == "payload_analyzer_0"
        return _p("analyzer", head.counter + 1, {"step": "recomputed-from-head"})

    bad = _p("analyzer", 1, {"step": "bad"})
    bad.content["step"] = "corrupted"
    with pytest.raises(PayloadIntegrityError):
        chain.accept(bad)
    fixed = chain.recompute(producer)
    assert fixed.payload_id == "payload_analyzer_1"
    assert chain.head is fixed


# --- sequencing / replay ------------------------------------------------------------

def test_replayed_counter_is_rejected_without_changing_state():
    chain = _chain_with({"s": 0}, {"s": 1})
    with pytest.raises(PayloadSequenceError):
        chain.accept(_p("analyzer", 1, {"s": 1}))  # replay of an accepted counter
    with pytest.raises(PayloadSequenceError):
        chain.accept(_p("analyzer", 5, {"s": 5}))  # skipped counters
    assert chain.head is not None and chain.head.counter == 1


# --- zero placeholders --------------------------------------------------------------

@pytest.mark.parametrize("content", [
    {"copy": "TODO: write the hero line"},
    {"copy": "Lorem ipsum dolor sit amet"},
    {"nested": {"items": ["ok", "TBD"]}},
    {"slot": "[INSERT CLIENT NAME]"},
    {"slot": "{{client_name}}"},
    {"stub": "raise NotImplementedError"},
])
def test_placeholder_content_is_refused_and_quarantined(content):
    chain = PayloadChain()
    with pytest.raises(PlaceholderError):
        chain.accept(_p("writer", 0, content))
    assert chain.head is None
    assert chain.quarantine[-1].reason == "PLACEHOLDER_CONTENT"


def test_placeholder_detection_reports_locations_and_ignores_ordinary_prose():
    locations = find_placeholders({"a": "fine", "b": ["ok", "FIXME"], "c": {"d": "TBD"}})
    assert locations == ["content.b[1]", "content.c.d"]
    assert find_placeholders({"a": "The todo list is in the placeholder store."}) == []


# --- schema -------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("payload_id", "payload_Analyzer_0"),
    ("payload_id", "payload_analyzer_x"),
    ("payload_id", "../../payload_analyzer_0"),
    ("timestamp_utc", "2026-11-04T12:00:00"),          # naive: no offset
    ("timestamp_utc", "2026-11-04T12:00:00+02:00"),    # not UTC
    ("timestamp_utc", "yesterday"),
    ("content_hash", "ABC"),
    ("content_hash", "g" * 64),
    ("content", {}),
])
def test_invalid_payload_fields_are_rejected_by_the_schema(field, value):
    base = _p("analyzer", 0, {"x": 1}).model_dump()
    base[field] = value
    with pytest.raises(ValidationError):
        Payload.model_validate(base)


def test_unknown_fields_are_rejected():
    base = _p("analyzer", 0, {"x": 1}).model_dump()
    base["shell"] = "rm -rf /"
    with pytest.raises(ValidationError):
        Payload.model_validate(base)


def test_mutations_and_access_log_are_carried_but_outside_the_digest():
    a = _p("analyzer", 0, {"x": 1}, mutations=[{"op": "rename"}], access_log=[{"actor": "u1"}])
    b = _p("analyzer", 0, {"x": 1})
    assert a.content_hash == b.content_hash  # documented scope: digest covers content only
