"""T15 — DecisionSpine: versioned material decisions with causal impact.

Accepted decision versions are immutable. A revision appends a new version
that ``supersedes`` the old hash and yields a :class:`DecisionDiff` naming the
causal descendants in the CWG that are now stale. The spine is append-only
in memory; durable decision rows remain the kernel's
``persistence/agency_kernel.py`` decisions — this is the planning view.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel

from .backchain import CausalWorkGraph, DecisionKind
from .hashing import semantic_hash

_FROZEN = {"frozen": True, "extra": "forbid"}


class DecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class DecisionNode(BaseModel):
    model_config = _FROZEN

    id: str
    kind: DecisionKind
    version: int = 1
    question: str
    alternatives: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    selected_option: str | None = None
    owner: str
    required_approver: str | None = None
    approved_by: str | None = None
    affected_nodes: tuple[str, ...] = ()
    status: DecisionStatus = DecisionStatus.PROPOSED
    confidence: float | None = None
    supersedes: str | None = None
    created_at: str | None = None

    @property
    def decision_hash(self) -> str:
        # created_at is provenance, not semantics.
        return semantic_hash(self, exclude={"created_at"})


class DecisionError(ValueError):
    pass


class DecisionDiff(BaseModel):
    model_config = _FROZEN

    kind: DecisionKind
    old_hash: str
    new_hash: str
    changed_fields: tuple[str, ...]
    stale_nodes: tuple[str, ...]


class DecisionSpine:
    def __init__(self, versions: Iterable[DecisionNode] = ()):
        self._versions: list[DecisionNode] = []
        self._superseded: set[str] = set()
        for v in versions:
            self._append(v)

    def _append(self, node: DecisionNode) -> DecisionNode:
        if node.supersedes:
            self._superseded.add(node.supersedes)
        self._versions.append(node)
        return node

    @property
    def versions(self) -> tuple[DecisionNode, ...]:
        return tuple(self._versions)

    def current(self, kind: DecisionKind) -> DecisionNode | None:
        live = [v for v in self._versions if v.kind is kind and v.decision_hash not in self._superseded]
        return live[-1] if live else None

    def effective_status(self, node: DecisionNode) -> DecisionStatus:
        return DecisionStatus.SUPERSEDED if node.decision_hash in self._superseded else node.status

    def propose(self, node: DecisionNode) -> DecisionNode:
        if node.status is not DecisionStatus.PROPOSED:
            raise DecisionError("new decisions enter the spine as PROPOSED")
        if self.current(node.kind) is not None:
            raise DecisionError(f"{node.kind.value} already has a live version; use revise()")
        return self._append(node)

    def accept(self, kind: DecisionKind, *, selected_option: str, approver_ref: str) -> DecisionNode:
        current = self.current(kind)
        if current is None:
            raise DecisionError(f"no live {kind.value} decision")
        if current.status is DecisionStatus.ACCEPTED:
            raise DecisionError("accepted decision versions are immutable; use revise()")
        if selected_option not in current.alternatives:
            raise DecisionError("selected option must be one of the declared alternatives")
        if not approver_ref or approver_ref == current.owner:
            raise DecisionError("acceptance needs an approver distinct from the decision owner")
        if current.required_approver and approver_ref != current.required_approver:
            raise DecisionError("approver does not match the required approver")
        accepted = current.model_copy(update={
            "status": DecisionStatus.ACCEPTED,
            "selected_option": selected_option,
            "approved_by": approver_ref,
            "version": current.version + 1,
            "supersedes": current.decision_hash,
        })
        return self._append(accepted)

    def revise(
        self,
        kind: DecisionKind,
        graph: CausalWorkGraph,
        **changes,
    ) -> tuple[DecisionNode, DecisionDiff]:
        """New version → supersedes → causal invalidation of CWG descendants."""
        current = self.current(kind)
        if current is None:
            raise DecisionError(f"no live {kind.value} decision")
        forbidden = set(changes) & {"id", "kind", "version", "supersedes", "status", "approved_by"}
        if forbidden:
            raise DecisionError(f"cannot set {sorted(forbidden)} on a revision")
        revised = current.model_copy(update={
            **changes,
            "version": current.version + 1,
            "supersedes": current.decision_hash,
            "status": DecisionStatus.PROPOSED,
            "approved_by": None,
        })
        changed = tuple(sorted(k for k in changes if getattr(current, k) != getattr(revised, k)))
        stale = tuple(sorted(graph.descendants([f"decision:{kind.value}"])))
        self._append(revised)
        return revised, DecisionDiff(
            kind=kind,
            old_hash=current.decision_hash,
            new_hash=revised.decision_hash,
            changed_fields=changed,
            stale_nodes=stale,
        )

    def accepted_by_kind(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for kind in DecisionKind:
            node = self.current(kind)
            if node is not None and node.status is DecisionStatus.ACCEPTED:
                out[kind.value] = node.decision_hash
        return out


def uncertainty_priority(graph: CausalWorkGraph) -> list[tuple[str, int]]:
    """Unresolved decisions ranked by downstream topology they could reshape."""
    pending = [n.id for n in graph.nodes.values() if n.id.startswith("decision:") and n.status.value == "AWAITING_HUMAN"]
    return sorted(((d, len(graph.descendants([d]))) for d in pending), key=lambda x: (-x[1], x[0]))
