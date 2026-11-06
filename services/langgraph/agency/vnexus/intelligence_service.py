"""VNEXUS marketing, prompt genome and design immune system services (authorization, storage, graph links)."""

from __future__ import annotations

import json
from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import vnexus as db
from services.langgraph.security.auth import Principal

from . import immune, marketing, prompt_genome, service
from .creative_service import _graph
from .genome import Scope
from .graph import EdgeKind, NodeKind
from .production import approved_projection, link_output

# --------------------------------------------------------------------------- marketing


def plan_campaign(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str,
                  request: marketing.CampaignRequest) -> dict[str, Any]:
    service.authorize(principal, project_id, write=True)
    p, _ = approved_projection(principal, brand_id, scope=scope, scope_ref=scope_ref)
    plan = marketing.compile_campaign(p, request)
    from services.langgraph.agency.foundry.studio import store
    from services.langgraph.api.routes._project_common import storage_adapter

    head = store(principal, project_id, f"vnexus-campaign-{request.campaign_ref}.json", json.dumps(plan, indent=2, sort_keys=True).encode(),
                 mime="application/json", artifact_type="campaign_package", subtype="vnexus_campaign_plan", adapter=storage_adapter(),
                 v2={"provenance_ref": f"vnexus:{p.genome_ref}"})
    node = link_output(principal, brand_id, label=f"campaign {request.campaign_ref}", kind=NodeKind.CAMPAIGN, ref=head["artifact_id"],
                       attributes={"campaign_ref": request.campaign_ref, "plan_hash": plan["plan_hash"]}, genome_version_id=p.genome_ref,
                       job_id=None)
    _link_audiences(principal, brand_id, node, plan)
    return {"plan": plan, "artifact_id": head["artifact_id"], "version": head["version"], "graph_node": node}


def _link_audiences(principal: Principal, brand_id: str, campaign_node: str, plan: dict[str, Any]) -> None:
    from services.langgraph.persistence.database import transaction

    from .graph import node_hash

    with transaction(write=True) as conn:
        nodes, _ = db.load_graph(conn, brand_id, lock=True)
        current = {(n["kind"], (n["attributes"] or {}).get("ref")): n["node_id"] for n in nodes if n["valid_to"] is None}
        for seg in plan["segments"]:
            ref = f"segment:{seg['segment_id']}"
            nid = current.get((NodeKind.AUDIENCE.value, ref))
            if nid is None:
                attrs = {"ref": ref, "evidence": seg["evidence"], "evidence_refs": seg["evidence_refs"]}
                nid = db.insert_node(tenant_id=principal.tenant_id, brand_id=brand_id, kind=NodeKind.AUDIENCE.value, label=seg["name"],
                                     attributes=attrs, content_hash=node_hash(NodeKind.AUDIENCE, seg["name"], attrs), actor=principal.user_id,
                                     db=conn)["node_id"]
            db.insert_edge(tenant_id=principal.tenant_id, brand_id=brand_id, kind=EdgeKind.TARGETS.value, src=campaign_node, dst=nid,
                           provenance={"plan_hash": plan["plan_hash"]}, actor=principal.user_id, db=conn)
        for ch in plan["brief"]["channels"]:
            ref = f"channel:{ch}"
            nid = current.get((NodeKind.CHANNEL.value, ref))
            if nid is None:
                attrs = {"ref": ref}
                nid = db.insert_node(tenant_id=principal.tenant_id, brand_id=brand_id, kind=NodeKind.CHANNEL.value, label=ch, attributes=attrs,
                                     content_hash=node_hash(NodeKind.CHANNEL, ch, attrs), actor=principal.user_id, db=conn)["node_id"]
            db.insert_edge(tenant_id=principal.tenant_id, brand_id=brand_id, kind=EdgeKind.TARGETS.value, src=campaign_node, dst=nid,
                           provenance={"plan_hash": plan["plan_hash"]}, actor=principal.user_id, db=conn)


