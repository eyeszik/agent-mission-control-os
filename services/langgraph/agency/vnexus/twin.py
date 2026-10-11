"""VNEXUS creative digital twin: the approved creative system as a testable model.

Every result here is a SIMULATION computed from stored state. Nothing is
written, no approval is opened, and no number is presented as a business
outcome. The twin answers: if this approved scope changed this way, which
descendant scopes would conflict, which produced assets would drift or need
regeneration, and would the change be promotable.
"""

from __future__ import annotations

from typing import Any, Optional

from services.langgraph.persistence import vnexus as db
from services.langgraph.security.auth import Principal

from . import immune, media_fabric, service
from .creative_service import _graph
from .genome import SCOPE_ORDER, GenomeDocument, GenomeLayer, Scope, VersionStatus, ancestor_refs, resolve
from .graph import NodeKind
from .multiverse import ChangeSet, apply_changes, compare_with_base

LABEL = "SIMULATION: computed from stored state; nothing changed and no outcome is measured"


def _approved(brand_id: str) -> list[dict]:
    return db.list_versions(brand_id, statuses=["APPROVED"])


def _layers(brand_id: str, scope: Scope, scope_ref: str, override: Optional[tuple[str, str, GenomeDocument]] = None) -> list[GenomeLayer]:
    layers = []
    for s, ref in ancestor_refs(scope, scope_ref, brand_id):
        if override and (s.value, ref) == override[:2]:
            layers.append(GenomeLayer(scope=s, scope_ref=ref, status=VersionStatus.APPROVED, document=override[2]))
            continue
        row = db.approved_version(brand_id, s.value, ref)
        if row:
            layers.append(GenomeLayer(scope=s, scope_ref=ref, status=VersionStatus.APPROVED, document=GenomeDocument.model_validate(row["document"])))
    return layers


def _is_descendant(scope: Scope, scope_ref: str, other: dict) -> bool:
    deeper = SCOPE_ORDER.index(Scope(other["scope"])) > SCOPE_ORDER.index(scope)
    return deeper and (scope is Scope.BRAND or other["scope_ref"].startswith(scope_ref + "/") or other["scope_ref"] == scope_ref)


def snapshot(principal: Principal, brand_id: str) -> dict[str, Any]:
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, brand["owner_project_id"])
    approved = _approved(brand_id)
    scopes = []
    for row in approved:
        res = resolve(_layers(brand_id, Scope(row["scope"]), row["scope_ref"]))
        scopes.append({"scope": row["scope"], "scope_ref": row["scope_ref"], "version": row["version"], "version_id": row["version_id"],
                       "resolution_hash": res.resolution_hash, "failed_findings": [f.constraint_id for f in res.findings if not f.passed],
                       "conflicts": [c.reason.value for c in res.conflicts]})
    g = _graph(brand_id)
    branches = db.list_branches(brand_id)
    in_review = db.list_versions(brand_id, statuses=["IN_REVIEW"])
    produced = [n for n in g.nodes.values() if n.kind in (NodeKind.ASSET, NodeKind.EXPERIENCE)]
    return {"brand_id": brand_id, "approved_scopes": scopes, "graph": g.snapshot(), "produced_outputs": len(produced),
            "open_branches": sum(1 for b in branches if b["state"] == "OPEN"), "versions_in_review": len(in_review),
            "release_readiness": {"scopes_with_failed_findings": sum(1 for s in scopes if s["failed_findings"]),
                                  "scopes_with_conflicts": sum(1 for s in scopes if s["conflicts"]),
                                  "pending_human_decisions": len(in_review) + sum(1 for b in branches if b["state"] == "IN_REVIEW")},
            "label": LABEL}


