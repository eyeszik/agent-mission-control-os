from datetime import datetime, timezone
import pytest
from services.langgraph.quality.request_accut import (
    AccutPolicy, QualityContractError, RequestIntent, canonical_digest,
    compare_shadow, validate_accut,
)

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
POLICY = AccutPolicy(("id", "amount"), "id", 60, min_accuracy=0)

def row(id="a", amount=10, observed_at="2026-10-13T00:00:00Z"):
    return {"id": id, "amount": amount, "observed_at": observed_at}

def test_request_requires_every_dimension():
    data = dict(reason="report", entities=["orders"], questions=["how many"],
                units=["USD"], events=["paid"], scope="tenant", tradeoffs=["latency"])
    assert RequestIntent.from_mapping(data).envelope()["schema_version"] == "ace.request.v1"
    del data["scope"]
    with pytest.raises(QualityContractError): RequestIntent.from_mapping(data)

def test_accut_good_row():
    result = validate_accut([row()], POLICY, observed_at=NOW)
    assert result["decision"] == "ACCEPT"
    assert result["metrics"]["accuracy"] is None

def test_accuracy_unknown_blocks_default_policy():
    strict = AccutPolicy(("id",), "id", 60)
    assert validate_accut([row()], strict, observed_at=NOW)["decision"] == "BLOCK"

def test_duplicate_and_stale_are_quarantined():
    result = validate_accut([row(), row(observed_at="2026-10-01T00:00:00Z")], POLICY, observed_at=NOW)
    assert result["decision"] == "BLOCK"
    assert "uniqueness" in result["violations"]
    assert "timeliness" in result["violations"]
    assert len(result["quarantine"]) == 2

def test_bad_timestamp_cannot_be_accepted():
    assert validate_accut([row(observed_at="not-a-date")], POLICY, observed_at=NOW)["decision"] == "BLOCK"

def test_empty_data_blocks_publishing():
    assert validate_accut([], POLICY, observed_at=NOW)["decision"] == "BLOCK"

def test_untrusted_nan_rejected():
    with pytest.raises(QualityContractError): canonical_digest({"x": float("nan")})

def test_shadow_is_read_only_and_order_insensitive():
    result = compare_shadow({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert result["matches"] and not result["promotion_authorized"]
    assert not compare_shadow({"a": 1}, {"a": 2})["matches"]

def test_invalid_policy_rejected():
    with pytest.raises(QualityContractError): AccutPolicy(("id",), "id", -1)
