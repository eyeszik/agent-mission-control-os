"""VNEXUS knowledge graph and creative multiverse services.

Authorization: a brand's graph and branches are governed by the brand's owner
project for brand-scope work and by the scope's project otherwise. Graph
writes are serialized per brand and checked (edge typing, lineage cycles)
inside the same transaction that writes them.

Branch promotion is never automatic: it creates a genome version from the
branch and submits it to the existing approval route; the branch becomes
PROMOTED only when that version is settled APPROVED.
"""

from __future__ import annotations

from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import vnexus as db
from services.langgraph.persistence.database import transaction
from services.langgraph.security.auth import Principal

from . import service
from .genome import GenomeDocument, Scope, VersionStatus
from .graph import Edge, EdgeKind, Graph, GraphError, Node, NodeKind, diff_snapshots, node_hash
from .multiverse import (
    BranchState,
    ChangeSet,
    apply_changes,
    compare_branches,
    compare_with_base,
    compose,
    merge_change_sets,
    next_branch_state,
    rebase,
)

MAX_ATTRIBUTE_BYTES = 16_384


# --------------------------------------------------------------------------- graph


def _graph(brand_id: str, *, as_of: Optional[str] = None, conn: Any = None) -> Graph:
    nodes, edges = db.load_graph(conn, brand_id) if conn is not None else db.list_graph(brand_id)
    return Graph([Node(**n) for n in nodes], [Edge(**e) for e in edges], as_of=as_of)


def _brand_access(principal: Principal, brand_id: str, *, write: bool = False) -> dict:
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, brand["owner_project_id"], write=write)
    return brand


def _attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    import json

    if len(json.dumps(attributes, sort_keys=True, default=str)) > MAX_ATTRIBUTE_BYTES:
        raise ValueError(f"node attributes exceed {MAX_ATTRIBUTE_BYTES} bytes")
    return attributes


def add_node(principal: Principal, brand_id: str, *, kind: NodeKind, label: str, attributes: dict[str, Any],
             actor: Optional[str] = None) -> dict:
    _brand_access(principal, brand_id, write=True)
    attrs = _attributes(attributes)
    return db.insert_node(tenant_id=principal.tenant_id, brand_id=brand_id, kind=kind.value, label=label, attributes=attrs,
                          content_hash=node_hash(kind, label, attrs), actor=actor or principal.user_id)


def add_edge(principal: Principal, brand_id: str, *, kind: EdgeKind, src: str, dst: str, provenance: dict[str, Any]) -> dict:
    _brand_access(principal, brand_id, write=True)
    with transaction(write=True) as conn:
        graph = _graph_locked(conn, brand_id)
        graph.check_edge(kind, src, dst)
        return db.insert_edge(tenant_id=principal.tenant_id, brand_id=brand_id, kind=kind.value, src=src, dst=dst,
                              provenance=_attributes(provenance), actor=principal.user_id, db=conn)


def _graph_locked(conn: Any, brand_id: str) -> Graph:
    nodes, edges = db.load_graph(conn, brand_id, lock=True)
    return Graph([Node(**n) for n in nodes], [Edge(**e) for e in edges])


def supersede_node(principal: Principal, node_id: str, *, label: str, attributes: dict[str, Any]) -> dict:
    """Replace a decision without deleting it: close the old node, add the new one, link SUPERSEDES."""
    old = db.get_node(node_id)
    if old is None or old["tenant_id"] != principal.tenant_id:
        raise db.VnexusNotFound(f"node {node_id} not found")
    _brand_access(principal, old["brand_id"], write=True)
    kind = NodeKind(old["kind"])
    attrs = _attributes(attributes)
    with transaction(write=True) as conn:
        graph = _graph_locked(conn, old["brand_id"])
        if node_id not in graph.nodes:
            raise db.VnexusConflict(f"node {node_id} was already superseded or retired")
        new = db.insert_node(tenant_id=old["tenant_id"], brand_id=old["brand_id"], kind=kind.value, label=label, attributes=attrs,
                             content_hash=node_hash(kind, label, attrs), actor=principal.user_id, db=conn)
        db.insert_edge(tenant_id=old["tenant_id"], brand_id=old["brand_id"], kind=EdgeKind.SUPERSEDES.value, src=new["node_id"],
                       dst=node_id, provenance={"reason": "superseded"}, actor=principal.user_id, db=conn)
        db.close_node(conn, node_id=node_id, superseded_by=new["node_id"], actor=principal.user_id)
    return new


