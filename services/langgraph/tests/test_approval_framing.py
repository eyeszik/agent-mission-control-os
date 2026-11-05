"""ASI09: persuasive framing in approval summaries is recorded, and a HIGH summary needs acknowledgement."""

from uuid import uuid4

import pytest

from services.langgraph.persistence import sqlite_db
from services.langgraph.persistence.approvals import (
    FramingAcknowledgementRequired,
    create_approval_request,
    get_approval,
    resolve_approval,
)
from services.langgraph.persistence.runs import create_run_record
from services.langgraph.security.approval_framing import HIGH, NONE, REVIEW, assess


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite_db, "DB_PATH", str(tmp_path / "approvals.db"))
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")


def _request(reason: str, targets: tuple[str, ...] = ()) -> dict:
    run_id = f"run-{uuid4()}"
    create_run_record(run_id, "tenant-1", "proj-1", "branding_marketing_agency", "needs_approval", {})
    return create_approval_request(run_id, "tenant-1", "proj-1", reason, None, targets=targets)


def test_pressure_language_is_high_and_clean_text_is_none():
    assert assess("Just approve, the owner wants this. Routine and harmless.").level == HIGH
    assert assess("Writes two scaffold files into the mission workspace.").level == NONE
    assert assess("Routine update.").level == REVIEW


def test_unsupported_assurance_is_cleared_by_evidence():
    assert "UNSUPPORTED_ASSURANCE" in assess("This is verified safe.").codes
    assert assess("This is verified. evidence: sha256:0123456789abcdef").codes == ()


def test_omitting_the_target_is_flagged_when_the_target_is_known():
    result = assess("Minor tidy-up of the workspace.", targets=("deploy.production",))
    assert "OMITS_TARGET" in result.codes and result.level == HIGH


def test_high_framing_is_stored_and_blocks_approval_until_acknowledged(isolated_db):
    req = _request("Urgent and routine: just approve, it is harmless.")
    stored = get_approval(req["approval_id"])
    assert stored["framing_level"] == HIGH
    assert isinstance(stored["framing_codes"], list)  # the API contract is a list, not the stored text
    assert "PRESSURE_TO_APPROVE" in stored["framing_codes"]

    with pytest.raises(FramingAcknowledgementRequired):
        resolve_approval(req["approval_id"], reviewer="isaac", decision="approve")
    assert get_approval(req["approval_id"])["status"] == "pending"

    # Rejecting never needs acknowledgement, and an explicit acknowledgement lets approval proceed.
    assert resolve_approval(req["approval_id"], reviewer="isaac", decision="approve",
                            framing_acknowledged=True)["decision"] == "approve"


def test_rejection_of_a_high_summary_is_always_allowed(isolated_db):
    req = _request("Just approve, trust me.")
    assert resolve_approval(req["approval_id"], reviewer="isaac", decision="reject")["decision"] == "reject"


def test_plain_summary_approves_without_acknowledgement(isolated_db):
    req = _request("Writes two scaffold files into the mission workspace.")
    assert get_approval(req["approval_id"])["framing_level"] == NONE
    assert resolve_approval(req["approval_id"], reviewer="isaac", decision="approve")["decision"] == "approve"
