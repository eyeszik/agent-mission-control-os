"""Scoped memory with an explicit authority order.

    BRAND_CANON > APPROVED_PROJECT_DECISION > VERIFIED_EVIDENCE
                > WORKING_CONTEXT > LEARNING_SIGNAL

Rules enforced here (pure, so persistence and tests share them):

* a scope may only hold the authority classes listed in
  ``MEMORY_SCOPE_AUTHORITIES`` (a conversation can never mint brand canon);
* a write with *lower* authority than the active record for the same subject
  is quarantined, never silently applied;
* resolution returns the highest-authority fresh record and reports every
  shadowed or stale alternative, so nothing is hidden;
* promotion to a higher authority is an explicit, attributed act.

Memory is scoped knowledge, not hidden global state: M0 is tenant-wide
generalized know-how; M1–M5 belong to one project; M3 additionally to one
thread; M6 holds quarantined learning signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from .models import MemoryRecord
from .vocabulary import MEMORY_SCOPE_AUTHORITIES, PRIVATE_MEMORY_SCOPES, authority_rank


class MemoryPolicyError(ValueError):
    pass


def validate_placement(*, scope: str, authority: str, project_id: Optional[str], thread_id: Optional[str]) -> None:
    allowed = MEMORY_SCOPE_AUTHORITIES.get(scope)
    if allowed is None:
        raise MemoryPolicyError(f"unknown memory scope {scope!r}")
    if authority not in allowed:
        raise MemoryPolicyError(f"scope {scope} cannot hold {authority} memory (allowed: {', '.join(allowed)})")
    if scope == "M0_AGENCY" and project_id is not None:
        raise MemoryPolicyError("M0_AGENCY memory is tenant-wide and must not name a project")
    if scope != "M0_AGENCY" and scope != "M6_LEARNING" and project_id is None:
        raise MemoryPolicyError(f"{scope} memory must belong to a project")
    if scope == "M3_CONVERSATION" and not thread_id:
        raise MemoryPolicyError("M3_CONVERSATION memory must name its thread")


def _fresh(record: MemoryRecord, now: datetime) -> bool:
    if not record.fresh_until:
        return True
    moment = datetime.fromisoformat(record.fresh_until)
    return moment >= now


@dataclass(frozen=True)
class WriteDecision:
    status: str  # ACTIVE or QUARANTINED
    supersedes: Optional[str]
    reason: Optional[str]


def decide_write(*, authority: str, content_hash: str, active: Iterable[MemoryRecord]) -> WriteDecision:
    """How a new record for a subject relates to the active records for it."""
    ranked = sorted(active, key=lambda record: authority_rank(record.authority.value), reverse=True)
    if not ranked:
        return WriteDecision("ACTIVE", None, None)
    top = ranked[0]
    if top.content_hash == content_hash and top.authority.value == authority:
        return WriteDecision("DUPLICATE", top.memory_id, "identical content already active")
    if authority_rank(authority) < authority_rank(top.authority.value):
        return WriteDecision(
            "QUARANTINED",
            None,
            f"{authority} cannot override active {top.authority.value} memory {top.memory_id}",
        )
    same_or_lower = [record for record in ranked if authority_rank(record.authority.value) <= authority_rank(authority)]
    return WriteDecision("ACTIVE", same_or_lower[0].memory_id if same_or_lower else None, None)


def resolve(records: Iterable[MemoryRecord], *, now: datetime) -> dict[str, object]:
    candidates = [record for record in records if record.status.value == "ACTIVE"]
    fresh = [record for record in candidates if _fresh(record, now)]
    stale = [record.memory_id for record in candidates if not _fresh(record, now)]
    # Authority first; at equal authority, project-scoped memory beats tenant-wide
    # agency memory (M0 only fills gaps); then the newest record.
    fresh.sort(key=lambda record: (authority_rank(record.authority.value), record.project_id is not None, record.created_at), reverse=True)
    winner = fresh[0] if fresh else None
    shadowed = [record.memory_id for record in fresh[1:] if winner and record.content_hash != winner.content_hash]
    return {
        "winner": winner,
        "authority": winner.authority.value if winner else None,
        "shadowed": shadowed,
        "stale": stale,
        "resolved": winner is not None,
    }


def can_promote(*, scope: str, from_authority: str, to_authority: str) -> None:
    if to_authority not in MEMORY_SCOPE_AUTHORITIES.get(scope, ()):
        raise MemoryPolicyError(f"{scope} memory cannot be promoted to {to_authority}")
    if authority_rank(to_authority) <= authority_rank(from_authority):
        raise MemoryPolicyError("promotion must raise authority")


def portfolio_visible(scope: str) -> bool:
    """Only generalized agency memory crosses project/brand boundaries."""
    return scope not in PRIVATE_MEMORY_SCOPES and scope != "M6_LEARNING"