def retire_edge(principal: Principal, brand_id: str, edge_id: str) -> None:
    _brand_access(principal, brand_id, write=True)
    _, edges = db.list_graph(brand_id)
    if not any(e["edge_id"] == edge_id for e in edges):
        raise db.VnexusNotFound(f"edge {edge_id} not found")
    db.close_edge(edge_id, actor=principal.user_id)


def graph_view(principal: Principal, brand_id: str, *, as_of: Optional[str] = None) -> dict[str, Any]:
    _brand_access(principal, brand_id)
    g = _graph(brand_id, as_of=as_of)
    return {"as_of": as_of, "nodes": [n.model_dump(mode="json") for n in g.nodes.values()],
            "edges": [e.model_dump(mode="json") for e in g.edges], "lineage_cycles": g.find_cycles(),
            "snapshot": g.snapshot()}


def impact(principal: Principal, brand_id: str, node_ids: list[str], *, as_of: Optional[str] = None) -> dict[str, Any]:
    _brand_access(principal, brand_id)
    return _graph(brand_id, as_of=as_of).impact(node_ids)


def evidence(principal: Principal, node_id: str, *, as_of: Optional[str] = None) -> dict[str, Any]:
    node = db.get_node(node_id)
    if node is None or node["tenant_id"] != principal.tenant_id:
        raise db.VnexusNotFound(f"node {node_id} not found")
    _brand_access(principal, node["brand_id"])
    g = _graph(node["brand_id"], as_of=as_of)
    try:
        out = g.evidence_for(node_id)
    except GraphError as exc:
        raise db.VnexusConflict(str(exc)) from exc
    out["history"] = g.history(node_id)
    return out


def snapshot_diff(principal: Principal, brand_id: str, *, from_ts: str, to_ts: Optional[str]) -> dict[str, Any]:
    _brand_access(principal, brand_id)
    return diff_snapshots(_graph(brand_id, as_of=from_ts).snapshot(), _graph(brand_id, as_of=to_ts).snapshot())


def record_genome_decision(version: dict, approval: dict) -> None:
    """Link an approved genome version into the graph: GenomeVersion -APPROVED_BY-> Approval, -SUPERSEDES-> previous."""
    brand_id, tenant_id = version["brand_id"], version["tenant_id"]
    with transaction(write=True) as conn:
        graph = _graph_locked(conn, brand_id)
        attrs = {"ref": version["version_id"], "scope": version["scope"], "scope_ref": version["scope_ref"],
                 "version": version["version"], "content_hash": version["content_hash"]}
        label = f"{version['scope']}:{version['scope_ref']} v{version['version']}"
        node = db.insert_node(tenant_id=tenant_id, brand_id=brand_id, kind=NodeKind.GENOME_VERSION.value, label=label,
                              attributes=attrs, content_hash=node_hash(NodeKind.GENOME_VERSION, label, attrs), actor="system", db=conn)
        a_attrs = {"ref": approval["approval_id"], "reviewer": approval.get("reviewer"), "decision": approval.get("decision"),
                   "subject_hash": approval.get("subject_hash"), "decided_at": approval.get("decided_at")}
        a_node = db.insert_node(tenant_id=tenant_id, brand_id=brand_id, kind=NodeKind.APPROVAL.value,
                                label=f"approval {approval['approval_id'][:8]}", attributes=a_attrs,
                                content_hash=node_hash(NodeKind.APPROVAL, "approval", a_attrs), actor="system", db=conn)
        db.insert_edge(tenant_id=tenant_id, brand_id=brand_id, kind=EdgeKind.APPROVED_BY.value, src=node["node_id"],
                       dst=a_node["node_id"], provenance={"approval_id": approval["approval_id"]}, actor="system", db=conn)
        previous = [n for n in graph.nodes.values() if n.kind is NodeKind.GENOME_VERSION
                    and (n.attributes.get("scope"), n.attributes.get("scope_ref")) == (version["scope"], version["scope_ref"])]
        for prev in previous:
            db.insert_edge(tenant_id=tenant_id, brand_id=brand_id, kind=EdgeKind.SUPERSEDES.value, src=node["node_id"],
                           dst=prev.node_id, provenance={"reason": "genome version approved"}, actor="system", db=conn)
            db.close_node(conn, node_id=prev.node_id, superseded_by=node["node_id"], actor="system")
        origin_branch = version.get("origin_ref") if version.get("origin") == "BRANCH_PROMOTION" else None
        branch_node = next((n for n in graph.nodes.values() if n.kind is NodeKind.BRANCH and n.attributes.get("ref") == origin_branch),
                           None) if origin_branch else None
        if branch_node is not None:
            db.insert_edge(tenant_id=tenant_id, brand_id=brand_id, kind=EdgeKind.DERIVED_FROM.value, src=node["node_id"],
                           dst=branch_node.node_id, provenance={"reason": "promoted branch"}, actor="system", db=conn)


