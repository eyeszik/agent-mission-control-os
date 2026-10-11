"""VNEXUS creative multiverse: alternative directions as change sets over an approved genome version.

A branch never edits its base. It records a change set (values set, keys
unset, constraints added or removed) against an immutable base version, so
the branch document is always ``apply(base, changes)`` and two branches from
the same base can be compared and merged key by key.

Promotion is not a merge: it creates a new genome version from the branch
document and sends it through the normal approval route. Nothing here decides
that a direction is better; comparison reports what changed, what inherited
constraints are untouched, and which approved invariants a branch would break.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Sequence

from pydantic import Field, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

from .genome import (
    ConflictReason,
    ConstraintKind,
    GenomeConstraint,
    GenomeDocument,
    GenomeLayer,
    Value,
    VersionStatus,
    _Strict,
    diff_documents,
    document_from_flat,
    resolve,
)


class BranchState(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


BRANCH_TRANSITIONS: dict[str, dict[BranchState, BranchState]] = {
    "submit": {BranchState.OPEN: BranchState.IN_REVIEW},
    "withdraw": {BranchState.IN_REVIEW: BranchState.OPEN},
    "promote": {BranchState.IN_REVIEW: BranchState.PROMOTED},
    "reject": {BranchState.IN_REVIEW: BranchState.REJECTED},
    "archive": {BranchState.OPEN: BranchState.ARCHIVED},
}


class BranchTransitionError(ValueError):
    pass


def next_branch_state(current: BranchState, action: str) -> BranchState:
    target = BRANCH_TRANSITIONS.get(action, {}).get(BranchState(current))
    if target is None:
        raise BranchTransitionError(f"cannot {action} a branch in state {BranchState(current).value}")
    return target


class ChangeSet(_Strict):
    set: dict[str, Value] = Field(default_factory=dict)
    unset: tuple[str, ...] = ()
    add_constraints: tuple[GenomeConstraint, ...] = ()
    remove_constraints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _disjoint(self) -> "ChangeSet":
        if set(self.set) & set(self.unset):
            raise ValueError("a key cannot be both set and unset")
        if {c.constraint_id for c in self.add_constraints} & set(self.remove_constraints):
            raise ValueError("a constraint cannot be both added and removed")
        if len(self.set) + len(self.unset) > 400:
            raise ValueError("a change set touches at most 400 keys")
        return self

    @property
    def changes_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def apply_changes(base: GenomeDocument, changes: ChangeSet) -> GenomeDocument:
    values = {k: v for k, v in base.flatten().items() if k not in changes.unset}
    missing = sorted(set(changes.unset) - set(base.flatten()))
    if missing:
        raise ValueError(f"cannot unset keys the base does not have: {missing}")
    values.update(changes.set)
    known = {c.constraint_id for c in base.constraints}
    absent = sorted(set(changes.remove_constraints) - known)
    if absent:
        raise ValueError(f"cannot remove constraints the base does not have: {absent}")
    clash = sorted({c.constraint_id for c in changes.add_constraints} & (known - set(changes.remove_constraints)))
    if clash:
        raise ValueError(f"constraints already exist in the base: {clash}")
    constraints = [c for c in base.constraints if c.constraint_id not in changes.remove_constraints] + list(changes.add_constraints)
    return document_from_flat(values, constraints=constraints, provenance=base.provenance)


def compose(parent: ChangeSet, child: ChangeSet) -> ChangeSet:
    """A sub-branch's effective change set relative to the shared base: parent first, then child."""
    values = {**{k: v for k, v in parent.set.items() if k not in child.unset}, **child.set}
    unset = tuple(sorted((set(parent.unset) - set(child.set)) | set(child.unset)))
    adds = {c.constraint_id: c for c in parent.add_constraints if c.constraint_id not in child.remove_constraints}
    adds.update({c.constraint_id: c for c in child.add_constraints})
    removes = tuple(sorted((set(parent.remove_constraints) - set(adds)) | (set(child.remove_constraints) - {c.constraint_id for c in parent.add_constraints})))
    return ChangeSet(set=values, unset=tuple(k for k in unset if k not in values), add_constraints=tuple(adds.values()),
                     remove_constraints=removes)


