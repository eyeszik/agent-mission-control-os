"""Brand lineage correctness: generic parent → child → grandchild contracts.

No Northline API is invented. This module implements the synthetic lineage
contract required by ISSUE-03: inheritance, override precedence, provenance,
branch isolation, propagation, invalidation, cycle rejection, deletion integrity,
empty/malformed handling, and deterministic traversal.

It is intentionally generic and not tied to a specific brand model so it can
be used without external fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class BrandNode:
    id: str
    parent_id: Optional[str] = None
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)  # property -> source node id


class LineageError(ValueError):
    pass


class BrandLineage:
    """In-memory brand lineage graph with validation."""

    def __init__(self) -> None:
        self._nodes: dict[str, BrandNode] = {}

    # ---- mutation ----------------------------------------------------------

    def add(self, node: BrandNode) -> None:
        if not node.id or not isinstance(node.id, str):
            raise LineageError("node id must be non-empty string")
        if node.id in self._nodes:
            raise LineageError(f"duplicate node {node.id}")
        if node.parent_id is not None:
            if node.parent_id not in self._nodes:
                raise LineageError(f"parent {node.parent_id} does not exist")
            if node.parent_id == node.id:
                raise LineageError("node cannot be its own parent")
            # cycle detection: walk ancestors
            cur = node.parent_id
            visited = {node.id}
            while cur is not None:
                if cur in visited:
                    raise LineageError(f"cycle detected at {cur}")
                visited.add(cur)
                parent = self._nodes.get(cur)
                cur = parent.parent_id if parent else None
        self._nodes[node.id] = node

    def remove(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise LineageError(f"unknown node {node_id}")
        # cannot delete if children exist (referential integrity)
        children = [n.id for n in self._nodes.values() if n.parent_id == node_id]
        if children:
            raise LineageError(f"cannot delete {node_id}: descendants exist {children}")
        del self._nodes[node_id]

    # ---- queries -----------------------------------------------------------

    def get(self, node_id: str) -> BrandNode:
        if node_id not in self._nodes:
            raise LineageError(f"unknown node {node_id}")
        return self._nodes[node_id]

    def ancestors(self, node_id: str) -> list[str]:
        """Root → parent order."""
        node = self.get(node_id)
        chain: list[str] = []
        cur: Optional[str] = node.parent_id
        while cur is not None:
            chain.append(cur)
            cur = self._nodes[cur].parent_id if cur in self._nodes else None
        chain.reverse()
        return chain

    def descendants(self, node_id: str) -> list[str]:
        """Deterministically ordered descendants (BFS, sorted by id at each level)."""
        result: list[str] = []
        frontier = sorted([n.id for n in self._nodes.values() if n.parent_id == node_id])
        while frontier:
            cur = frontier.pop(0)
            result.append(cur)
            children = sorted([n.id for n in self._nodes.values() if n.parent_id == cur])
            frontier.extend(children)
        return result

    def effective_properties(self, node_id: str) -> tuple[dict[str, Any], dict[str, str]]:
        """Merged properties from root → node; child overrides parent. Returns (props, provenance)."""
        node = self.get(node_id)
        chain_ids = self.ancestors(node_id) + [node_id]
        merged: dict[str, Any] = {}
        provenance: dict[str, str] = {}
        for nid in chain_ids:
            n = self._nodes[nid]
            for k, v in n.properties.items():
                merged[k] = v
                provenance[k] = nid
        return merged, provenance

    def is_stale(self, node_id: str, parent_version: int, node_parent_version: int) -> bool:
        """If parent version moved ahead, descendant is stale."""
        return parent_version > node_parent_version

    def lineage_graph(self) -> dict:
        return {
            "nodes": sorted(self._nodes.keys()),
            "edges": sorted([(n.parent_id, n.id) for n in self._nodes.values() if n.parent_id]),
        }