# --------------------------------------------------------------------------- branches


def _base(principal: Principal, version_id: str) -> tuple[dict, GenomeDocument]:
    row = service.get_version(principal, version_id, settle=False)
    return row, GenomeDocument.model_validate(row["document"])


def _branch(principal: Principal, branch_id: str) -> dict:
    row = db.get_branch(branch_id)
    if row is None or row["tenant_id"] != principal.tenant_id:
        raise db.VnexusNotFound(f"branch {branch_id} not found")
    service.authorize(principal, row["project_id"])
    return row


def _ancestors(row: dict) -> list:
    """Approved layers strictly above the branch's scope."""
    layers = service.layers_for(row["brand_id"], Scope(row["scope"]), row["scope_ref"])
    return [layer for layer in layers if layer.scope_ref != row["scope_ref"] or layer.scope.value != row["scope"]]


def fork(principal: Principal, brand_id: str, *, base_version_id: str, name: str, hypothesis: str, changes: ChangeSet,
         parent_branch_id: Optional[str] = None) -> dict:
    base_row, base_doc = _base(principal, base_version_id)
    if base_row["brand_id"] != brand_id:
        raise ValueError("base version belongs to a different brand")
    if base_row["status"] != VersionStatus.APPROVED.value:
        raise db.VnexusConflict("a branch forks from the current approved version of its scope")
    service.authorize(principal, base_row["project_id"], write=True)
    effective = changes
    if parent_branch_id:
        parent = _branch(principal, parent_branch_id)
        if parent["base_version_id"] != base_version_id:
            raise ValueError("a sub-branch must share its parent's base version")
        effective = compose(ChangeSet.model_validate(parent["changes"]), changes)
    apply_changes(base_doc, effective)  # validates the change set against the base
    row = db.create_branch(tenant_id=principal.tenant_id, brand_id=brand_id, scope=base_row["scope"], scope_ref=base_row["scope_ref"],
                           project_id=base_row["project_id"], base_version_id=base_version_id, parent_branch_id=parent_branch_id,
                           name=name, hypothesis=hypothesis, changes=effective.model_dump(mode="json"),
                           changes_hash=effective.changes_hash, actor=principal.user_id)
    _link_branch_node(principal, row)
    return row


def _link_branch_node(principal: Principal, row: dict) -> None:
    attrs = {"ref": row["branch_id"], "name": row["name"], "hypothesis": row["hypothesis"], "base_version_id": row["base_version_id"]}
    with transaction(write=True) as conn:
        graph = _graph_locked(conn, row["brand_id"])
        node = db.insert_node(tenant_id=row["tenant_id"], brand_id=row["brand_id"], kind=NodeKind.BRANCH.value, label=row["name"],
                              attributes=attrs, content_hash=node_hash(NodeKind.BRANCH, row["name"], attrs), actor=principal.user_id,
                              db=conn)
        parent_ref = row.get("parent_branch_id") or row["base_version_id"]
        parent_kind = NodeKind.BRANCH if row.get("parent_branch_id") else NodeKind.GENOME_VERSION
        parent = next((n for n in graph.nodes.values() if n.kind is parent_kind and n.attributes.get("ref") == parent_ref), None)
        if parent is not None:
            db.insert_edge(tenant_id=row["tenant_id"], brand_id=row["brand_id"], kind=EdgeKind.DERIVED_FROM.value, src=node["node_id"],
                           dst=parent.node_id, provenance={"reason": "fork"}, actor=principal.user_id, db=conn)


