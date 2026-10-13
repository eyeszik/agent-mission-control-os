"""Real SQLite/PostgreSQL-backed signed governance decisions and tamper detection."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.langgraph.persistence.ace_provenance import (
    append_provenance, read_project_provenance, verify_project_provenance,
)
from services.langgraph.persistence.database import json_param, table, transaction
from services.langgraph.persistence.tenancy import ProjectOwnershipError
from services.langgraph.quality.request_accut import (
    AccutPolicy, compare_shadow_and_record, validate_and_record_accut,
)

KEY1 = b"a" * 32
KEY2 = b"b" * 32


def _scope():
    suffix = uuid4().hex
    return f"ace-tenant-{suffix}", f"ace-project-{suffix}"


def test_ace_signed_quality_and_shadow_decisions_append_to_same_chain():
    tenant, project = _scope()
    now = datetime.now(timezone.utc)
    policy = AccutPolicy(("id", "amount"), "id", 60, min_accuracy=0)
    good = validate_and_record_accut(
        [{"id": "one", "amount": 5, "observed_at": now.isoformat()}], policy,
        observed_at=now, tenant_id=tenant, project_id=project, actor="system:quality",
        signing_key=KEY1, key_id="key-1",
    )
    assert good["decision"] == "ACCEPT"
    shadow = compare_shadow_and_record(
        {"rows": 1}, {"rows": 2},
        observed_at=now, tenant_id=tenant, project_id=project, actor="system:shadow",
        signing_key=KEY2, key_id="key-2",
    )
    assert shadow["matches"] is False
    assert shadow["promotion_authorized"] is False
    records = read_project_provenance(tenant_id=tenant, project_id=project)
    assert len(records) == 2
    assert records[0]["event_type"] == "ACE_ACCUT_DECISION"
    assert records[1]["event_type"] == "ACE_SHADOW_COMPARISON"
    assert records[1]["previous_hash"] == records[0]["record_hash"]
    assert verify_project_provenance(
        tenant_id=tenant, project_id=project, keys={"key-1": KEY1, "key-2": KEY2}
    )
    assert not verify_project_provenance(
        tenant_id=tenant, project_id=project, keys={"key-1": KEY1}
    )


def test_ace_quarantined_payload_gets_authenticated_record_without_source_values():
    tenant, project = _scope()
    now = datetime.now(timezone.utc)
    policy = AccutPolicy(("id", "amount"), "id", 60, min_accuracy=0)
    event = validate_and_record_accut(
        [{"id": "x", "amount": None, "observed_at": "bad timestamp"}],
        policy, observed_at=now, tenant_id=tenant, project_id=project,
        actor="system:quality", signing_key=KEY1, key_id="k",
    )
    assert event["decision"] == "BLOCK"
    stored = read_project_provenance(tenant_id=tenant, project_id=project)
    assert stored[0]["payload"]["decision"] == "BLOCK"
    assert "bad timestamp" not in str(stored)
    assert verify_project_provenance(tenant_id=tenant, project_id=project, keys={"k": KEY1})


def test_ace_provenance_payload_is_redacted_and_tamper_detected():
    tenant, project = _scope()
    now = datetime.now(timezone.utc)
    append_provenance(
        tenant_id=tenant, project_id=project, actor="system:auditor",
        event_type="TEST", payload={"authorization": "Bearer verylongsecrettokenvalue"},
        signing_key=KEY1, key_id="k", now=now,
    )
    event = read_project_provenance(tenant_id=tenant, project_id=project)[0]
    assert event["payload"]["authorization"] == "[REDACTED_SENSITIVE_FIELD]"
    assert verify_project_provenance(tenant_id=tenant, project_id=project, keys={"k": KEY1})
    with transaction(write=True) as db:
        db.execute(
            f"UPDATE {table('ace_provenance')} SET payload = ? WHERE tenant_id = ? AND project_id = ?",
            (json_param({"authorization": "modified"}), tenant, project),
        )
    assert not verify_project_provenance(tenant_id=tenant, project_id=project, keys={"k": KEY1})


def test_ace_provenance_tenant_boundaries_and_empty_chain_are_fail_closed():
    tenant, project = _scope()
    assert not verify_project_provenance(tenant_id=tenant, project_id=project, keys={"k": KEY1})
    append_provenance(
        tenant_id=tenant, project_id=project, actor="system:test",
        event_type="TEST", payload={"x": 1}, signing_key=KEY1,
        key_id="k", now=datetime.now(timezone.utc),
    )
    with pytest.raises(ProjectOwnershipError):
        append_provenance(
            tenant_id=tenant + "-other", project_id=project,
            actor="system:intruder", event_type="TEST", payload={"x": 2},
            signing_key=KEY1, key_id="k", now=datetime.now(timezone.utc),
        )
    assert read_project_provenance(tenant_id=tenant + "-other", project_id=project) == ()


def test_ace_audit_must_have_protected_sufficient_key():
    tenant, project = _scope()
    with pytest.raises(ValueError, match="256-bit"):
        append_provenance(
            tenant_id=tenant, project_id=project, actor="system:test",
            event_type="TEST", payload={"decision": "ACCEPT"},
            signing_key=b"unsafe", key_id="test", now=datetime.now(timezone.utc),
        )
    assert read_project_provenance(tenant_id=tenant, project_id=project) == ()
