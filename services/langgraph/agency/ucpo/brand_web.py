"""Approved VNEXUS genome -> UCPO, without copying brand text into a second brief by hand.

VNEXUS remains the brand/approval authority. Project OS stores only derived,
versioned handoff and per-facet projections; UCPO owns source, jobs and release.
The handoff is revalidated against current approved layers and approval rows
before a build and whenever a bridged release proof is inspected. No deploy,
provider call, or approval decision occurs here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry import psem
from services.langgraph.agency.foundry.studio import observe
from services.langgraph.agency.project_os.storage import StorageAdapter
from services.langgraph.agency.vnexus import service as vnexus
from services.langgraph.agency.vnexus.genome import Scope
from services.langgraph.security.auth import Principal

from .brand_web_contracts import BrandWebsiteMapping
from .contracts import ImageAsset, PageBrief, SectionBrief, WebsiteBrief

HANDOFF_SCHEMA = "amc-ucpo-brand-handoff/v1"


def _name(site_id: str, facet: str) -> str:
    return f"uw-{canonical_hash({'site': site_id})[:16]}-{facet}"


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1) + "\n").encode()


def handoff_head(project_id: str, site_id: str, adapter: StorageAdapter) -> Optional[tuple[dict, dict]]:
    from services.langgraph.persistence.projects import project_artifact_id

    artifact_id = project_artifact_id(project_id, "foundry-" + _name(site_id, "binding"))
    try:
        data, head = observe(artifact_id, adapter)
    except LookupError:
        return None
    if head["project_id"] != project_id:
        raise ValueError("brand handoff is outside this project")
    if hashlib.sha256(data).hexdigest() != head["content_hash"]:
        raise ValueError("brand handoff content does not match its artifact head")
    body = json.loads(data)
    if body.get("schema_version") != HANDOFF_SCHEMA or body.get("project_id") != project_id or body.get("site_id") != site_id:
        raise ValueError("invalid stored brand handoff")
    return body, head


def _layer_approved(principal: Principal, layer: Any) -> dict:
    from services.langgraph.persistence.approvals import get_approval

    row = vnexus.get_version(principal, layer.version_id, settle=False)
    approval = get_approval(row.get("approval_id") or "")
    expected = (row["tenant_id"], row["project_id"], row["version_id"], str(row["version"]), row["content_hash"],
                vnexus.SUBJECT_GENOME, vnexus.APPROVAL_POLICY)
    actual = tuple((approval or {}).get(k) for k in ("tenant_id", "project_id", "subject_ref", "subject_version_ref",
                                                     "subject_hash", "subject_type", "policy_version"))
    if (row["status"] != "APPROVED" or actual != expected or (approval or {}).get("status") != "resolved"
            or (approval or {}).get("decision") != "approve" or not (approval or {}).get("reviewer")
            or approval["reviewer"] in {row["created_by"], row.get("submitted_by")}):
        raise ValueError("BRAND_APPROVAL_INVALID: an approved layer lacks its exact independent approval")
    return {k: row[k] for k in ("version_id", "version", "content_hash", "approval_id", "scope", "scope_ref")}


def current_brand(principal: Principal, project_id: str, brand_id: str) -> tuple[Any, list[dict]]:
    vnexus.authorize(principal, project_id)
    brand = vnexus.brand_for(principal, brand_id)
    if brand["owner_project_id"] != project_id:
        # A background job is scoped to one project and cannot safely replay a
        # caller's authority over another project's brand. Fail before copying.
        raise ValueError("CROSS_PROJECT_BRAND_BLOCKED: brand and site must share their owner project")
    resolution, layers = vnexus.resolve_scope(principal, brand_id, scope=Scope.PROJECT, scope_ref=project_id)
    if not layers or layers[0].scope is not Scope.BRAND or not resolution.authoritative:
        raise ValueError("BRAND_NOT_APPROVED: an approved brand layer is required")
    if resolution.conflicts or resolution.blocking:
        raise ValueError("BRAND_CONSTRAINTS_BLOCKED: resolved brand has conflicts or blocking findings")
    return resolution, [_layer_approved(principal, layer) for layer in layers]


def _text(values: dict, key: str, used: set[str]) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MISSING_APPROVED_COPY:{key}")
    used.add(key)
    return value


def _phrase_rules(values: dict, key: str, used: set[str]) -> tuple[str, ...]:
    value = values.get(key, [])
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"INVALID_BRAND_PHRASE_RULE:{key}")
    if key in values:
        used.add(key)
    return tuple(value)


def _accent(values: dict, used: set[str]) -> str:
    required = {"ink": psem.PALETTE["charcoal"], "paper": psem.PALETTE["paper"], "muted": psem.PALETTE["fog"]}
    required_keys = [f"visual.color.{role}" for role in (*required, "accent", "accent_2")]
    used.update(required_keys)
    if any(values.get(f"visual.color.{role}") != expected for role, expected in required.items()):
        raise ValueError("UNSUPPORTED_BRAND_PALETTE: UCPO supports the locked PSEM grounds and muted colour only")
    primary, secondary = values.get("visual.color.accent"), values.get("visual.color.accent_2")
    if (not isinstance(primary, str) or not isinstance(secondary, str)
            or {primary, secondary} != {psem.PALETTE[name] for name in psem.ACCENTS}):
        raise ValueError("UNSUPPORTED_BRAND_PALETTE: both PSEM accents must be supplied")
    return next(name for name in psem.ACCENTS if psem.PALETTE[name] == primary)


def map_brief(values: dict, mapping: BrandWebsiteMapping) -> tuple[WebsiteBrief, str, list[str]]:
    used: set[str] = set()
    get = lambda key: _text(values, key, used)  # noqa: E731 - records every mapped key
    primary = _accent(values, used)
    pages = []
    for page in mapping.pages:
        sections = tuple(SectionBrief(kind=s.kind, heading=get(s.heading_key), body=get(s.body_key) if s.body_key else "",
                                      label=get(s.label_key) if s.label_key else "", cta=s.cta, anchor=s.anchor, image=s.image)
                         for s in page.sections)
        pages.append(PageBrief(slug=page.slug, title=get(page.title_key), description=get(page.description_key), sections=sections))
    images = tuple(ImageAsset(asset_id=i.asset_id, alt=get(i.alt_key), motif_seed=i.motif_seed) for i in mapping.images)
    brief = WebsiteBrief(organization=get(mapping.organization_key), tagline=get(mapping.tagline_key),
                         offering=get(mapping.offering_key), audience=get(mapping.audience_key), locale=mapping.locale,
                         cta_label=get(mapping.cta_label_key), cta_target=mapping.cta_target, pages=tuple(pages), images=images,
                         required_phrases=_phrase_rules(values, "verbal.content_rules.required_phrases", used),
                         forbidden_phrases=_phrase_rules(values, "verbal.content_rules.forbidden_phrases", used), seed=mapping.seed)
    return brief, primary, sorted(used)


def _put(principal: Principal, project_id: str, site_id: str, facet: str, body: dict, adapter: StorageAdapter) -> dict:
    from services.langgraph.agency.ucpo import service

    role, kind = ("design_lead", "design_system_spec") if facet == "visual" else ("product_manager", "product_spec")
    return service._put(principal, project_id, site_id, f"brand_{facet}", _dump(body), adapter=adapter,
                        spec=(role, kind, "application/json"), name=_name(site_id, facet))


def compile_from_brand(principal: Principal, project_id: str, site_id: str, brand_id: str, mapping: BrandWebsiteMapping,
                       *, adapter: StorageAdapter, export_root: Path) -> dict:
    """Join Project OS heads, edges, handoff and queued build in one transaction."""
    from services.langgraph.agency.ucpo import service
    from services.langgraph.persistence.database import atomic_transaction

    with atomic_transaction() as db:
        service.lock_site(db, principal.tenant_id, project_id, site_id)
        return _compile_from_brand(principal, project_id, site_id, brand_id, mapping, adapter=adapter, export_root=export_root)


def _compile_from_brand(principal: Principal, project_id: str, site_id: str, brand_id: str, mapping: BrandWebsiteMapping,
                        *, adapter: StorageAdapter, export_root: Path) -> dict:
    from services.langgraph.agency.ucpo import service
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import project_artifact_id

    vnexus.authorize(principal, project_id, write=True)
    service._check_site_id(site_id)
    resolution, layers = current_brand(principal, project_id, brand_id)
    brief, primary, used = map_brief(resolution.values, mapping)  # validation before any mutation
    prior = handoff_head(project_id, site_id, adapter)
    legacy = project_artifact_id(project_id, "foundry-" + service._name(site_id, "brief"))
    if prior is None and get_artifact(legacy) is not None:
        raise ValueError("SITE_ALREADY_EXISTS: choose a new site id for a brand-bound site")
    if prior and prior[0]["brand_id"] != brand_id:
        raise ValueError("BRAND_BINDING_IMMUTABLE: choose a new site id for another brand")
    binding_body = {"schema_version": HANDOFF_SCHEMA, "project_id": project_id, "site_id": site_id, "brand_id": brand_id,
                    "resolution_hash": resolution.resolution_hash, "layers": layers, "mapping": mapping.model_dump(mode="json"),
                    "keys_used": used}
    binding = _put(principal, project_id, site_id, "binding", binding_body, adapter)
    text = _put(principal, project_id, site_id, "copy", brief.model_dump(mode="json"), adapter)
    visual = _put(principal, project_id, site_id, "visual", {
        "organization": brief.organization, "offering": brief.offering, "audience": brief.audience,
        "primary_accent": primary, "palette": {k: resolution.values[k] for k in used if k.startswith("visual.color.")},
        "seed": brief.seed}, adapter)
    site = service.compile_site_line(principal, project_id, site_id, brief, adapter=adapter, export_root=export_root,
                                     brand_inputs={"binding": binding, "copy": text, "visual": visual, "primary": primary})
    return {"site": site, "brand": {"brand_id": brand_id, "resolution_hash": resolution.resolution_hash, "layers": layers,
                                     "keys_used": used, "unmapped_keys": sorted(set(resolution.values) - set(used)),
                                     "primary_accent": primary},
            "handoff": {"artifact_id": binding["artifact_id"], "version": binding["version"],
                        "content_hash": binding["content_hash"]}, "external_effects": "none"}


def freshness(principal: Principal, project_id: str, site_id: str, adapter: StorageAdapter,
              *, expected_ref: Optional[str] = None) -> list[str]:
    try:
        pair = handoff_head(project_id, site_id, adapter)
        if pair is None:
            return ["BRAND_HANDOFF_MISSING"] if expected_ref else []
        body, head = pair
        ref = f"artifact:{head['artifact_id']}@v{head['version']}"
        if expected_ref and expected_ref != ref:
            return ["BRAND_HANDOFF_STALE: handoff head changed"]
        if head.get("status") in {"invalidated", "review_required"}:
            return ["BRAND_HANDOFF_STALE: handoff invalidated"]
        resolution, layers = current_brand(principal, project_id, body["brand_id"])
        if layers != body["layers"] or resolution.resolution_hash != body["resolution_hash"]:
            return ["BRAND_HANDOFF_STALE: approved brand layers changed"]
        return []
    except (LookupError, ValueError, PermissionError, OSError, RuntimeError, KeyError, TypeError) as exc:
        return [f"BRAND_HANDOFF_BLOCKED:{type(exc).__name__}"]


def proof_freshness(head: dict, *, approval_id: Optional[str] = None) -> list[str]:
    """Re-evaluate a UCPO proof even when reached through the generic vault.

    A caller's ``verification_passed=True`` is not proof. Reopen the actual
    source, build, QA and coverage, verify their scoped heads and hashes, then
    bind the proof to the fenced UCPO job receipt and recompute coverage and
    gates. This is a read-only verdict, not deployment authority; an eventual
    external release must recheck at its own boundary.
    """
    from services.langgraph.agency.exporter import resolve_export_root
    from services.langgraph.agency.foundry.contracts import CreativeGenome
    from services.langgraph.agency.project_os.storage import resolve_storage_adapter
    from services.langgraph.persistence import durable_runs
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import project_artifact_id
    from .contracts import (BrowserVerification, BuildResult, ReleaseProof, RequirementsPackage,
                            SemanticCoverageReport, SiteArchitecture, WebsiteBrief, WebsiteIR)
    from .release import parse_ref, seal_proof, stale_reasons
    from .semantic import evaluate
    from .service import KIND, STAGES, _check_site_id, export_digest, site_job_id
    from .source import unpack_tree

    try:
        adapter = resolve_storage_adapter(resolve_export_root())
        raw = adapter.get_bytes(head["content_location"])
        if hashlib.sha256(raw).hexdigest() != head["content_hash"]:
            return ["PROOF_BYTES_MISMATCH"]
        proof = ReleaseProof.model_validate_json(raw)
        project, tenant = head["project_id"], head["tenant_id"]
        _check_site_id(proof.site_id)
        canonical_proof = project_artifact_id(project, f"foundry-ucpo-{proof.site_id}-release_proof")
        if proof.project_ref != project:
            return ["PROOF_SCOPE_MISMATCH"]
        if head.get("artifact_id") != canonical_proof or head.get("subtype") != "ucpo.release_proof":
            return ["PROOF_OWNER_MISMATCH"]
        binding = handoff_head(project, proof.site_id, adapter)
        if binding and "brand_handoff" not in proof.artifact_refs:
            return ["BRAND_HANDOFF_MISSING_FROM_PROOF"]
        reasons = stale_reasons(proof, get_artifact)
        required = {"brief", "requirements", "genome", "tokens", "site_ir", "source", "build", "browser_qa", "coverage"}
        if not required.issubset(proof.artifact_refs):
            reasons.append("PROOF_INCOMPLETE: required artifact references missing")
        if not proof.eligible_for_approval or proof.reasons:
            reasons.append("PROOF_NOT_ELIGIBLE")
        if reasons:
            return reasons
        data: dict[str, bytes] = {}
        heads: dict[str, dict] = {}
        facets = {"brand_handoff": "binding", "brand_copy": "copy", "brand_visual": "visual"}
        for stage, ref in proof.artifact_refs.items():
            artifact_id, _ = parse_ref(ref)
            item = get_artifact(artifact_id)
            if item is None or (item["tenant_id"], item["project_id"]) != (tenant, project):
                return [f"PROOF_SCOPE_MISMATCH:{stage}"]
            if stage in facets:
                facet = facets[stage]
                owner_id = project_artifact_id(project, "foundry-" + _name(proof.site_id, facet))
                subtype = f"ucpo.brand_{facet}"
            elif stage in STAGES or stage.startswith("image-"):
                owner_id = project_artifact_id(project, f"foundry-ucpo-{proof.site_id}-{stage}")
                subtype = f"ucpo.{stage}"
            else:
                return [f"PROOF_UNKNOWN_STAGE:{stage}"]
            if artifact_id != owner_id or item.get("subtype") != subtype:
                return [f"PROOF_OWNER_MISMATCH:{stage}"]
            heads[stage] = item
            data[stage] = adapter.get_bytes(item["content_location"])
            if hashlib.sha256(data[stage]).hexdigest() != item["content_hash"]:
                return [f"PROOF_BYTES_MISMATCH:{stage}"]

        # Generic Project OS artifacts and client-provided verification flags
        # are not build attestations. A proof must be the exact result of the
        # server's fenced UCPO job for these current inputs and brand handoff.
        handoff_hash = binding[1]["content_hash"] if binding else None
        job_id = site_job_id(project, proof.site_id, heads["source"]["content_hash"], handoff_hash)
        job = durable_runs.get_job(job_id)
        if job is None or (job.get("tenant_id"), job.get("project_id"), job.get("kind")) != (tenant, project, KIND):
            return ["PROOF_JOB_MISSING_OR_SCOPE_MISMATCH"]
        envelope = job.get("spec")
        spec = envelope.get("ucpo") if isinstance(envelope, dict) else None
        receipt = job.get("result")
        if not isinstance(spec, dict) or not isinstance(spec.get("revisions"), dict):
            return ["PROOF_JOB_INPUT_MISMATCH"]
        if not isinstance(receipt, dict):
            return ["PROOF_JOB_RECEIPT_MISMATCH"]
        source_head = heads["source"]
        expected_source = {"artifact_id": source_head["artifact_id"], "version": int(source_head["version"]),
                           "content_hash": source_head["content_hash"]}
        inputs = {k: v for k, v in proof.artifact_refs.items() if k not in {"build", "browser_qa", "coverage"}}
        base_revisions = {"brief", "requirements", "genome", "tokens", "site_ir", "source"}
        if (canonical_hash(spec) != job.get("spec_hash") or set(spec["revisions"]) != base_revisions
                or spec.get("site_id") != proof.site_id or spec.get("source") != expected_source
                or spec.get("artifact_refs") != inputs
                or any(proof.revisions.get(k) != v for k, v in spec["revisions"].items())):
            return ["PROOF_JOB_INPUT_MISMATCH"]
        expected_proof = {"artifact_id": head["artifact_id"], "version": int(head["version"]), "content_hash": head["content_hash"]}
        if (receipt.get("proof_artifact") != expected_proof or receipt.get("eligible_for_approval") is not True
                or receipt.get("build_status") != "PASSED" or receipt.get("browser_qa_status") != "PASSED"
                or not isinstance(receipt.get("approval"), dict) or not receipt["approval"].get("approval_id")):
            return ["PROOF_JOB_RECEIPT_MISMATCH"]
        if approval_id is not None and receipt["approval"]["approval_id"] != approval_id:
            return ["PROOF_APPROVAL_ORIGIN_MISMATCH"]
        brief = WebsiteBrief.model_validate_json(data["brief"])
        pkg = RequirementsPackage.model_validate_json(data["requirements"])
        genome = CreativeGenome.model_validate_json(data["genome"])
        tokens = json.loads(data["tokens"])
        site_ir = json.loads(data["site_ir"])
        arch, ir = SiteArchitecture.model_validate(site_ir["architecture"]), WebsiteIR.model_validate(site_ir["ir"])
        files, manifest = unpack_tree(data["source"])
        record = json.loads(data["build"])
        build = BuildResult.model_validate(record["build"])
        qa = BrowserVerification.model_validate_json(data["browser_qa"])
        coverage = SemanticCoverageReport.model_validate_json(data["coverage"])
        expected = {"brief": brief.content_hash, "requirements": pkg.content_hash, "genome": genome.content_hash,
                    "tokens": tokens["source_hash"], "site_ir": ir.content_hash, "source": manifest.tree_hash,
                    "build": build.output_hash or build.status, "browser_qa": qa.content_hash, "coverage": coverage.content_hash}
        if any(proof.revisions.get(k) != v for k, v in expected.items()):
            return ["PROOF_REVISION_MISMATCH"]
        if (pkg.project_ref != project or pkg.brief_hash != brief.content_hash or ir.project_ref != project
                or ir.requirements_ref != pkg.content_hash or ir.site_architecture_ref != arch.content_hash
                or ir.genome_ref != genome.content_hash or ir.token_refs.get("dtcg_source_hash") != tokens["source_hash"]
                or manifest.website_ir_ref != ir.content_hash):
            return ["PROOF_LINEAGE_MISMATCH"]
        if (build.source_tree_hash != manifest.tree_hash or build.output_hash != export_digest(record["export"])
                or qa.build_output_hash != build.output_hash or not qa.checks
                or any(check.result != "PASS" for check in qa.checks)):
            return ["PROOF_BUILD_OR_QA_MISMATCH"]
        inputs = {k: v for k, v in proof.artifact_refs.items() if k != "coverage"}
        recomputed, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=qa, artifacts=inputs)
        if recomputed != coverage:
            return ["PROOF_COVERAGE_MISMATCH"]
        resealed = seal_proof(project_ref=project, site_id=proof.site_id, revisions=proof.revisions,
                              artifact_refs=proof.artifact_refs, build=build, qa=qa, coverage=coverage)
        if (resealed.gates, resealed.eligible_for_approval, resealed.reasons) != (proof.gates, proof.eligible_for_approval, proof.reasons):
            return ["PROOF_GATE_MISMATCH"]
        ref = proof.artifact_refs.get("brand_handoff")
        if ref:
            principal = Principal("system:brand-freshness", tenant, "operator", frozenset({project}))
            return freshness(principal, project, proof.site_id, adapter, expected_ref=ref)
        return []
    except (LookupError, ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        return [f"PROOF_RECHECK_BLOCKED:{type(exc).__name__}"]
