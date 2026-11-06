"""ACE v100 fail-closed evidence-driven promotion and effect uncertainty budget.

This module decides, never deploys, retries or authorizes external operations.
Release evidence must be signed by a key held outside the repository; passing a
repository-local test is not production attestation. Caller must supply an
independently checked GitHub commit SHA and an authoritative scoped intent scan.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from enum import Enum
from typing import Literal, Mapping

from pydantic import Field, model_validator

from services.langgraph.agency.ace_controls import StrictModel


class ReleaseStage(str, Enum):
    SHADOW = "shadow"
    INTERNAL_SANDBOX = "internal_sandbox"
    CANARY = "canary"
    LIMITED_PRODUCTION = "limited_production"
    FULL_PRODUCTION = "full_production"


class GateResult(StrictModel):
    gate: str = Field(min_length=1, max_length=100)
    status: Literal["PASS", "FAIL", "UNVERIFIED"]
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    evidence_ref: str = Field(min_length=1, max_length=2048)


class EffectObservation(StrictModel):
    operation_key_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    risk: Literal["R0", "R1", "R2", "R3", "R4", "R5"]
    status: Literal[
        "INTENT", "DISPATCHING", "UNCONFIRMED", "RECONCILING",
        "COMMITTED", "FAILED", "COMPENSATION_REQUIRED", "ABANDONED",
    ]
    updated_at: datetime

    @model_validator(mode="after")
    def aware_clock(self) -> "EffectObservation":
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("effect updated_at must be timezone-aware")
        return self


class UncertaintyPolicy(StrictModel):
    max_unconfirmed_total: int = Field(default=0, ge=0)
    max_unconfirmed_critical: int = Field(default=0, ge=0)
    max_oldest_seconds: int = Field(default=0, ge=0)
    critical_risk: frozenset[Literal["R3", "R4", "R5"]] = frozenset({"R3", "R4", "R5"})


class UncertaintyAssessment(StrictModel):
    allow_high_risk_dispatch: bool
    unconfirmed_total: int
    unconfirmed_critical: int
    oldest_seconds: int
    blockers: tuple[str, ...]


def assess_uncertainty(*, observations: tuple[EffectObservation, ...],
                       now: datetime, policy: UncertaintyPolicy,
                       snapshot_complete: bool) -> UncertaintyAssessment:
    """Fail closed when cross-worker durable intent scanning is incomplete.

    Provider non-response is never interpreted as FAILED or COMMITTED.
    The caller must supply a complete, authoritative tenant/project snapshot.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    unresolved = tuple(x for x in observations if x.status in {
        "UNCONFIRMED", "RECONCILING", "COMPENSATION_REQUIRED"
    })
    count = len(unresolved)
    critical = sum(x.risk in policy.critical_risk for x in unresolved)
    future = any(x.updated_at > now for x in unresolved)
    oldest = max((max(0, int((now - x.updated_at).total_seconds()))
                  for x in unresolved), default=0)
    blockers = []
    if not snapshot_complete:
        blockers.append("UNCERTAINTY_SNAPSHOT_INCOMPLETE")
    if future:
        blockers.append("EFFECT_TIMESTAMP_IN_FUTURE")
    if count > policy.max_unconfirmed_total:
        blockers.append("UNCERTAINTY_COUNT_EXCEEDED")
    if critical > policy.max_unconfirmed_critical:
        blockers.append("CRITICAL_UNCERTAINTY_EXCEEDED")
    if oldest > policy.max_oldest_seconds:
        blockers.append("UNCERTAINTY_AGE_EXCEEDED")
    return UncertaintyAssessment(
        allow_high_risk_dispatch=not blockers, unconfirmed_total=count,
        unconfirmed_critical=critical, oldest_seconds=oldest,
        blockers=tuple(blockers),
    )