def list_branches(principal: Principal, brand_id: str) -> list[dict]:
    service.brand_for(principal, brand_id)
    return [b for b in db.list_branches(brand_id) if principal.can_access_project(b["project_id"])]


def get_branch(principal: Principal, branch_id: str) -> dict:
    row = _branch(principal, branch_id)
    if row["state"] == BranchState.IN_REVIEW.value:
        row = settle(principal, branch_id)
    return {**row, "evaluations": db.list_branch_evaluations(branch_id)}


def edit(principal: Principal, branch_id: str, *, expected_revision: int, changes: ChangeSet) -> dict:
    row = _branch(principal, branch_id)
    service.authorize(principal, row["project_id"], write=True)
    _, base_doc = _base(principal, row["base_version_id"])
    apply_changes(base_doc, changes)
    return db.update_branch(branch_id, expected_revision=expected_revision, actor=principal.user_id, action="edit",
                            changes=changes.model_dump(mode="json"), changes_hash=changes.changes_hash)


def compare(principal: Principal, branch_id: str) -> dict[str, Any]:
    row = _branch(principal, branch_id)
    _, base_doc = _base(principal, row["base_version_id"])
    report = compare_with_base(base_doc, ChangeSet.model_validate(row["changes"]), _ancestors(row), scope_ref=row["scope_ref"],
                               scope=row["scope"])
    current = db.approved_version(row["brand_id"], row["scope"], row["scope_ref"])
    report["base_is_current"] = bool(current and current["version_id"] == row["base_version_id"])
    report["changes_hash"] = row["changes_hash"]
    return report


def evaluate(principal: Principal, branch_id: str) -> dict:
    """Record the deterministic comparison, bound to the change set it evaluated."""
    row = _branch(principal, branch_id)
    service.authorize(principal, row["project_id"], write=True)
    report = compare(principal, branch_id)
    payload = {"kind": "DETERMINISTIC", "report": report, "note": "constraint and invariant checks only; not a quality judgement"}
    return db.add_branch_evaluation(tenant_id=row["tenant_id"], branch_id=branch_id, kind="DETERMINISTIC", evaluator="vnexus.multiverse",
                                    changes_hash=row["changes_hash"], payload=payload, payload_hash=canonical_hash(payload))


def record_feedback(principal: Principal, branch_id: str, *, text: str, decision: Optional[str] = None) -> dict:
    """What a named person actually said, verbatim. There is no synthetic counterpart."""
    row = _branch(principal, branch_id)
    service.authorize(principal, row["project_id"], write=True)
    if not text.strip():
        raise ValueError("feedback needs the reviewer's own words")
    if decision not in (None, "prefer", "reject", "revise"):
        raise ValueError("decision is prefer, reject or revise")
    payload = {"kind": "HUMAN", "text": text.strip()[:4000], "decision": decision}
    return db.add_branch_evaluation(tenant_id=row["tenant_id"], branch_id=branch_id, kind="HUMAN", evaluator=principal.user_id,
                                    changes_hash=row["changes_hash"], payload=payload, payload_hash=canonical_hash(payload))


def compare_two(principal: Principal, a_id: str, b_id: str) -> dict[str, Any]:
    a, b = _branch(principal, a_id), _branch(principal, b_id)
    if a["base_version_id"] != b["base_version_id"]:
        return {"comparable": False, "reason": "branches have different base versions; rebase one first",
                "a_base": a["base_version_id"], "b_base": b["base_version_id"]}
    return {"comparable": True, **compare_branches(ChangeSet.model_validate(a["changes"]), ChangeSet.model_validate(b["changes"]))}


def merge(principal: Principal, a_id: str, b_id: str, *, name: str) -> dict:
    """Combine two branches into a new candidate branch. Conflicts are reported, never resolved by picking a side."""
    a, b = _branch(principal, a_id), _branch(principal, b_id)
    if a["base_version_id"] != b["base_version_id"]:
        raise db.VnexusConflict("branches have different base versions; rebase one first")
    merged, report = merge_change_sets(ChangeSet.model_validate(a["changes"]), ChangeSet.model_validate(b["changes"]))
    if merged is None:
        raise MergeConflict(report)
    row = fork(principal, a["brand_id"], base_version_id=a["base_version_id"], name=name,
               hypothesis=f"merge of {a['name']} and {b['name']}", changes=merged)
    return {"branch": row, "report": report}


