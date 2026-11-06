"""VNEXUS temporal creative knowledge graph: typed nodes and edges with validity windows.

Pure functions over node/edge records. Persistence is ``persistence/vnexus.py``
(two relational tables; a graph database is not justified at this size). The
rules enforced here:

* every edge kind declares which node kinds it may connect;
* lineage edges (DERIVED_FROM, DEPENDS_ON, SUPERSEDES, IMPLEMENTS, GENERATED_BY)
  must stay acyclic among edges valid at the same moment; CONFLICTS_WITH may
  be symmetric;
* superseding a node closes its validity window and links the replacement,
  it never deletes the old decision;
* ``as_of`` reads see only nodes and edges valid at that instant.

Impact analysis follows dependency edges in reverse: if X changes, everything
that (transitively) depends on, derives from, implements or was generated from
X is affected.
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.execution.canonical import canonical_hash


class NodeKind(str, Enum):
    BRAND = "Brand"
    GENOME_VERSION = "GenomeVersion"
    CAMPAIGN = "Campaign"
    AUDIENCE = "Audience"
    INSIGHT = "Insight"
    DESIGN_DECISION = "DesignDecision"
    CREATIVE_CONCEPT = "CreativeConcept"
    ASSET = "Asset"
    PROMPT = "Prompt"
    EXPERIMENT = "Experiment"
    EXPERIENCE = "Experience"
    CHANNEL = "Channel"
    PROVIDER_JOB = "ProviderJob"
    APPROVAL = "Approval"
    EVIDENCE = "Evidence"
    BRANCH = "Branch"


class EdgeKind(str, Enum):
    DERIVED_FROM = "DERIVED_FROM"
    APPROVED_BY = "APPROVED_BY"
    DEPENDS_ON = "DEPENDS_ON"
    SUPERSEDES = "SUPERSEDES"
    IMPLEMENTS = "IMPLEMENTS"
    GENERATED_BY = "GENERATED_BY"
    TESTED_BY = "TESTED_BY"
    TARGETS = "TARGETS"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    SUPPORTED_BY = "SUPPORTED_BY"


ANY = frozenset(NodeKind)
_PRODUCTS = frozenset({NodeKind.ASSET, NodeKind.EXPERIENCE, NodeKind.CREATIVE_CONCEPT, NodeKind.CAMPAIGN, NodeKind.PROMPT})

# edge kind -> (allowed source kinds, allowed destination kinds)
EDGE_RULES: dict[EdgeKind, tuple[frozenset[NodeKind], frozenset[NodeKind]]] = {
    EdgeKind.DERIVED_FROM: (ANY - {NodeKind.APPROVAL, NodeKind.EVIDENCE}, ANY - {NodeKind.APPROVAL}),
    EdgeKind.APPROVED_BY: (ANY - {NodeKind.APPROVAL, NodeKind.EVIDENCE}, frozenset({NodeKind.APPROVAL})),
    EdgeKind.DEPENDS_ON: (ANY - {NodeKind.APPROVAL}, ANY - {NodeKind.APPROVAL}),
    EdgeKind.SUPERSEDES: (ANY, ANY),  # same-kind is checked separately
    EdgeKind.IMPLEMENTS: (_PRODUCTS | {NodeKind.GENOME_VERSION}, frozenset({NodeKind.DESIGN_DECISION, NodeKind.CREATIVE_CONCEPT,
                                                                           NodeKind.CAMPAIGN, NodeKind.INSIGHT})),
    EdgeKind.GENERATED_BY: (frozenset({NodeKind.ASSET, NodeKind.EXPERIENCE}), frozenset({NodeKind.PROVIDER_JOB, NodeKind.PROMPT})),
    EdgeKind.TESTED_BY: (_PRODUCTS | {NodeKind.DESIGN_DECISION, NodeKind.INSIGHT}, frozenset({NodeKind.EXPERIMENT})),
    EdgeKind.TARGETS: (_PRODUCTS | {NodeKind.EXPERIMENT}, frozenset({NodeKind.AUDIENCE, NodeKind.CHANNEL})),
    EdgeKind.CONFLICTS_WITH: (ANY - {NodeKind.APPROVAL, NodeKind.EVIDENCE}, ANY - {NodeKind.APPROVAL, NodeKind.EVIDENCE}),
    EdgeKind.SUPPORTED_BY: (ANY - {NodeKind.EVIDENCE}, frozenset({NodeKind.EVIDENCE})),
}
ACYCLIC = frozenset({EdgeKind.DERIVED_FROM, EdgeKind.DEPENDS_ON, EdgeKind.SUPERSEDES, EdgeKind.IMPLEMENTS, EdgeKind.GENERATED_BY})
# Edges whose source is affected when their destination changes.
IMPACT_EDGES = frozenset({EdgeKind.DERIVED_FROM, EdgeKind.DEPENDS_ON, EdgeKind.IMPLEMENTS, EdgeKind.GENERATED_BY, EdgeKind.TESTED_BY})


class GraphError(ValueError):
    pass


class Node(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    node_id: str
    kind: NodeKind
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    valid_from: str
    valid_to: Optional[str] = None
    superseded_by: Optional[str] = None


class Edge(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    edge_id: str
    kind: EdgeKind
    src_node_id: str
    dst_node_id: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    valid_from: str
    valid_to: Optional[str] = None


def node_hash(kind: NodeKind, label: str, attributes: dict[str, Any]) -> str:
    return canonical_hash({"kind": kind.value, "label": label, "attributes": attributes})


def valid_at(record: Node | Edge, as_of: Optional[str]) -> bool:
    if as_of is None:
        return record.valid_to is None
    return record.valid_from <= as_of and (record.valid_to is None or as_of < record.valid_to)


class Graph:
    """An in-memory view of one brand's graph at one instant."""

    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge], *, as_of: Optional[str] = None):
        self.as_of = as_of
        self.all_nodes = {n.node_id: n for n in nodes}
        self.nodes = {k: n for k, n in self.all_nodes.items() if valid_at(n, as_of)}
        edges = list(edges)
        # Edges valid at the instant, including those that point at a node since superseded (lineage to history).
        self.all_edges = [e for e in edges if valid_at(e, as_of) and e.src_node_id in self.all_nodes and e.dst_node_id in self.all_nodes]
        self.edges = [e for e in self.all_edges if e.src_node_id in self.nodes and e.dst_node_id in self.nodes]

    # ------------------------------------------------------------------ validation
    def check_edge(self, kind: EdgeKind, src: str, dst: str) -> None:
        if src == dst:
            raise GraphError("an edge cannot connect a node to itself")
        if src not in self.nodes or dst not in self.nodes:
            raise GraphError("both endpoints must exist and be currently valid")
        a, b = self.nodes[src].kind, self.nodes[dst].kind
        sources, targets = EDGE_RULES[kind]
        if a not in sources or b not in targets:
            raise GraphError(f"{kind.value} may not connect {a.value} -> {b.value}")
        if kind is EdgeKind.SUPERSEDES and a is not b:
            raise GraphError("SUPERSEDES connects two nodes of the same kind")
        if any(e.kind is kind and e.src_node_id == src and e.dst_node_id == dst for e in self.edges):
            raise GraphError(f"{kind.value} {src} -> {dst} already exists")
        if kind in ACYCLIC and self.reaches(dst, src, ACYCLIC):
            raise GraphError(f"{kind.value} {src} -> {dst} would create a lineage cycle")

    def reaches(self, start: str, goal: str, kinds: frozenset[EdgeKind]) -> bool:
        seen, queue = {start}, deque([start])
        while queue:
            cur = queue.popleft()
            if cur == goal:
                return True
            for e in self.edges:
                if e.kind in kinds and e.src_node_id == cur and e.dst_node_id not in seen:
                    seen.add(e.dst_node_id)
                    queue.append(e.dst_node_id)
        return False

    def find_cycles(self) -> list[list[str]]:
        """Lineage cycles in the stored data (should be none; detects rows written around the API)."""
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            if e.kind in ACYCLIC:
                adj.setdefault(e.src_node_id, []).append(e.dst_node_id)
        cycles: list[list[str]] = []
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(n: str) -> None:
            state[n] = 1
            stack.append(n)
            for m in sorted(adj.get(n, [])):
                if state.get(m) == 1:
                    cycles.append(stack[stack.index(m):] + [m])
                elif m not in state:
                    visit(m)
            stack.pop()
            state[n] = 2

        for n in sorted(adj):
            if n not in state:
                visit(n)
        return cycles

    # ------------------------------------------------------------------ queries
    def upstream(self, node_id: str, kinds: frozenset[EdgeKind] = IMPACT_EDGES) -> list[str]:
        out, seen, queue = [], {node_id}, deque([node_id])
        while queue:
            cur = queue.popleft()
            for e in sorted(self.edges, key=lambda e: e.edge_id):
                if e.kind in kinds and e.src_node_id == cur and e.dst_node_id not in seen:
                    seen.add(e.dst_node_id)
                    out.append(e.dst_node_id)
                    queue.append(e.dst_node_id)
        return out

    def impact(self, changed: Iterable[str]) -> dict[str, Any]:
        """Everything downstream of the changed nodes, with the shortest dependency path to each."""
        changed = [c for c in changed if c in self.nodes]
        paths: dict[str, list[str]] = {c: [c] for c in changed}
        queue = deque(changed)
        while queue:
            cur = queue.popleft()
            for e in sorted(self.edges, key=lambda e: e.edge_id):
                if e.kind in IMPACT_EDGES and e.dst_node_id == cur and e.src_node_id not in paths:
                    paths[e.src_node_id] = paths[cur] + [f"<-{e.kind.value}-", e.src_node_id]
                    queue.append(e.src_node_id)
        affected = sorted((n for n in paths if n not in changed), key=lambda n: (len(paths[n]), n))
        return {"changed": sorted(changed), "affected": [{"node_id": n, "kind": self.nodes[n].kind.value, "label": self.nodes[n].label,
                                                          "path": paths[n]} for n in affected]}

    def evidence_for(self, node_id: str) -> dict[str, Any]:
        """Evidence and approvals supporting a node, directly or through what it implements or derives from."""
        if node_id not in self.nodes:
            raise GraphError(f"node {node_id} is not valid at this instant")
        chain = [node_id] + self.upstream(node_id, frozenset({EdgeKind.IMPLEMENTS, EdgeKind.DERIVED_FROM}))
        evidence, approvals = [], []
        for n in chain:
            for e in self.edges:
                if e.src_node_id != n:
                    continue
                target = self.nodes[e.dst_node_id]
                item = {"via": n, "node_id": target.node_id, "label": target.label, "attributes": target.attributes,
                        "edge_provenance": e.provenance}
                if e.kind is EdgeKind.SUPPORTED_BY:
                    evidence.append(item)
                elif e.kind is EdgeKind.APPROVED_BY:
                    approvals.append(item)
        return {"node_id": node_id, "considered": chain, "evidence": evidence, "approvals": approvals,
                "unsupported": not evidence and not approvals}

    def history(self, node_id: str) -> list[str]:
        """The supersession chain through ``node_id``, oldest first (uses all nodes, not just valid ones)."""
        older = {n.superseded_by: n.node_id for n in self.all_nodes.values() if n.superseded_by}
        first = node_id
        while first in older:
            first = older[first]
        chain = [first]
        while self.all_nodes.get(chain[-1]) and self.all_nodes[chain[-1]].superseded_by:
            chain.append(self.all_nodes[chain[-1]].superseded_by)
        return chain

    def snapshot(self) -> dict[str, Any]:
        nodes = {n.node_id: n.content_hash for n in self.nodes.values()}
        edges = sorted(f"{e.src_node_id}|{e.kind.value}|{e.dst_node_id}" for e in self.edges)
        return {"as_of": self.as_of, "nodes": dict(sorted(nodes.items())), "edges": edges,
                "snapshot_hash": canonical_hash({"nodes": nodes, "edges": edges})}


def diff_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    na, nb = a["nodes"], b["nodes"]
    ea, eb = set(a["edges"]), set(b["edges"])
    return {"from": a["as_of"], "to": b["as_of"], "nodes_added": sorted(set(nb) - set(na)), "nodes_removed": sorted(set(na) - set(nb)),
            "nodes_changed": sorted(k for k in set(na) & set(nb) if na[k] != nb[k]), "edges_added": sorted(eb - ea),
            "edges_removed": sorted(ea - eb), "identical": a["snapshot_hash"] == b["snapshot_hash"]}


__all__ = ["ACYCLIC", "EDGE_RULES", "Edge", "EdgeKind", "Graph", "GraphError", "IMPACT_EDGES", "Node", "NodeKind", "diff_snapshots",
           "node_hash", "valid_at"]