def record_measurement(principal: Principal, project_id: str, *, campaign_ref: str, metric: str, value: float, unit: str, source: str,
                       source_ref: str, observed_at: str) -> dict:
    service.authorize(principal, project_id, write=True)
    if not source.strip() or not source_ref.strip():
        raise ValueError("a measurement names its source system and a reference into it")
    if value < 0:
        raise ValueError("measured counts and amounts are not negative")
    return db.record_measurement(tenant_id=principal.tenant_id, project_id=project_id, campaign_ref=campaign_ref, metric=metric,
                                 value=value, unit=unit, source=source, source_ref=source_ref, observed_at=observed_at, actor=principal.user_id)


def campaign_report(principal: Principal, project_id: str, campaign_ref: str) -> dict[str, Any]:
    service.authorize(principal, project_id)
    from services.langgraph.agency.foundry.studio import _key, observe
    from services.langgraph.api.routes._project_common import storage_adapter
    from services.langgraph.persistence.projects import project_artifact_id

    data, _ = observe(project_artifact_id(project_id, _key(f"vnexus-campaign-{campaign_ref}.json")), storage_adapter())
    plan = json.loads(data)
    return marketing.report(plan, db.list_measurements(project_id, campaign_ref))


# --------------------------------------------------------------------------- prompt genomes


def _brand_write(principal: Principal, brand_id: str) -> dict:
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, brand["owner_project_id"], write=True)
    return brand


def create_prompt(principal: Principal, brand_id: str, *, prompt_id: str, document: prompt_genome.PromptGenomeDocument) -> dict:
    _brand_write(principal, brand_id)
    if document.source_text is not None:
        raise ValueError("source_text is set only by the original-source import")
    kind = prompt_genome.SourceKind.DERIVED if document.template_of else prompt_genome.SourceKind.AUTHORED
    return db.create_prompt_version(tenant_id=principal.tenant_id, brand_id=brand_id, prompt_id=prompt_id,
                                    document=document.model_dump(mode="json"), content_hash=document.content_hash, source_kind=kind.value,
                                    source_hash=None, actor=principal.user_id)


def import_original(principal: Principal, brand_id: str, *, prompt_id: str, text: str, source_ref: str,
                    family: str, asset_type: str) -> dict:
    """Byte-preserving import of an original source prompt. The text is stored exactly as given, with its SHA-256."""
    _brand_write(principal, brand_id)
    if not text.strip() or not source_ref.strip():
        raise ValueError("an original import needs the exact text and where it came from")
    doc = prompt_genome.PromptGenomeDocument(intent=text[:1000], family=family, asset_type=asset_type, source_text=text,
                                             quality_rules=(f"original source: {source_ref}",))
    return db.create_prompt_version(tenant_id=principal.tenant_id, brand_id=brand_id, prompt_id=prompt_id,
                                    document=doc.model_dump(mode="json"), content_hash=doc.content_hash,
                                    source_kind=prompt_genome.SourceKind.ORIGINAL_IMPORT.value,
                                    source_hash=prompt_genome.source_hash(text), actor=principal.user_id)


def list_prompts(principal: Principal, brand_id: str) -> dict[str, Any]:
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, brand["owner_project_id"])
    rows = db.list_prompt_versions(brand_id)
    return {"prompts": rows, "inventory": prompt_genome.inventory(rows)}


def _prompt(principal: Principal, prompt_version_id: str) -> dict:
    row = db.get_prompt_version(prompt_version_id)
    if row is None or row["tenant_id"] != principal.tenant_id:
        raise db.VnexusNotFound(f"prompt version {prompt_version_id} not found")
    brand = service.brand_for(principal, row["brand_id"])
    service.authorize(principal, brand["owner_project_id"])
    doc = prompt_genome.PromptGenomeDocument.model_validate(row["document"])
    if doc.content_hash != row["content_hash"]:
        raise service.GenomeIntegrityError(f"prompt version {prompt_version_id} does not match its recorded hash")
    if row.get("source_hash") and prompt_genome.source_hash(doc.source_text or "") != row["source_hash"]:
        raise service.GenomeIntegrityError("imported source text no longer matches its recorded SHA-256")
    return row