def simulate_change(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, changes: ChangeSet) -> dict[str, Any]:
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, service.scope_project(brand, scope, scope_ref))
    base = db.approved_version(brand_id, scope.value, scope_ref)
    if base is None:
        raise db.VnexusNotFound("no approved version at this scope to simulate against")
    base_doc = GenomeDocument.model_validate(base["document"])
    new_doc = apply_changes(base_doc, changes)
    ancestors = [layer for layer in _layers(brand_id, scope, scope_ref) if layer.scope_ref != scope_ref or layer.scope is not scope]
    own = compare_with_base(base_doc, changes, ancestors, scope_ref=scope_ref, scope=scope.value)
    descendants = []
    for row in _approved(brand_id):
        if not _is_descendant(scope, scope_ref, row):
            continue
        s, ref = Scope(row["scope"]), row["scope_ref"]
        before = resolve(_layers(brand_id, s, ref))
        after = resolve(_layers(brand_id, s, ref, override=(scope.value, scope_ref, new_doc)))
        new_conflicts = {(c.key, c.reason.value) for c in after.conflicts} - {(c.key, c.reason.value) for c in before.conflicts}
        newly_failed = {f.constraint_id for f in after.findings if not f.passed} - {f.constraint_id for f in before.findings if not f.passed}
        descendants.append({"scope": s.value, "scope_ref": ref, "new_conflicts": sorted(new_conflicts), "newly_failed": sorted(newly_failed),
                            "values_changed": sorted(k for k in set(before.values) | set(after.values) if before.values.get(k) != after.values.get(k))})
    g = _graph(brand_id)
    gv = next((n for n in g.nodes.values() if n.kind is NodeKind.GENOME_VERSION and n.attributes.get("ref") == base["version_id"]), None)
    impact = g.impact([gv.node_id]) if gv else {"changed": [], "affected": []}
    new_res = resolve(_layers(brand_id, scope, scope_ref, override=(scope.value, scope_ref, new_doc)))
    palette, fonts = immune.palette_from(new_res), immune.approved_fonts(new_res)
    drift = []
    if palette:
        from services.langgraph.agency.foundry.studio import observe
        from services.langgraph.api.routes._project_common import storage_adapter
        from services.langgraph.persistence.agency_kernel import get_artifact

        adapter = storage_adapter()
        for item in impact["affected"]:
            node = g.nodes[item["node_id"]]
            ref = node.attributes.get("ref")
            head = get_artifact(ref) if ref else None
            if head and (head.get("metadata") or {}).get("v2", {}).get("mime_type") == "image/svg+xml":
                data, _ = observe(ref, adapter)
                hits = [f["code"] for f in immune.svg_findings(node.label, data.decode("utf-8", "replace"), palette=palette, fonts=fonts)]
                if hits:
                    drift.append({"node_id": node.node_id, "label": node.label, "would_fail": sorted(set(hits))})
    blocking = bool(own["invariant_violations"]) or any(d["new_conflicts"] or d["newly_failed"] for d in descendants)
    return {"scope": scope.value, "scope_ref": scope_ref, "base_version_id": base["version_id"], "own": own, "descendants": descendants,
            "downstream_outputs": impact["affected"], "projected_drift": drift,
            "projection": "WOULD_BLOCK" if blocking else "WOULD_BE_PROMOTABLE",
            "regeneration_needed": len(impact["affected"]), "label": LABEL}


def simulate_provider_outage(principal: Principal, provider_id: str, *, project_id: str) -> dict[str, Any]:
    service.authorize(principal, project_id)
    provider = media_fabric.get_provider(provider_id)
    caps = provider.capabilities().capabilities
    fallback = {}
    for cap in caps:
        alt = [p for p in media_fabric.REGISTRY.values() if p.provider_id != provider_id and p.kind is not media_fabric.ProviderKind.MOCK
               and cap in p.capabilities().capabilities and p.capabilities().status is media_fabric.ProviderStatus.AVAILABLE]
        fallback[cap.value] = alt[0].provider_id if alt else None
    jobs = [j for j in db.list_media_jobs(project_id) if j["provider_id"] == provider_id]
    return {"provider_id": provider_id, "capabilities": [c.value for c in caps], "fallback_provider": fallback,
            "blocked_capabilities": [c for c, alt in fallback.items() if alt is None], "historical_jobs_on_provider": len(jobs),
            "label": LABEL}


__all__ = ["LABEL", "simulate_change", "simulate_provider_outage", "snapshot"]