def compare_with_base(base: GenomeDocument, changes: ChangeSet, ancestors: Sequence[GenomeLayer], *, scope_ref: str,
                      scope: str) -> dict[str, Any]:
    """What a branch changes relative to its base, and which approved invariants it would break."""
    branch_doc = apply_changes(base, changes)
    diff = diff_documents(base, branch_doc)
    preview = list(ancestors) + [GenomeLayer(scope=scope, scope_ref=scope_ref, status=VersionStatus.DRAFT, document=branch_doc)]
    resolution = resolve(preview, preview_ref=scope_ref)
    violations = [{"kind": c.reason.value, "key": c.key, "constraint_id": c.constraint_id, "detail": c.detail}
                  for c in resolution.conflicts if c.scope_ref == scope_ref and c.reason is not ConflictReason.UNAPPROVED_OVERRIDE]
    base_immutable = {c.constraint_id: c for c in base.constraints if c.kind is ConstraintKind.IMMUTABLE}
    for cid in sorted(set(changes.remove_constraints) & set(base_immutable)):
        violations.append({"kind": "INVARIANT_REMOVED", "key": base_immutable[cid].key, "constraint_id": cid,
                           "detail": "removes an approved immutable constraint"})
    for c in base_immutable.values():
        if c.key in changes.set and base.flatten().get(c.key) != changes.set[c.key]:
            violations.append({"kind": "INVARIANT_CHANGED", "key": c.key, "constraint_id": c.constraint_id,
                               "detail": "changes a value the approved version declares immutable"})
        if c.key in changes.unset:
            violations.append({"kind": "INVARIANT_CHANGED", "key": c.key, "constraint_id": c.constraint_id,
                               "detail": "unsets a value the approved version declares immutable"})
    inherited = [c.constraint_id for c in resolution.constraints if resolution.constraint_owner.get(c.constraint_id) != scope_ref]
    failed = [f.model_dump(mode="json") for f in resolution.findings if not f.passed]
    return {"branch_document_hash": branch_doc.content_hash, "base_document_hash": base.content_hash,
            "values": {"added": [c.model_dump(mode="json") for c in diff.added], "removed": [c.model_dump(mode="json") for c in diff.removed],
                       "modified": [c.model_dump(mode="json") for c in diff.modified], "unchanged": list(diff.unchanged)},
            "constraints": {"added": list(diff.constraints_added), "removed": list(diff.constraints_removed),
                            "modified": list(diff.constraints_modified),
                            "unchanged_own": sorted({c.constraint_id for c in base.constraints} - set(diff.constraints_removed)
                                                    - set(diff.constraints_modified)),
                            "unchanged_inherited": sorted(inherited)},
            "invariant_violations": violations, "failed_findings": failed, "resolution_hash": resolution.resolution_hash,
            "promotable": not violations and not any(f["severity"] == "BLOCKING" for f in failed)}


def compare_branches(a: ChangeSet, b: ChangeSet) -> dict[str, Any]:
    """Two branches from the same base: which keys they agree on, which only one touches, and where they conflict."""
    def effect(cs: ChangeSet) -> dict[str, Any]:
        out: dict[str, Any] = {k: ("SET", v) for k, v in cs.set.items()}
        out.update({k: ("UNSET", None) for k in cs.unset})
        return out

    ea, eb = effect(a), effect(b)
    keys = sorted(set(ea) | set(eb))
    only_a = [k for k in keys if k in ea and k not in eb]
    only_b = [k for k in keys if k in eb and k not in ea]
    same = [k for k in keys if k in ea and k in eb and ea[k] == eb[k]]
    conflicts = [{"key": k, "a": list(ea[k]), "b": list(eb[k])} for k in keys if k in ea and k in eb and ea[k] != eb[k]]
    ca = {c.constraint_id: c for c in a.add_constraints}
    cb = {c.constraint_id: c for c in b.add_constraints}
    constraint_conflicts = sorted(k for k in set(ca) & set(cb) if ca[k] != cb[k])
    constraint_conflicts += sorted((set(a.remove_constraints) & set(cb)) | (set(b.remove_constraints) & set(ca)))
    return {"only_a": only_a, "only_b": only_b, "agree": same, "conflicts": conflicts, "constraint_conflicts": constraint_conflicts,
            "mergeable": not conflicts and not constraint_conflicts}


def merge_change_sets(a: ChangeSet, b: ChangeSet) -> tuple[Optional[ChangeSet], dict[str, Any]]:
    """Deterministic merge. Returns (None, report) when any key or constraint conflicts; never picks a side."""
    report = compare_branches(a, b)
    if not report["mergeable"]:
        return None, report
    adds = {c.constraint_id: c for c in (*a.add_constraints, *b.add_constraints)}
    merged = ChangeSet(set={**a.set, **b.set}, unset=tuple(sorted(set(a.unset) | set(b.unset))),
                       add_constraints=tuple(adds[k] for k in sorted(adds)),
                       remove_constraints=tuple(sorted(set(a.remove_constraints) | set(b.remove_constraints))))
    return merged, report


def rebase(old_base: GenomeDocument, new_base: GenomeDocument, changes: ChangeSet) -> tuple[Optional[ChangeSet], dict[str, Any]]:
    """Carry a change set onto a newer approved base. Keys the base changed and the branch also touched conflict."""
    base_diff = diff_documents(old_base, new_base)
    base_touched = {c.key for c in (*base_diff.added, *base_diff.removed, *base_diff.modified)}
    branch_touched = set(changes.set) | set(changes.unset)
    conflicts = sorted(base_touched & branch_touched)
    constraint_touched = set(base_diff.constraints_added) | set(base_diff.constraints_removed) | set(base_diff.constraints_modified)
    constraint_conflicts = sorted(constraint_touched & ({c.constraint_id for c in changes.add_constraints} | set(changes.remove_constraints)))
    report = {"base_changed_keys": sorted(base_touched), "conflicts": conflicts, "constraint_conflicts": constraint_conflicts}
    if conflicts or constraint_conflicts:
        return None, report
    try:
        apply_changes(new_base, changes)
    except ValueError as exc:
        report["conflicts"] = [str(exc)]
        return None, report
    return changes, report


__all__ = ["BRANCH_TRANSITIONS", "BranchState", "BranchTransitionError", "ChangeSet", "apply_changes", "compare_branches",
           "compare_with_base", "compose", "merge_change_sets", "next_branch_state", "rebase"]