def compile_prompt(principal: Principal, prompt_version_id: str, *, scope: Scope, scope_ref: str, adapt_to: Optional[str] = None) -> dict:
    row = _prompt(principal, prompt_version_id)
    p, meta = approved_projection(principal, row["brand_id"], scope=scope, scope_ref=scope_ref)
    doc = prompt_genome.PromptGenomeDocument.model_validate(row["document"])
    out = prompt_genome.compile_genome_prompt(p, row["prompt_id"], doc, brand_constraints=meta["constraints"])
    if adapt_to and out.get("package"):
        out["adapted"] = prompt_genome.adapt(out["package"], target=adapt_to)
    out["prompt_version_id"] = prompt_version_id
    out["genome_ref"] = p.genome_ref
    return out


def regression(principal: Principal, brand_id: str, prompt_id: str, *, scope: Scope, scope_ref: str) -> dict[str, Any]:
    """Recompile every version against today's approved genome and report what each produces."""
    service.brand_for(principal, brand_id)
    versions = [r for r in db.list_prompt_versions(brand_id, prompt_id)]
    if not versions:
        raise db.VnexusNotFound(f"prompt {prompt_id} not found")
    rows = []
    for r in versions:
        out = compile_prompt(principal, r["prompt_version_id"], scope=scope, scope_ref=scope_ref)
        rows.append({"version": r["version"], "final_state": out["final_state"], "package_hash": out.get("package_hash"),
                     "checks": out.get("checks", {}), "missing_genome_keys": out.get("missing_genome_keys", [])})
    docs = [prompt_genome.PromptGenomeDocument.model_validate(r["document"]) for r in versions]
    diffs = [{"from": versions[i]["version"], "to": versions[i + 1]["version"], **prompt_genome.compare(docs[i], docs[i + 1])}
             for i in range(len(docs) - 1)]
    regressions = [b["version"] for a, b in zip(rows, rows[1:]) if a["final_state"] == "PROMPT_PACKAGE_READY" and b["final_state"] != a["final_state"]]
    return {"prompt_id": prompt_id, "results": rows, "diffs": diffs, "regressions": regressions}


# --------------------------------------------------------------------------- immune system


