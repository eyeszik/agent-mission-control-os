"""T23 — LearningQuarantine: append-only, hash-chained, non-authoritative.

Learning signals may tune *heuristics* (routing rank, context requirements,
validator selection, estimates, templates). They can never change
permissions, N1 ownership, N2 lifecycle, N3 authority, approval requirements,
security/privacy/legal policy, provider permissions, secrets or governance
thresholds. A signal aimed at any of those is converted into a
:class:`GovernanceProposal` that goes through normal human review — the
ledger has no code path that applies it.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel

from .hashing import semantic_hash

_FROZEN = {"frozen": True, "extra": "forbid"}
GENESIS = "0" * 64

ALLOWED_HEURISTICS = frozenset({
    "routing_ranking",
    "context_requirements",
    "dependency_templates",
    "validator_selection",
    "estimation_hints",
    "tool_reliability_recommendations",
    "validated_reusable_templates",
})
PROTECTED_TARGETS = frozenset({
    "permissions",
    "n1_ownership",
    "n2_lifecycle",
    "n3_authority",
    "approval_requirements",
    "security_policy",
    "privacy_policy",
    "legal_policy",
    "provider_permissions",
    "secrets",
    "governance_thresholds",
})


class SignalStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    GOVERNANCE_PROPOSAL = "GOVERNANCE_PROPOSAL"
    REJECTED = "REJECTED"


class LearningSignal(BaseModel):
    model_config = _FROZEN

    id: str
    tenant_scope: str
    run_refs: tuple[str, ...]
    observation: str
    evidence_refs: tuple[str, ...]
    target_heuristic: str
    confidence: float | None = None
    status: SignalStatus = SignalStatus.QUARANTINED
    created_at: str | None = None
    prev_hash: str = GENESIS
    hash: str = ""


class GovernanceProposal(BaseModel):
    model_config = _FROZEN

    signal_id: str
    target: str
    rationale: str
    requires: str = "human governance review and approval"


class LearningLedgerError(ValueError):
    pass


class LearningLedger:
    """Append-only per-tenant ledger. There is deliberately no update/delete/apply."""

    def __init__(self) -> None:
        self._entries: list[LearningSignal] = []
        self.proposals: list[GovernanceProposal] = []

    def append(self, signal: LearningSignal) -> LearningSignal:
        if not signal.tenant_scope:
            raise LearningLedgerError("tenant_scope is required")
        if any(e.id == signal.id for e in self._entries):
            raise LearningLedgerError(f"duplicate signal id {signal.id}")
        status = SignalStatus.QUARANTINED
        if signal.target_heuristic in PROTECTED_TARGETS:
            status = SignalStatus.GOVERNANCE_PROPOSAL
            self.proposals.append(GovernanceProposal(
                signal_id=signal.id, target=signal.target_heuristic, rationale=signal.observation))
        elif signal.target_heuristic not in ALLOWED_HEURISTICS:
            status = SignalStatus.REJECTED
        if not signal.evidence_refs and status is SignalStatus.QUARANTINED:
            status = SignalStatus.REJECTED
        prev = self._entries[-1].hash if self._entries else GENESIS
        staged = signal.model_copy(update={"status": status, "prev_hash": prev, "hash": ""})
        sealed = staged.model_copy(update={"hash": semantic_hash(staged, exclude={"hash"})})
        self._entries.append(sealed)
        return sealed

    def entries(self, tenant_scope: str) -> tuple[LearningSignal, ...]:
        """Tenant-isolated read: no cross-tenant leakage."""
        return tuple(e for e in self._entries if e.tenant_scope == tenant_scope)

    def verify_chain(self) -> bool:
        prev = GENESIS
        for entry in self._entries:
            if entry.prev_hash != prev or entry.hash != semantic_hash(entry, exclude={"hash"}):
                return False
            prev = entry.hash
        return True

    @classmethod
    def replay(cls, entries: Iterable[LearningSignal]) -> "LearningLedger":
        ledger = cls()
        ledger._entries = list(entries)
        if not ledger.verify_chain():
            raise LearningLedgerError("STATE_CORRUPTION: learning ledger hash chain broken")
        return ledger