class SignedEvidenceBundle(StrictModel):
    schema_version: Literal["ace.release-evidence.v1"] = "ace.release-evidence.v1"
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    policy_version: str = Field(min_length=1)
    contract_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_stage: ReleaseStage
    issued_at: datetime
    expires_at: datetime
    gates: tuple[GateResult, ...]
    fault_injection_refs: tuple[str, ...]
    operation_receipt_digests: tuple[str, ...]
    reviewer_identity: str | None = None
    human_approval_ref: str | None = None
    signing_key_id: str = Field(min_length=1)
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def clock_and_unique(self) -> "SignedEvidenceBundle":
        for instant in (self.issued_at, self.expires_at):
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError("evidence timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("evidence expiry must follow issuance")
        names = [g.gate for g in self.gates]
        if len(names) != len(set(names)):
            raise ValueError("duplicate gate results")
        if any(len(item) != 64 or any(c not in "0123456789abcdef" for c in item)
               for item in self.operation_receipt_digests):
            raise ValueError("invalid operation receipt digest")
        return self


def _canonical(bundle: SignedEvidenceBundle) -> bytes:
    payload = bundle.model_dump(mode="json", exclude={"signature"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def sign_evidence(bundle: SignedEvidenceBundle, signing_key: bytes) -> SignedEvidenceBundle:
    """Sign with an externally protected >=256-bit key, never repository secrets."""
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError("protected signing key must contain at least 32 bytes")
    signature = hmac.new(signing_key, _canonical(bundle), hashlib.sha256).hexdigest()
    return bundle.model_copy(update={"signature": signature})


def verify_evidence(bundle: SignedEvidenceBundle, keys: Mapping[str, bytes]) -> bool:
    key = keys.get(bundle.signing_key_id)
    if not isinstance(key, bytes) or len(key) < 32:
        return False
    expected = hmac.new(key, _canonical(bundle), hashlib.sha256).hexdigest()
    return hmac.compare_digest(bundle.signature, expected)


class PromotionDecision(StrictModel):
    authorized: bool
    stage: ReleaseStage
    commit_sha: str
    reasons: tuple[str, ...]
    evidence_sha256: str


REQUIRED_GATES = frozenset({
    "dependency_consistency", "backend_sqlite", "backend_postgresql",
    "schema_parity", "frontend_build", "browser_e2e", "dependency_audit",
    "fault_injection", "security_regression", "evidence_integrity",
})


def evaluate_promotion(*, bundle: SignedEvidenceBundle, keys: Mapping[str, bytes],
                       exact_head_sha: str, current_policy_version: str,
                       current_contract_digest: str, stage: ReleaseStage,
                       now: datetime, uncertainty: UncertaintyAssessment,
                       required_gates: frozenset[str] = REQUIRED_GATES,
                       authorized_reviewers: frozenset[str] = frozenset(),
                       live_effects_enabled: bool = False) -> PromotionDecision:
    """No deploy action; exact-commit evidence and explicit authorization gate.

    The invoking release environment must independently establish head SHA,
    reviewer identity and signing-key custody. This checks supplied proofs,
    never trusting a PR comment or job status from another commit.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    problems = []
    if not verify_evidence(bundle, keys):
        problems.append("INVALID_EVIDENCE_SIGNATURE")
    if bundle.commit_sha != exact_head_sha or any(
        g.source_commit != exact_head_sha for g in bundle.gates
    ):
        problems.append("SOURCE_COMMIT_MISMATCH")
    if stage != bundle.target_stage:
        problems.append("STAGE_MISMATCH")
    if bundle.policy_version != current_policy_version:
        problems.append("POLICY_VERSION_MISMATCH")
    if bundle.contract_digest != current_contract_digest:
        problems.append("CONTRACT_DIGEST_MISMATCH")
    if not bundle.issued_at <= now < bundle.expires_at:
        problems.append("EXPIRED_OR_FUTURE_EVIDENCE")
    gates = {g.gate: g for g in bundle.gates}
    if required_gates - gates.keys():
        problems.append("MISSING_REQUIRED_GATES")
    if any(g.status != "PASS" for g in gates.values()):
        problems.append("FAILED_OR_UNVERIFIED_GATE")
    if not bundle.fault_injection_refs:
        problems.append("MISSING_FAULT_EVIDENCE")
    if not bundle.operation_receipt_digests:
        problems.append("MISSING_OPERATION_RECEIPTS")
    if (not bundle.reviewer_identity
            or bundle.reviewer_identity not in authorized_reviewers
            or not bundle.human_approval_ref):
        problems.append("EXPLICIT_HUMAN_APPROVAL_MISSING")
    if live_effects_enabled:
        problems.append("LIVE_EFFECTS_ALREADY_ENABLED_BEFORE_APPROVAL")
    if not uncertainty.allow_high_risk_dispatch:
        problems.append("UNCERTAINTY_BUDGET_BLOCKED")
    return PromotionDecision(
        authorized=not problems, stage=stage, commit_sha=exact_head_sha,
        reasons=tuple(problems),
        evidence_sha256=hashlib.sha256(_canonical(bundle)).hexdigest(),
    )