def scan(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str) -> dict[str, Any]:
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, brand["owner_project_id"])
    resolution, layers = service.resolve_scope(principal, brand_id, scope=scope, scope_ref=scope_ref)
    findings = immune.genome_findings(resolution)
    if not layers:
        findings.append(immune.finding("NO_APPROVED_GENOME", "BLOCKING", f"{scope.value}:{scope_ref}", "no approved genome applies"))
    palette, fonts = immune.palette_from(resolution), immune.approved_fonts(resolution)
    g = _graph(brand_id)
    from services.langgraph.agency.foundry.studio import observe
    from services.langgraph.api.routes._project_common import storage_adapter
    from services.langgraph.persistence.agency_kernel import get_artifact

    adapter = storage_adapter()
    scanned = 0
    for node in sorted(g.nodes.values(), key=lambda n: n.node_id):
        if node.kind not in (NodeKind.ASSET, NodeKind.EXPERIENCE, NodeKind.DESIGN_DECISION, NodeKind.CAMPAIGN):
            continue
        ref = node.attributes.get("ref")
        derived = [e for e in g.all_edges if e.src_node_id == node.node_id and e.kind is EdgeKind.DERIVED_FROM]
        if not derived:
            findings.append(immune.finding("MISSING_PROVENANCE", "ERROR", node.label, "output is not linked to the genome it came from",
                                           evidence={"node_id": node.node_id},
                                           remediation=_provenance_fix(ref) if ref else None))
        else:
            source_gv = g.all_nodes.get(derived[0].dst_node_id)
            if source_gv is not None and source_gv.kind is NodeKind.GENOME_VERSION and source_gv.valid_to is not None:
                findings.append(immune.finding("STALE_GENOME_SOURCE", "WARNING", node.label,
                                               f"produced from {source_gv.label}, which has since been superseded; regenerate to update",
                                               evidence={"node_id": node.node_id, "source": source_gv.attributes.get("ref")}))
        head = get_artifact(ref) if ref else None
        if ref and head is None:
            findings.append(immune.finding("BROKEN_REFERENCE", "ERROR", node.label, f"artifact {ref} no longer exists", evidence={"node_id": node.node_id}))
            continue
        if head is None:
            continue
        scanned += 1
        try:
            data, _ = observe(ref, adapter)
        except Exception as exc:  # noqa: BLE001 - the finding is the result
            findings.append(immune.finding("MISSING_ARTIFACT_EVIDENCE", "BLOCKING", node.label, f"stored bytes unreadable: {type(exc).__name__}",
                                           evidence={"artifact_id": ref}))
            continue
        import hashlib

        if node.attributes.get("sha256") and hashlib.sha256(data).hexdigest() != node.attributes["sha256"]:
            findings.append(immune.finding("ARTIFACT_CHANGED", "ERROR", node.label, "stored bytes differ from the hash recorded when produced",
                                           evidence={"artifact_id": ref}))
        mime = ((head.get("metadata") or {}).get("v2") or {}).get("mime_type")
        if mime == "image/svg+xml":
            for f in immune.svg_findings(node.label, data.decode("utf-8", "replace"), palette=palette, fonts=fonts):
                if f["remediation"]:
                    f["remediation"] = {**f["remediation"], "artifact_id": ref}
                findings.append(f)
        elif mime == "application/json" and node.kind is NodeKind.EXPERIENCE:
            pkg = json.loads(data)
            if [s.get("stage") for s in pkg.get("stages", [])][:1] != ["genome_context"]:
                findings.append(immune.finding("INVALID_OUTPUT_SCHEMA", "ERROR", node.label, "experience package is missing its stages"))
            if node.attributes.get("verification") not in ("PASSED", None, "NOT_APPLICABLE"):
                findings.append(immune.finding("ACCESSIBILITY_REGRESSION", "ERROR", node.label,
                                               f"experience verification is {node.attributes.get('verification')}"))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in immune.SEVERITIES}
    return {"brand_id": brand_id, "scope": scope.value, "scope_ref": scope_ref, "outputs_scanned": scanned, "findings": findings,
            "counts": counts, "healthy": counts["BLOCKING"] == 0 and counts["ERROR"] == 0, "scan_hash": canonical_hash(findings)}


def _provenance_fix(ref: str) -> Optional[dict[str, Any]]:
    from services.langgraph.persistence.agency_kernel import get_artifact

    head = get_artifact(ref)
    prov = (((head or {}).get("metadata") or {}).get("v2") or {}).get("provenance_ref") or ""
    if prov.startswith("vnexus:gv-"):
        return {"kind": "LINK_PROVENANCE", "genome_version_id": prov.split(":", 1)[1], "artifact_id": ref}
    return None


