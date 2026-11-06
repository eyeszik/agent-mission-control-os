"""T18/T19 — causal invalidation (BlastRadiusCertificate), ArtifactDNA and DeltaApproval.

These are the planning-side projections of machinery that already exists in
persistence: ``persistence/invalidation.py`` records durable invalidation
obligations and ``persistence/approvals.py`` binds approvals to
``subject_hash``/``policy_version``. Nothing here writes to either; the
certificate and scope evaluation tell a caller *which* obligations and
approvals those stores should record as stale, using exact hashes rather than
phase-wide invalidation.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping

from pydantic import BaseModel

from .backchain import CausalWorkGraph, NodeType
from .context import ContextCapsule
from .hashing import closure_hash, semantic_hash

_FROZEN = {"frozen": True, "extra": "forbid"}


def dependency_closure_hash(graph: CausalWorkGraph, subject_refs: Iterable[str], artifact_hashes: Mapping[str, str]) -> str:
    """Hash of everything the approved subjects causally rest on.

    Uses the current artifact content hash where known and the node's
    structural hash otherwise, so either an upstream content change or an
    upstream structural change moves the closure.
    """
    closure: set[str] = set()
    for ref in subject_refs:
        closure |= graph.ancestors(ref)
    return closure_hash(
        (ref, artifact_hashes.get(ref, graph.nodes[ref].semantic_hash)) for ref in sorted(closure) if ref in graph.nodes
    )


class ApprovalScope(BaseModel):
    model_config = _FROZEN

    approval_id: str
    subject_refs: tuple[str, ...]
    subject_hashes: tuple[tuple[str, str], ...]
    dependency_closure_hash: str
    preview_hash: str | None = None
    policy_version: str
    reviewer_class: str
    authenticated_reviewer_ref: str | None
    decision: str | None
    timestamp: str | None = None

    @property
    def scope_hash(self) -> str:
        return semantic_hash(self, exclude={"timestamp"})


def build_scope(
    graph: CausalWorkGraph,
    *,
    approval_id: str,
    subjects: Mapping[str, str],
    artifact_hashes: Mapping[str, str],
    policy_version: str,
    reviewer_ref: str | None,
    decision: str | None,
    reviewer_class: str = "authenticated_human",
    preview_hash: str | None = None,
    timestamp: str | None = None,
) -> ApprovalScope:
    return ApprovalScope(
        approval_id=approval_id,
        subject_refs=tuple(sorted(subjects)),
        subject_hashes=tuple(sorted(subjects.items())),
        dependency_closure_hash=dependency_closure_hash(graph, subjects, artifact_hashes),
        preview_hash=preview_hash,
        policy_version=policy_version,
        reviewer_class=reviewer_class,
        authenticated_reviewer_ref=reviewer_ref,
        decision=decision,
        timestamp=timestamp,
    )


def scope_from_approval_record(record: Mapping[str, object], *, dependency_closure_hash: str) -> ApprovalScope:
    """Adapt a ``persistence/approvals.py`` row. The reviewer is whatever the
    server bound from the authenticated principal — never client-supplied."""
    subject_ref = str(record.get("subject_ref") or record.get("run_id"))
    subject_hash = str(record.get("subject_hash") or "")
    return ApprovalScope(
        approval_id=str(record["approval_id"]),
        subject_refs=(subject_ref,),
        subject_hashes=((subject_ref, subject_hash),),
        dependency_closure_hash=dependency_closure_hash,
        policy_version=str(record.get("policy_version") or "amc-approval/v1"),
        reviewer_class="authenticated_human",
        authenticated_reviewer_ref=record.get("reviewer") or None,  # type: ignore[arg-type]
        decision=record.get("decision") or None,  # type: ignore[arg-type]
        timestamp=record.get("decided_at") or None,  # type: ignore[arg-type]
    )


class ApprovalValidity(str, Enum):
    VALID = "VALID"
    STALE_APPROVAL = "STALE_APPROVAL"
    FULL_GATE_REPLAY = "FULL_GATE_REPLAY"
    NOT_APPROVED = "NOT_APPROVED"
    UNAUTHENTICATED_REVIEWER = "UNAUTHENTICATED_REVIEWER"


def evaluate_scope(
    scope: ApprovalScope,
    *,
    current_subject_hashes: Mapping[str, str],
    current_closure_hash: str,
    current_policy_version: str,
    preservation_permitted: bool = True,
    high_risk_change: bool = False,
) -> ApprovalValidity:
    """An approval stays valid only if the exact protected state is unchanged."""
    if not scope.authenticated_reviewer_ref:
        return ApprovalValidity.UNAUTHENTICATED_REVIEWER
    if scope.decision != "approve":
        return ApprovalValidity.NOT_APPROVED
    unchanged = (
        all(current_subject_hashes.get(ref) == digest for ref, digest in scope.subject_hashes)
        and current_closure_hash == scope.dependency_closure_hash
        and current_policy_version == scope.policy_version
    )
    if unchanged and preservation_permitted:
        return ApprovalValidity.VALID
    if high_risk_change:
        return ApprovalValidity.FULL_GATE_REPLAY
    return ApprovalValidity.STALE_APPROVAL


class BlastRadiusCertificate(BaseModel):
    model_config = _FROZEN

    changed_refs: tuple[str, ...]
    old_hashes: tuple[str, ...]
    new_hashes: tuple[str, ...]
    causal_descendants: tuple[str, ...]
    preserved_refs: tuple[str, ...]
    stale_context_capsules: tuple[str, ...]
    stale_validation_refs: tuple[str, ...]
    stale_approvals: tuple[str, ...]
    preserved_approvals: tuple[str, ...]
    mandatory_full_replay_reasons: tuple[str, ...]
    certificate_hash: str


_HIGH_RISK_PREFIXES = ("external:", "decision:legal_security_policy", "decision:release_go_no_go")


def compute_blast_radius(
    graph: CausalWorkGraph,
    changes: Mapping[str, tuple[str, str]],
    *,
    approvals: Iterable[ApprovalScope] = (),
    capsules: Mapping[str, ContextCapsule] | None = None,
) -> BlastRadiusCertificate:
    """new version → delta → descendant closure → invalidate affected → preserve the rest."""
    changed = sorted(ref for ref, (old, new) in changes.items() if old != new and ref in graph.nodes)
    changed_set = set(changed)
    descendants = graph.descendants(changed) - changed_set
    affected = changed_set | descendants
    preserved = sorted(set(graph.nodes) - affected)

    stale_capsules = sorted(
        node_id for node_id, capsule in (capsules or {}).items()
        if node_id in affected or any(ref in changed_set for ref, _ in capsule.dependency_hashes)
    )
    stale_validations = sorted(n for n in affected if graph.nodes[n].type is NodeType.VALIDATION_OBLIGATION)
    stale_approvals: list[str] = []
    preserved_approvals: list[str] = []
    for scope in approvals:
        closure = set(scope.subject_refs)
        for ref in scope.subject_refs:
            closure |= graph.ancestors(ref)
        (stale_approvals if closure & affected else preserved_approvals).append(scope.approval_id)

    replay: set[str] = set()
    for ref in affected:
        if ref.startswith(_HIGH_RISK_PREFIXES):
            replay.add(f"HIGH_RISK_NODE_AFFECTED:{ref}")
        node = graph.nodes[ref]
        if any(o in {"PROFILE:SECURITY", "PROFILE:PRIVACY", "PROFILE:TRADEMARK"} for o in node.validation_obligations):
            replay.add(f"REGULATED_VALIDATION_AFFECTED:{ref}")

    body = {
        "changed_refs": tuple(changed),
        "old_hashes": tuple(changes[r][0] for r in changed),
        "new_hashes": tuple(changes[r][1] for r in changed),
        "causal_descendants": tuple(sorted(descendants)),
        "preserved_refs": tuple(preserved),
        "stale_context_capsules": tuple(stale_capsules),
        "stale_validation_refs": tuple(stale_validations),
        "stale_approvals": tuple(sorted(stale_approvals)),
        "preserved_approvals": tuple(sorted(preserved_approvals)),
        "mandatory_full_replay_reasons": tuple(sorted(replay)),
    }
    return BlastRadiusCertificate(**body, certificate_hash=semantic_hash(body))


def artifact_dna(
    graph: CausalWorkGraph,
    node_id: str,
    *,
    evidence_refs: Mapping[str, Iterable[str]] | None = None,
    approvals: Iterable[ApprovalScope] = (),
) -> dict[str, list[str]]:
    """Trace an artifact back to its evidence, decisions, inputs and approvals."""
    ancestry = graph.ancestors(node_id) | {node_id}
    evidence = sorted(
        {ref for anc in ancestry if graph.nodes[anc].artifact_type
         for ref in (evidence_refs or {}).get(graph.nodes[anc].artifact_type or "", ())}
    )
    return {
        "artifact": [node_id],
        "evidence_requirements": sorted(a for a in ancestry if graph.nodes[a].type is NodeType.EVIDENCE_REQUIREMENT),
        "evidence_refs": evidence,
        "decisions": sorted(a for a in ancestry if graph.nodes[a].type is NodeType.MATERIAL_DECISION),
        "existing_inputs": sorted(a for a in ancestry if graph.nodes[a].type is NodeType.EXISTING_REF),
        "producing_work": sorted(a for a in ancestry if graph.nodes[a].type is NodeType.EXECUTABLE_WORK),
        "approvals": sorted(s.approval_id for s in approvals if set(s.subject_refs) & ancestry),
    }
