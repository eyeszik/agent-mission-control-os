"""Contract tests for exact-SHA signed promotion and uncertainty budgets."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from services.langgraph.agency.ace_release import (
    EffectObservation, GateResult, ReleaseStage, SignedEvidenceBundle,
    UncertaintyPolicy, assess_uncertainty, evaluate_promotion,
    sign_evidence, verify_evidence, REQUIRED_GATES,
)

SHA = "a" * 40
SHA_OTHER = "b" * 40
DIGEST = "c" * 64
KEY = b"e" * 32
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def proof(*, approvals=True, gates=None, source_sha=SHA):
    values = tuple(GateResult(
        gate=name, status="PASS", source_commit=source_sha,
        evidence_ref=f"https://github.com/eyeszik/agent-mission-control-os/actions/runs/{index + 100}",
    ) for index, name in enumerate(sorted(REQUIRED_GATES))) if gates is None else gates
    return sign_evidence(SignedEvidenceBundle(
        commit_sha=SHA, policy_version="ace-policy-v100.1", contract_digest=DIGEST,
        target_stage=ReleaseStage.SHADOW, issued_at=NOW,
        expires_at=NOW + timedelta(minutes=30), gates=values,
        fault_injection_refs=("github:run/chaos-verified",),
        operation_receipt_digests=("f" * 64,),
        reviewer_identity="reviewer-1" if approvals else None,
        human_approval_ref="approval:123" if approvals else None,
        signing_key_id="key-1", signature="0" * 64,
    ), KEY)


def clear_snapshot():
    return assess_uncertainty(
        observations=(), now=NOW, policy=UncertaintyPolicy(),
        snapshot_complete=True,
    )


def decide(bundle, *, current_sha=SHA, **override):
    args = dict(bundle=bundle, keys={"key-1": KEY}, exact_head_sha=current_sha,
                current_policy_version="ace-policy-v100.1", current_contract_digest=DIGEST,
                stage=ReleaseStage.SHADOW, now=NOW + timedelta(minutes=1),
                uncertainty=clear_snapshot(), authorized_reviewers=frozenset({"reviewer-1"}),
                live_effects_enabled=False)
    args.update(override)
    return evaluate_promotion(**args)


def test_signed_exact_sha_policy_and_human_approval_allow_only_complete_shadow():
    item = proof()
    assert verify_evidence(item, {"key-1": KEY})
    approved = decide(item)
    assert approved.authorized and approved.reasons == ()
    assert len(approved.evidence_sha256) == 64


def test_tampering_or_missing_key_rejects_promotion():
    item = proof()
    tampered = item.model_copy(update={"policy_version": "changed"})
    assert not verify_evidence(tampered, {"key-1": KEY})
    assert "INVALID_EVIDENCE_SIGNATURE" in decide(tampered).reasons
    assert not decide(item, keys={}).authorized


def test_stale_head_or_mismatched_nested_ci_commit_rejected():
    item = proof()
    assert "SOURCE_COMMIT_MISMATCH" in decide(item, current_sha=SHA_OTHER).reasons
    stale = proof(source_sha=SHA_OTHER)
    assert "SOURCE_COMMIT_MISMATCH" in decide(stale).reasons


def test_failed_unverified_or_missing_gates_never_promote():
    failing = proof(gates=(GateResult(gate="backend_sqlite", status="FAIL",
                                      source_commit=SHA, evidence_ref="test"),))
    outcome = decide(failing)
    assert "FAILED_OR_UNVERIFIED_GATE" in outcome.reasons
    assert "MISSING_REQUIRED_GATES" in outcome.reasons
    unverified = proof(gates=tuple(
        GateResult(gate=g, status="UNVERIFIED" if g == "security_regression" else "PASS",
                   source_commit=SHA, evidence_ref="test") for g in sorted(REQUIRED_GATES)))
    assert not decide(unverified).authorized


def test_expiry_and_policy_schema_mismatch_are_fail_closed():
    item = proof()
    assert "EXPIRED_OR_FUTURE_EVIDENCE" in decide(item, now=NOW + timedelta(hours=1)).reasons
    assert "POLICY_VERSION_MISMATCH" in decide(item, current_policy_version="other").reasons
    assert "CONTRACT_DIGEST_MISMATCH" in decide(item, current_contract_digest="d" * 64).reasons
    assert "STAGE_MISMATCH" in decide(item, stage=ReleaseStage.CANARY).reasons


def test_missing_human_approval_live_effects_and_incomplete_scan_reject():
    missing = proof(approvals=False)
    assert "EXPLICIT_HUMAN_APPROVAL_MISSING" in decide(missing).reasons
    assert "LIVE_EFFECTS_ALREADY_ENABLED_BEFORE_APPROVAL" in decide(
        proof(), live_effects_enabled=True).reasons
    incomplete = assess_uncertainty(
        observations=(), now=NOW, policy=UncertaintyPolicy(), snapshot_complete=False)
    assert "UNCERTAINTY_BUDGET_BLOCKED" in decide(proof(), uncertainty=incomplete).reasons


def test_unconfirmed_critical_effect_suspends_dispatch():
    uncertain = EffectObservation(operation_key_digest="a" * 64, risk="R5",
                                  status="UNCONFIRMED", updated_at=NOW - timedelta(seconds=90))
    report = assess_uncertainty(observations=(uncertain,), now=NOW,
                                policy=UncertaintyPolicy(), snapshot_complete=True)
    assert not report.allow_high_risk_dispatch
    assert report.unconfirmed_total == 1
    assert report.unconfirmed_critical == 1
    assert report.oldest_seconds == 90
    assert "CRITICAL_UNCERTAINTY_EXCEEDED" in report.blockers
    assert "UNCERTAINTY_BUDGET_BLOCKED" in decide(proof(), uncertainty=report).reasons


def test_older_critical_effect_fails_age_even_under_count_budget():
    observations = (EffectObservation(operation_key_digest="a" * 64, risk="R3",
                                      status="RECONCILING", updated_at=NOW - timedelta(seconds=90)),)
    policy = UncertaintyPolicy(max_unconfirmed_total=2, max_unconfirmed_critical=2,
                               max_oldest_seconds=60)
    assessment = assess_uncertainty(observations=observations, now=NOW,
                                    policy=policy, snapshot_complete=True)
    assert "UNCERTAINTY_AGE_EXCEEDED" in assessment.blockers


def test_future_clock_and_incomplete_scope_fail_closed():
    observations = (EffectObservation(operation_key_digest="a" * 64, risk="R4",
                                      status="UNCONFIRMED", updated_at=NOW + timedelta(minutes=1)),)
    assessment = assess_uncertainty(observations=observations, now=NOW,
                                    policy=UncertaintyPolicy(max_unconfirmed_total=2,
                                                             max_unconfirmed_critical=2),
                                    snapshot_complete=False)
    assert "EFFECT_TIMESTAMP_IN_FUTURE" in assessment.blockers
    assert "UNCERTAINTY_SNAPSHOT_INCOMPLETE" in assessment.blockers


def test_strict_immutable_contract_rejects_extra_fields_and_duplicate_gate_names():
    with pytest.raises(ValidationError):
        GateResult(gate="foo", status="PASS", source_commit=SHA, evidence_ref="r",
                   unknown_authority=True)
    with pytest.raises(ValidationError, match="duplicate gate"):
        SignedEvidenceBundle(
            commit_sha=SHA, policy_version="v", contract_digest=DIGEST,
            target_stage=ReleaseStage.SHADOW, issued_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
            gates=(GateResult(gate="x", status="PASS", source_commit=SHA, evidence_ref="r"),
                   GateResult(gate="x", status="PASS", source_commit=SHA, evidence_ref="r")),
            fault_injection_refs=(), operation_receipt_digests=(),
            signing_key_id="k", signature="0" * 64,
        )


def test_unconfirmed_status_must_not_be_conflated_with_failed_result():
    value = EffectObservation(operation_key_digest="a" * 64, risk="R4",
                              status="FAILED", updated_at=NOW)
    assessment = assess_uncertainty(observations=(value,), now=NOW,
                                    policy=UncertaintyPolicy(), snapshot_complete=True)
    assert assessment.allow_high_risk_dispatch
    assert assessment.unconfirmed_total == 0