def remediate(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, finding_ids: list[str]) -> dict[str, Any]:
    """Apply only the offered deterministic repairs for the named findings. Each repair is a new revision or a new edge."""
    brand = service.brand_for(principal, brand_id)
    service.authorize(principal, brand["owner_project_id"], write=True)
    report = scan(principal, brand_id, scope=scope, scope_ref=scope_ref)
    chosen = [f for f in report["findings"] if f["finding_id"] in set(finding_ids)]
    unknown = sorted(set(finding_ids) - {f["finding_id"] for f in chosen})
    applied, refused = [], [{"finding_id": u, "reason": "not in the current scan"} for u in unknown]
    swaps: dict[str, dict[str, str]] = {}
    for f in chosen:
        fix = f.get("remediation")
        if not fix:
            refused.append({"finding_id": f["finding_id"], "reason": "no deterministic, reversible repair exists"})
        elif fix["kind"] == "SNAP_COLOUR":
            swaps.setdefault(fix["artifact_id"], {})[fix["from"]] = fix["to"]
        elif fix["kind"] == "LINK_PROVENANCE":
            applied.append(_apply_provenance(principal, brand_id, fix) | {"finding_id": f["finding_id"]})
    from services.langgraph.agency.foundry.studio import observe
    from services.langgraph.api.routes._project_common import storage_adapter
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import revise_project_artifact

    adapter = storage_adapter()
    for artifact_id, colour_map in swaps.items():
        head = get_artifact(artifact_id)
        service.authorize(principal, head["project_id"], write=True)
        data, _ = observe(artifact_id, adapter)
        fixed = immune.snap_colours(data.decode("utf-8"), colour_map).encode()
        stored = adapter.put_bytes(tenant_id=principal.tenant_id, project_id=head["project_id"], data=fixed)
        from services.langgraph.persistence.projects import register_storage_object

        register_storage_object(tenant_id=principal.tenant_id, project_id=head["project_id"], stored=stored, mime_type="image/svg+xml")
        revised = revise_project_artifact(project_id=head["project_id"], artifact_id=artifact_id, actor=principal.user_id, adapter=adapter,
                                          expected_version=int(head["version"]), content_hash=stored.content_hash, storage_uri=stored.storage_uri,
                                          v2_patch={"remediation": {"kind": "SNAP_COLOUR", "swaps": colour_map, "previous_version": int(head["version"])}})
        applied.append({"kind": "SNAP_COLOUR", "artifact_id": artifact_id, "swaps": colour_map, "previous_version": int(head["version"]),
                        "new_version": int(revised["artifact"].version)})
    from services.langgraph.persistence.database import transaction

    with transaction(write=True) as conn:
        db.append_audit(conn, tenant_id=principal.tenant_id, chain_ref=brand_id, subject_type="immune", subject_id=report["scan_hash"][:24],
                        action="remediate", actor=principal.user_id, detail={"applied": applied, "refused": refused})
    return {"applied": applied, "refused": refused, "rescan": scan(principal, brand_id, scope=scope, scope_ref=scope_ref)["counts"]}


def _apply_provenance(principal: Principal, brand_id: str, fix: dict[str, Any]) -> dict[str, Any]:
    from services.langgraph.persistence.database import transaction

    with transaction(write=True) as conn:
        nodes, _ = db.load_graph(conn, brand_id, lock=True)
        current = [n for n in nodes if n["valid_to"] is None]
        asset = next((n for n in current if (n["attributes"] or {}).get("ref") == fix["artifact_id"]), None)
        gv = next((n for n in current if n["kind"] == NodeKind.GENOME_VERSION.value and (n["attributes"] or {}).get("ref") == fix["genome_version_id"]), None)
        if asset is None or gv is None:
            return {"kind": "LINK_PROVENANCE", "status": "REFUSED", "reason": "the recorded genome version is not in the graph"}
        edge = db.insert_edge(tenant_id=principal.tenant_id, brand_id=brand_id, kind=EdgeKind.DERIVED_FROM.value, src=asset["node_id"],
                              dst=gv["node_id"], provenance={"restored_from": "artifact provenance_ref"}, actor=principal.user_id, db=conn)
    return {"kind": "LINK_PROVENANCE", "status": "APPLIED", "edge_id": edge["edge_id"]}


__all__ = ["campaign_report", "compile_prompt", "create_prompt", "import_original", "list_prompts", "plan_campaign", "record_measurement",
           "regression", "remediate", "scan"]