class MergeConflict(ValueError):
    def __init__(self, report: dict):
        super().__init__("branches conflict; resolve the listed keys in one branch first")
        self.report = report


def rebase_branch(principal: Principal, branch_id: str) -> dict:
    row = _branch(principal, branch_id)
    service.authorize(principal, row["project_id"], write=True)
    current = db.approved_version(row["brand_id"], row["scope"], row["scope_ref"])
    if current is None or current["version_id"] == row["base_version_id"]:
        return {"branch": row, "report": {"rebased": False, "reason": "already on the current approved version"}}
    _, old_doc = _base(principal, row["base_version_id"])
    new_doc = GenomeDocument.model_validate(current["document"])
    carried, report = rebase(old_doc, new_doc, ChangeSet.model_validate(row["changes"]))
    if carried is None:
        raise MergeConflict({**report, "rebased": False})
    updated = db.update_branch(branch_id, expected_revision=row["revision"], actor=principal.user_id, action="rebase",
                               base_version_id=current["version_id"], detail={"from": row["base_version_id"], "to": current["version_id"]})
    return {"branch": updated, "report": {**report, "rebased": True}}


def submit(principal: Principal, branch_id: str) -> dict:
    row = _branch(principal, branch_id)
    service.authorize(principal, row["project_id"], write=True)
    next_branch_state(BranchState(row["state"]), "submit")
    report = compare(principal, branch_id)
    if not report["base_is_current"]:
        raise db.VnexusConflict("the base version is no longer the approved version; rebase the branch first")
    if not report["promotable"]:
        raise service.GenomeBlocked("branch breaks approved invariants or blocking constraints", report)
    _, base_doc = _base(principal, row["base_version_id"])
    doc = apply_changes(base_doc, ChangeSet.model_validate(row["changes"]))
    version = db.create_version(tenant_id=row["tenant_id"], brand_id=row["brand_id"], scope=row["scope"], scope_ref=row["scope_ref"],
                                project_id=row["project_id"], document=doc.model_dump(mode="json"), content_hash=doc.content_hash,
                                actor=principal.user_id, origin="BRANCH_PROMOTION", origin_ref=branch_id,
                                parent_version_id=row["base_version_id"])
    submitted = service.submit_version(principal, version["version_id"])
    branch = db.update_branch(branch_id, expected_revision=row["revision"], actor=principal.user_id, action="submit",
                              state=BranchState.IN_REVIEW.value, from_state=BranchState.OPEN.value,
                              proposal_version_id=version["version_id"], detail={"approval_id": submitted["approval_id"]})
    return {"branch": branch, "proposal": submitted}


def settle(principal: Principal, branch_id: str) -> dict:
    row = _branch(principal, branch_id)
    if row["state"] != BranchState.IN_REVIEW.value or not row.get("proposal_version_id"):
        return row
    version = service.settle_version(principal, row["proposal_version_id"])
    mapping = {"APPROVED": ("promote", BranchState.PROMOTED), "REJECTED": ("reject", BranchState.REJECTED),
               "DRAFT": ("withdraw", BranchState.OPEN)}
    if version["status"] not in mapping:
        return row
    action, target = mapping[version["status"]]
    return db.update_branch(branch_id, expected_revision=row["revision"], actor=version.get("decided_by") or "system", action=action,
                            state=target.value, from_state=BranchState.IN_REVIEW.value,
                            decision_note=f"proposal {version['version_id']} {version['status']}")


def archive(principal: Principal, branch_id: str) -> dict:
    row = _branch(principal, branch_id)
    service.authorize(principal, row["project_id"], write=True)
    next_branch_state(BranchState(row["state"]), "archive")
    return db.update_branch(branch_id, expected_revision=row["revision"], actor=principal.user_id, action="archive",
                            state=BranchState.ARCHIVED.value, from_state=BranchState.OPEN.value)


__all__ = ["MergeConflict", "add_edge", "add_node", "archive", "compare", "compare_two", "edit", "evaluate", "evidence", "fork",
           "get_branch", "graph_view", "impact", "list_branches", "merge", "rebase_branch", "record_feedback", "record_genome_decision",
           "retire_edge", "settle", "snapshot_diff", "submit", "supersede_node"]
