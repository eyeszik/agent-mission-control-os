"""BlastRadiusCertificate: a record of what ProjectOS already decided.

ProjectOS (``record_artifact_revision`` / ``propagate_artifact_change``) is the
only invalidation authority. This certificate is built from its decision after
the fact, so it can explain an invalidation but never cause, widen or narrow
one. ProjectOS invalidates every reachable dependent (hard edges invalidate,
soft edges require review) and keeps none on semantic grounds, so
``preserved_nodes`` is always empty: preserving a node would need evidence that
its acceptance and dependency semantics are unchanged, and ambiguity means
invalidate.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from services.langgraph.agency.execution.canonical import canonical_hash


def blast_radius_certificate(
    *,
    changed_artifact_id: str,
    changed_version_ref: str,
    before_hash: Optional[str],
    after_hash: Optional[str],
    affected: Sequence[Mapping[str, Any]],
    reason_edges: Iterable[Mapping[str, Any]],
    staled_approval_ids: Iterable[str],
    projectos_decision_refs: Iterable[str],
) -> dict[str, Any]:
    affected_nodes = sorted(
        ({"artifact_id": str(a["artifact_id"]), "status": str(a["status"])} for a in affected),
        key=lambda a: a["artifact_id"],
    )
    affected_ids = {a["artifact_id"] for a in affected_nodes} | {changed_artifact_id}
    edges = sorted(
        (
            {
                "artifact_id": str(e["artifact_id"]),
                "depends_on_artifact_id": str(e["depends_on_artifact_id"]),
                "relationship": str(e.get("relationship") or "hard"),
            }
            for e in reason_edges
            if str(e["artifact_id"]) in affected_ids and str(e["depends_on_artifact_id"]) in affected_ids
        ),
        key=lambda e: (e["depends_on_artifact_id"], e["artifact_id"]),
    )
    body = {
        "schema_version": "amc-blast-radius/v1",
        "changed_version_ref": changed_version_ref,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "changed_paths": [changed_artifact_id],
        "affected_nodes": affected_nodes,
        "preserved_nodes": [],
        "staled_approval_ids": sorted(set(staled_approval_ids)),
        "reason_edges": edges,
        "projectos_decision_refs": sorted(set(projectos_decision_refs)),
    }
    return {**body, "certificate_hash": canonical_hash(body)}
