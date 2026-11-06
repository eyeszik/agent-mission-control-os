"""The website production line over existing owners: Project OS artifacts, durable jobs, approvals.

``compile_site_line`` runs the deterministic stages (requirements, PSEM genome, tokens,
plates, site IR, source) and stores each as a Project OS artifact with ``depends_on`` edges,
through the Foundry ``studio.store`` (create / revise / reuse-unchanged). Each stage is
checked against its N3 role with ``assert_role_may_produce`` before it is stored. A changed
brief revises only what changed; the existing dependency propagation invalidates everything
downstream, and approvals bound to those artifacts go stale through the existing path.

The untrusted part -- building and browsing the generated source -- is a durable job
(``ucpo_site_build``) driven by explicit ``run_tick`` calls (no worker is deployed). Its
handler builds and verifies inside the sandbox, stores the evidence, computes semantic
coverage and seals a ``ReleaseProof``. Only an eligible proof gets an approval request;
approval never deploys anything.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry import psem
from services.langgraph.agency.foundry.contracts import CreativeGenome
from services.langgraph.agency.foundry.studio import observe, store
from services.langgraph.agency.kernel.roles import assert_role_may_produce
from services.langgraph.agency.project_os.storage import StorageAdapter, resolve_storage_adapter
from services.langgraph.security.auth import Principal

from . import build as build_mod
from . import qa as qa_mod
from .contracts import (
    BrowserVerification,
    BuildResult,
    ReleaseProof,
    RequirementsPackage,
    SemanticCoverageReport,
    SiteArchitecture,
    WebsiteBrief,
    WebsiteIR,
)
from .release import seal_proof, stale_reasons
from .requirements import compile_requirements
from .semantic import IntentLinker, evaluate
from .site import compile_site
from .source import DEPENDENCIES, DEV_DEPENDENCIES, generate_source, pack_tree, unpack_tree

KIND = "ucpo_site_build"
RUN_PIPELINE = "ucpo_site_release"
APPROVAL_POLICY = "amc-ucpo-release/v1"
# Stage -> (N3 role, N1 artifact type, mime). Checked with assert_role_may_produce before every store.
STAGES: dict[str, tuple[str, str, str]] = {
    "brief": ("product_manager", "product_spec", "application/json"),
    "requirements": ("product_manager", "product_spec", "application/json"),
    "genome": ("design_lead", "design_system_spec", "application/json"),
    "tokens": ("design_lead", "design_token_set", "application/json"),
    "site_ir": ("design_lead", "website_lockup_spec", "application/json"),
    "source": ("implementation_lead", "app_build_spec", "application/json"),
    "build": ("implementation_lead", "app_build_spec", "application/json"),
    "browser_qa": ("brand_safety_reviewer", "qa_report", "application/json"),
    "coverage": ("brand_safety_reviewer", "qa_report", "application/json"),
    "release_proof": ("release_manager", "release_record", "application/json"),
}
IMAGE_STAGE = ("creative_director", "media_asset", "image/svg+xml")
SITE_ID = r"^[a-z0-9][a-z0-9-]{0,39}$"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dump(obj: Any) -> bytes:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return (json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode()


def _name(site_id: str, stage: str) -> str:
    return f"ucpo-{site_id}-{stage}"


def _ref(entry: dict) -> str:
    return f"artifact:{entry['artifact_id']}@v{entry['version']}"


def _check_site_id(site_id: str) -> None:
    import re

    if not re.fullmatch(SITE_ID, site_id):
        raise ValueError("site_id must be a lowercase slug of at most 40 characters")


def _put(principal: Principal, project_id: str, site_id: str, stage: str, data: bytes, *, adapter: StorageAdapter,
         depends_on: tuple[str, ...] = (), spec: Optional[tuple[str, str, str]] = None, name: Optional[str] = None) -> dict:
    """Store one stage through the Foundry store, after the N3 role check. Re-confirms unchanged-but-invalidated heads."""
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import revise_project_artifact

    role, artifact_type, mime = spec or STAGES[stage]
    assert_role_may_produce(role, artifact_type)
    entry = store(principal, project_id, name or _name(site_id, stage), data, mime=mime, artifact_type=artifact_type,
                  subtype=f"ucpo.{stage}", adapter=adapter, depends_on=depends_on,
                  v2={"ucpo_stage": stage, "ucpo_site": site_id, "produced_by_role": role})
    head = get_artifact(entry["artifact_id"])
    if entry["action"] == "reused_unchanged" and head and head.get("status") in {"invalidated", "review_required"}:
        # Same bytes under changed upstream inputs: record that it was re-derived, so lineage is current again.
        revised = revise_project_artifact(project_id=project_id, artifact_id=entry["artifact_id"], actor=principal.user_id,
                                          adapter=adapter, expected_version=int(head["version"]),
                                          content_hash=head["content_hash"], storage_uri=head["content_location"],
                                          v2_patch={"ucpo_reconfirmed": True})
        entry = {**entry, "version": int(revised["artifact"].version), "action": "reconfirmed"}
    return {**entry, "stage": stage, "role": role, "artifact_type": artifact_type}


def _read(entry_or_id: Any, adapter: StorageAdapter) -> tuple[bytes, dict]:
    artifact_id = entry_or_id if isinstance(entry_or_id, str) else entry_or_id["artifact_id"]
    return observe(artifact_id, adapter)


def site_job_id(project_id: str, site_id: str, source_hash: str) -> str:
    return "ucpo-" + canonical_hash({"project": project_id, "site": site_id, "source": source_hash})[:40]


# ------------------------------------------------------------------------------ compile (trusted, deterministic)


def compile_site_line(principal: Principal, project_id: str, site_id: str, brief: WebsiteBrief, *,
                      adapter: StorageAdapter, export_root: Path) -> dict:
    """Run the deterministic stages, persist them, and enqueue the sandboxed build. Never executes generated code."""
    from services.langgraph.persistence import durable_runs
    from services.langgraph.persistence.database import atomic_transaction
    from services.langgraph.persistence.events import record_event
    from services.langgraph.persistence.runs import create_run_record, get_run_record

    _check_site_id(site_id)
    stages: dict[str, dict] = {}
    stages["brief"] = _put(principal, project_id, site_id, "brief", _dump(brief), adapter=adapter)
    pkg = compile_requirements(brief, project_ref=project_id)
    stages["requirements"] = _put(principal, project_id, site_id, "requirements", _dump(pkg), adapter=adapter,
                                  depends_on=(stages["brief"]["artifact_id"],))
    genome = psem.compile_psem_genome(psem.psem_brief(brief.organization, offering=brief.offering,
                                                      target_audience=brief.audience, seed=brief.seed), project_id=project_id)
    stages["genome"] = _put(principal, project_id, site_id, "genome", _dump(genome), adapter=adapter,
                            depends_on=(stages["brief"]["artifact_id"],))
    token_doc, token_css, token_hash = psem.compile_psem_tokens(genome)
    stages["tokens"] = _put(principal, project_id, site_id, "tokens", _dump({"dtcg": token_doc, "css": token_css,
                                                                             "source_hash": token_hash}),
                            adapter=adapter, depends_on=(stages["genome"]["artifact_id"],))
    images = []
    for image in brief.images:
        svg = psem.plate(genome, title=image.alt, motif_seed=image.motif_seed).encode()
        images.append(_put(principal, project_id, site_id, f"image-{image.asset_id}", svg, adapter=adapter,
                           depends_on=(stages["genome"]["artifact_id"],), spec=IMAGE_STAGE))
    arch, ir = compile_site(brief, pkg, genome, token_refs={"dtcg_source_hash": token_hash})
    stages["site_ir"] = _put(principal, project_id, site_id, "site_ir", _dump({"architecture": arch.model_dump(mode="json"),
                                                                              "ir": ir.model_dump(mode="json")}),
                             adapter=adapter, depends_on=(stages["requirements"]["artifact_id"], stages["tokens"]["artifact_id"]))
    files, manifest = generate_source(ir, genome, token_css)
    stages["source"] = _put(principal, project_id, site_id, "source", pack_tree(files, manifest), adapter=adapter,
                            depends_on=(stages["site_ir"]["artifact_id"], *(i["artifact_id"] for i in images)))
    report, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest)

    refs = {k: _ref(v) for k, v in stages.items()} | {i["stage"]: _ref(i) for i in images}
    job_spec = {"ucpo": {"site_id": site_id, "routes": [p.route for p in ir.pages], "artifact_refs": refs,
                         "source": {k: stages["source"][k] for k in ("artifact_id", "version", "content_hash")},
                         "revisions": {"brief": brief.content_hash, "requirements": pkg.content_hash,
                                       "genome": genome.content_hash, "tokens": token_hash, "site_ir": ir.content_hash,
                                       "source": manifest.tree_hash}},
                "export_root": str(export_root)}
    spec_hash = canonical_hash(job_spec["ucpo"])
    job_id = site_job_id(project_id, site_id, stages["source"]["content_hash"])
    with atomic_transaction():
        job = durable_runs.create_job(tenant_id=principal.tenant_id, project_id=project_id, kind=KIND, spec=job_spec,
                                      spec_hash=spec_hash, requested_by=principal.user_id, due_at=_now(), job_id=job_id)
        if get_run_record(job_id) is None:
            create_run_record(job_id, principal.tenant_id, project_id, KIND, "queued",
                              {"initiated_by": principal.user_id, "site_id": site_id, "spec_hash": spec_hash},
                              enforce_limits=True)
            record_event(job_id, principal.tenant_id, project_id, "ucpo", "UCPO_BUILD_QUEUED",
                         {"site_id": site_id, "source_tree": manifest.tree_hash})
    return {"site_id": site_id, "job_id": job["job_id"], "job_state": job["state"],
            "stages": {k: {f: v[f] for f in ("artifact_id", "version", "action", "role", "artifact_type", "invalidated")}
                       for k, v in [*stages.items(), *((i["stage"], i) for i in images)]},
            "compile_coverage": {"coverage": report.coverage, "mandatory_resolved": report.mandatory_resolved,
                                 "mandatory_applicable": report.mandatory_applicable,
                                 "unresolved_until_rendered": sum(1 for e in report.entries if e.status == "UNRESOLVED")},
            "requirements": len(pkg.requirements), "source_files": len(files), "source_tree": manifest.tree_hash,
            "external_effects": "none"}


# ------------------------------------------------------------------------------ durable build handler (untrusted execution)


def _spec(job: dict) -> dict:
    spec = job["spec"]["ucpo"]
    if canonical_hash(spec) != job["spec_hash"]:
        raise ValueError("UCPO_SPEC_HASH_MISMATCH")
    return spec


def _adapter(job: dict) -> StorageAdapter:
    return resolve_storage_adapter(Path(job["spec"]["export_root"]))


def _export_bundle(out_dir: Path) -> dict[str, str]:
    return {f.relative_to(out_dir).as_posix(): base64.b64encode(f.read_bytes()).decode()
            for f in sorted(p for p in out_dir.rglob("*") if p.is_file())}


def export_digest(bundle: dict[str, str]) -> str:
    import hashlib

    return canonical_hash(sorted((p, hashlib.sha256(base64.b64decode(b)).hexdigest()) for p, b in bundle.items()))


class SiteBuildHandler:
    operation = "ucpo.site.build_and_verify"
    contract_version = "amc-ucpo-build/v1"
    retry_class = "RETRY_SAFE"  # a static build has no external effect; a lost run is safely redone

    def target(self, job: dict) -> str:
        return "ucpo-" + _spec(job)["site_id"]

    def input_hash(self, job: dict) -> str:
        return job["spec_hash"]

    def environment_fingerprint(self, job: dict) -> str:
        return canonical_hash({"deps": build_mod.installed_versions(sorted({**DEPENDENCIES, **DEV_DEPENDENCIES})),
                               "runner": qa_mod.RUNNER.name})

    def precheck(self, job: dict):
        from services.langgraph.persistence.agency_kernel import get_artifact
        from services.langgraph.persistence.projects import get_project_workspace

        workspace = get_project_workspace(job["project_id"])
        if not workspace or workspace.tenant_id != job["tenant_id"] or workspace.lifecycle_state.value == "ARCHIVED":
            return RunState.BLOCKED_AUTHORITY, ["PROJECT_NOT_ADMISSIBLE"]
        src = _spec(job)["source"]
        head = get_artifact(src["artifact_id"])
        if head is None or (int(head["version"]), head["content_hash"]) != (src["version"], src["content_hash"]):
            return RunState.BLOCKED_ENVIRONMENT, ["SOURCE_SUPERSEDED: a newer source revision exists; build that instead"]
        return None, []

    def pre_image(self, job: dict) -> dict:
        return {"source": _spec(job)["source"]}

    def dispatch(self, job: dict) -> dict:
        spec = _spec(job)
        adapter = _adapter(job)
        data, head = _read(spec["source"]["artifact_id"], adapter)
        import hashlib

        if hashlib.sha256(data).hexdigest() != spec["source"]["content_hash"]:
            raise ValueError("SOURCE_READBACK_MISMATCH")
        files, manifest = unpack_tree(data)
        result, out_dir = build_mod.build_site(files, manifest, routes=spec["routes"], keep_output=True)
        if result.status == "BLOCKED_ISOLATION":
            return {"blocked_state": RunState.BLOCKED_ENVIRONMENT.value,
                    "reasons": ["BLOCKED_ISOLATION: " + "; ".join(result.isolation.get("reasons") or [])[:300]]}
        verification: Optional[BrowserVerification] = None
        bundle: dict[str, str] = {}
        try:
            if out_dir is not None:
                verification = qa_mod.verify_build(out_dir, routes=spec["routes"], expected_output_hash=result.output_hash or "")
                bundle = _export_bundle(out_dir)
        finally:
            if out_dir is not None:
                build_mod.cleanup(out_dir.parent.parent)
        record = {"build": result.model_dump(mode="json"),
                  "browser_qa": verification.model_dump(mode="json") if verification else None, "export": bundle}
        stored = adapter.put_bytes(tenant_id=job["tenant_id"], project_id=job["project_id"], data=_dump(record))
        return {"storage_uri": stored.storage_uri, "content_hash": stored.content_hash, "route": "sandbox:unshare-rmn"}

    def observe(self, job: dict, dispatched: dict) -> dict:
        import hashlib

        data = _adapter(job).get_bytes(dispatched["storage_uri"])
        if hashlib.sha256(data).hexdigest() != dispatched["content_hash"]:
            raise ValueError("EVIDENCE_READBACK_MISMATCH")
        return {**dispatched, "bytes": len(data)}

    def verify(self, job: dict, observation: dict) -> dict:
        """Integrity of the evidence (not the site's verdict, which coverage and the proof carry)."""
        record = json.loads(_adapter(job).get_bytes(observation["storage_uri"]))
        build = BuildResult.model_validate(record["build"])
        findings = []
        if build.source_tree_hash != _spec(job)["revisions"]["source"]:
            findings.append("build is not of this source tree")
        if build.status == "PASSED" and export_digest(record["export"]) != build.output_hash:
            findings.append("stored export does not match the build output hash")
        if record["browser_qa"] and BrowserVerification.model_validate(record["browser_qa"]).build_output_hash != build.output_hash:
            findings.append("browser verification is of a different build output")
        return {"status": "FAILED" if findings else "PASSED", "findings": findings}

    def reconcile(self, job: dict, intent: dict):
        return "REDO", None

    def on_commit(self, job: dict, observation: dict, verification: dict):
        from services.langgraph.persistence import durable_runs
        from services.langgraph.persistence.database import atomic_transaction, json_param, table
        from services.langgraph.persistence.events import record_event
        from services.langgraph.persistence.runs import update_run_status

        spec = _spec(job)
        adapter = _adapter(job)
        principal = _requester(job)
        record = json.loads(adapter.get_bytes(observation["storage_uri"]))
        build = BuildResult.model_validate(record["build"])
        qa = BrowserVerification.model_validate(record["browser_qa"]) if record["browser_qa"] else None
        loaded = load_stages(job["project_id"], spec["site_id"], adapter)
        site_id, project = spec["site_id"], job["project_id"]
        with atomic_transaction() as db:
            durable_runs._active_fence(db, job_id=job["job_id"], fencing_token=job["lease_token"], now=_now())
            src_id = spec["source"]["artifact_id"]
            b = _put(principal, project, site_id, "build", _dump(record), adapter=adapter, depends_on=(src_id,))
            q = _put(principal, project, site_id, "browser_qa", _dump(qa or {"status": "NOT_RUN", "reason": build.status}),
                     adapter=adapter, depends_on=(b["artifact_id"],))
            refs = dict(spec["artifact_refs"]) | {"build": _ref(b), "browser_qa": _ref(q)}
            report, _ = evaluate(loaded["requirements"], arch=loaded["architecture"], ir=loaded["ir"], files=loaded["files"],
                                 manifest=loaded["manifest"], verification=qa, artifacts=refs)
            c = _put(principal, project, site_id, "coverage", _dump(report), adapter=adapter,
                     depends_on=(q["artifact_id"], loaded["entries"]["requirements"]["artifact_id"]))
            refs["coverage"] = _ref(c)
            revisions = dict(spec["revisions"]) | {"build": build.output_hash or build.status,
                                                   "browser_qa": qa.content_hash if qa else "NOT_RUN",
                                                   "coverage": report.content_hash}
            proof = seal_proof(project_ref=project, site_id=site_id, revisions=revisions, artifact_refs=refs, build=build,
                               qa=qa, coverage=report)
            p = _put(principal, project, site_id, "release_proof", _dump(proof), adapter=adapter, depends_on=(c["artifact_id"],))
            approval = None
            if proof.eligible_for_approval:
                from services.langgraph.agency.intake.release import open_artifact_approval

                approval = open_artifact_approval(
                    principal, tenant_id=job["tenant_id"], project_id=project, mission_id=f"{project}:ucpo:{site_id}",
                    contract_hash=canonical_hash({"proof": p["artifact_id"], "policy": APPROVAL_POLICY}),
                    artifact_id=p["artifact_id"], version=p["version"], content_hash=p["content_hash"],
                    run_pipeline=RUN_PIPELINE, policy_version=APPROVAL_POLICY, subject_type="WEBSITE_RELEASE_PROOF",
                    reason="Generated website passed automated verification; human visual, brand, copy and accessibility "
                           "review is required. Approval does not deploy.",
                    metadata={"site_id": site_id, "deployment": "NOT_AUTHORIZED"})
            result = {"site_id": site_id, "build_status": build.status, "browser_qa_status": qa.status if qa else "NOT_RUN",
                      "coverage": report.coverage, "release_blocked": report.release_blocked,
                      "proof_artifact": {k: p[k] for k in ("artifact_id", "version", "content_hash")},
                      "eligible_for_approval": proof.eligible_for_approval, "reasons": list(proof.reasons),
                      "approval": {k: approval[k] for k in ("approval_id", "run_id", "status")} if approval else None}
            db.execute(f"UPDATE {table('durable_jobs')} SET result = ? WHERE job_id = ? AND lease_token = ?",
                       (json_param(result), job["job_id"], job["lease_token"]))
        update_run_status(job["job_id"], "needs_approval" if approval else "blocked")
        record_event(job["job_id"], job["tenant_id"], project, "ucpo", "UCPO_VERIFIED" if approval else "UCPO_RELEASE_BLOCKED",
                     {"site_id": site_id, "build": build.status, "browser_qa": result["browser_qa_status"],
                      "coverage": report.coverage, "reasons": list(proof.reasons)[:10]})
        return (RunState.WAITING_APPROVAL if approval else RunState.DORMANT), result


def _requester(job: dict) -> Principal:
    # The recorded requester of this job, scoped to its project; not an authority supplied by a worker.
    return Principal(user_id=job["requested_by"], tenant_id=job["tenant_id"], role="operator",
                     allowed_project_ids=frozenset({job["project_id"]}))


def run_build_tick(job_id: str, *, worker_id: str = "ucpo-local-driver"):
    from services.langgraph.agency.durable.ticks import run_tick

    return run_tick(worker_id=worker_id, handlers={KIND: SiteBuildHandler()}, job_id=job_id)


# ------------------------------------------------------------------------------ read models


def load_stages(project_id: str, site_id: str, adapter: StorageAdapter) -> dict[str, Any]:
    """Current heads of a site's stages, parsed. Raises LookupError when the site was never compiled here."""
    from services.langgraph.persistence.projects import project_artifact_id

    _check_site_id(site_id)
    entries: dict[str, dict] = {}
    raw: dict[str, bytes] = {}
    for stage in STAGES:
        artifact_id = project_artifact_id(project_id, f"foundry-{_name(site_id, stage)}")
        try:
            data, head = _read(artifact_id, adapter)
        except LookupError:
            continue
        if head["project_id"] != project_id:
            raise LookupError("site not in this project")
        entries[stage] = {"artifact_id": artifact_id, "version": int(head["version"]), "content_hash": head["content_hash"],
                          "status": head.get("status")}
        raw[stage] = data
    if "brief" not in entries:
        raise LookupError(f"site {site_id} not found")
    out: dict[str, Any] = {"entries": entries}
    out["brief"] = WebsiteBrief.model_validate_json(raw["brief"])
    out["requirements"] = RequirementsPackage.model_validate_json(raw["requirements"]) if "requirements" in raw else None
    site_ir = json.loads(raw["site_ir"]) if "site_ir" in raw else None
    out["architecture"] = SiteArchitecture.model_validate(site_ir["architecture"]) if site_ir else None
    out["ir"] = WebsiteIR.model_validate(site_ir["ir"]) if site_ir else None
    out["files"], out["manifest"] = unpack_tree(raw["source"]) if "source" in raw else (None, None)
    out["genome"] = CreativeGenome.model_validate_json(raw["genome"]) if "genome" in raw else None
    build_record = json.loads(raw["build"]) if "build" in raw else None
    out["build"] = BuildResult.model_validate(build_record["build"]) if build_record else None
    out["export"] = build_record["export"] if build_record else None
    qa = json.loads(raw["browser_qa"]) if "browser_qa" in raw else None
    out["browser_qa"] = BrowserVerification.model_validate(qa) if qa and "schema_version" in qa else None
    out["coverage"] = SemanticCoverageReport.model_validate_json(raw["coverage"]) if "coverage" in raw else None
    out["proof"] = ReleaseProof.model_validate_json(raw["release_proof"]) if "release_proof" in raw else None
    return out


def inspect_site(principal: Principal, project_id: str, site_id: str, *, adapter: StorageAdapter) -> dict:
    from services.langgraph.agency.intake.release import artifact_release_verdict
    from services.langgraph.persistence import durable_runs
    from services.langgraph.persistence.agency_kernel import get_artifact

    s = load_stages(project_id, site_id, adapter)
    job_id = site_job_id(project_id, site_id, s["entries"]["source"]["content_hash"]) if "source" in s["entries"] else None
    job = durable_runs.get_job(job_id) if job_id else None
    result = (job or {}).get("result") or {}
    proof, proof_entry = s["proof"], s["entries"].get("release_proof")
    proof_current = bool(proof and result.get("proof_artifact", {}).get("version") == (proof_entry or {}).get("version")
                         and proof.revisions.get("source") == (s["manifest"].tree_hash if s["manifest"] else None))
    stale = stale_reasons(proof, get_artifact) if proof else []
    if proof and not proof_current:
        stale.append("PROOF_STALE: the proof does not belong to the current source revision")
    approval = result.get("approval") if proof_current else None
    verdict = artifact_release_verdict(
        simulated=False, verification_passed=bool(proof and proof.eligible_for_approval and not stale),
        artifact_id=(proof_entry or {}).get("artifact_id"), verified_version=(proof_entry or {}).get("version"),
        verified_hash=(proof_entry or {}).get("content_hash"), approval_id=(approval or {}).get("approval_id"),
        tenant_id=principal.tenant_id, project_id=project_id)
    reasons = list(verdict.reasons) + stale
    coverage = s["coverage"] if proof_current else None
    return {
        "site_id": site_id, "project_id": project_id,
        "stages": s["entries"],
        "job": {"job_id": job_id, "state": (job or {}).get("state"), "reasons": (job or {}).get("last_reasons") or []},
        "build": s["build"].model_dump(mode="json", exclude={"steps"}) if s["build"] and proof_current else None,
        "build_steps": [{k: st[k] for k in ("name", "exit_status", "duration_s")} for st in s["build"].steps]
        if s["build"] and proof_current else [],
        "browser_qa": {"status": s["browser_qa"].status, "checks": [c.model_dump(mode="json") for c in s["browser_qa"].checks],
                       "browser": s["browser_qa"].browser, "blocked_requests": list(s["browser_qa"].blocked_requests),
                       "screenshots": s["browser_qa"].screenshots, "note": s["browser_qa"].note}
        if s["browser_qa"] and proof_current else None,
        "coverage": {"coverage": coverage.coverage, "mandatory_resolved": coverage.mandatory_resolved,
                     "mandatory_applicable": coverage.mandatory_applicable, "release_blocked": coverage.release_blocked,
                     "debt": [d.model_dump(mode="json") for d in coverage.debt]} if coverage else None,
        "proof": proof.model_dump(mode="json") if proof and proof_current else None,
        "approval": approval,
        "release": {"allowed": verdict.allowed and not stale, "reasons": reasons, "deployment": "NOT_AUTHORIZED"},
        "external_effects": "none",
    }


def linker(project_id: str, site_id: str, *, adapter: StorageAdapter) -> IntentLinker:
    s = load_stages(project_id, site_id, adapter)
    pkg = s["requirements"]
    report = s["coverage"]
    if report is None or report.requirements_ref != pkg.content_hash:
        report, _ = evaluate(pkg, arch=s["architecture"], ir=s["ir"], files=s["files"], manifest=s["manifest"])
        qa = None
    else:
        qa = s["browser_qa"]
    return IntentLinker(pkg, report, ir=s["ir"], manifest=s["manifest"], verification=qa)


def list_sites(project_id: str) -> list[dict]:
    from services.langgraph.persistence.projects import list_project_artifacts

    out = []
    for a in list_project_artifacts(project_id):
        key = a.artifact_key
        if key.startswith("foundry-ucpo-") and key.endswith("-brief"):
            out.append({"site_id": key[len("foundry-ucpo-"):-len("-brief")], "brief_artifact": a.artifact_id,
                        "version": a.version})
    return sorted(out, key=lambda s: s["site_id"])


__all__ = ["APPROVAL_POLICY", "IMAGE_STAGE", "KIND", "RUN_PIPELINE", "STAGES", "SiteBuildHandler", "compile_site_line",
           "export_digest", "inspect_site", "linker", "list_sites", "load_stages", "run_build_tick", "site_job_id"]
