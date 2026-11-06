"""One local run of the website line without a database: brief -> verified site in a directory.

Used by ``orchestrate_brand_pipeline.py website``. It writes the generated source (preserving
human edits from an earlier run), the browser evidence and a JSON report. The release proof
it prints is eligible-for-approval at most: approval and release go through a project
(``/ucpo`` routes), never this command. Exit codes: 0 every gate passed, 1 release blocked,
3 BLOCKED_ISOLATION (source written, nothing executed).
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from services.langgraph.agency.foundry import psem

from . import build as build_mod
from .contracts import SourceTreeManifest, WebsiteBrief
from .preview import serve
from .qa import verify_build
from .release import seal_proof
from .requirements import compile_requirements
from .semantic import evaluate
from .service import _export_bundle
from .site import compile_site
from .source import export_tree, generate_source


def run_local(brief: WebsiteBrief, out: Path, *, preview_seconds: Optional[float] = None) -> tuple[int, dict]:
    out.mkdir(parents=True, exist_ok=True)
    pkg = compile_requirements(brief, project_ref="local")
    genome = psem.compile_psem_genome(psem.psem_brief(brief.organization, offering=brief.offering,
                                                      target_audience=brief.audience, seed=brief.seed), project_id="local")
    _, css, token_hash = psem.compile_psem_tokens(genome)
    arch, ir = compile_site(brief, pkg, genome, token_refs={"dtcg_source_hash": token_hash})
    files, manifest = generate_source(ir, genome, css)
    previous_path = out / "source-manifest.json"
    previous = SourceTreeManifest.model_validate_json(previous_path.read_text()) if previous_path.is_file() else None
    written = export_tree(out / "source", files, previous)
    previous_path.write_text(manifest.model_dump_json(indent=1))

    routes = [p.route for p in ir.pages]
    build, out_dir = build_mod.build_site(files, manifest, routes=routes, keep_output=True)
    qa = None
    preview = None
    evidence = out / "evidence"
    try:
        if out_dir is not None:
            shutil.rmtree(evidence, ignore_errors=True)
            qa = verify_build(out_dir, routes=routes, expected_output_hash=build.output_hash or "", evidence_dir=evidence)
            if preview_seconds and qa.status == "PASSED":
                preview = serve(_export_bundle(out_dir), expected_output_hash=build.output_hash or "")
    finally:
        if out_dir is not None:
            build_mod.cleanup(out_dir.parent.parent)
    report, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=qa)
    proof = seal_proof(project_ref="local", site_id="local", revisions={
        "brief": brief.content_hash, "requirements": pkg.content_hash, "genome": genome.content_hash, "tokens": token_hash,
        "site_ir": ir.content_hash, "source": manifest.tree_hash, "build": build.output_hash or build.status,
        "browser_qa": qa.content_hash if qa else "NOT_RUN", "coverage": report.content_hash},
        artifact_refs={}, build=build, qa=qa, coverage=report)
    summary = {
        "source": {"files": len(files), "tree_hash": manifest.tree_hash, "written": written["write"],
                   "preserved_human_edits": written["preserved"], "conflicts": written["conflicts"]},
        "build": {"status": build.status, "steps": [{k: s[k] for k in ("name", "exit_status", "duration_s")} for s in build.steps],
                  "output_hash": build.output_hash, "isolation": build.isolation},
        "browser_qa": {"status": qa.status, "failed": [c.model_dump(mode="json") for c in qa.checks if c.result != "PASS"],
                       "checks": len(qa.checks), "screenshots": qa.screenshots} if qa else None,
        "coverage": {"coverage": report.coverage, "mandatory_resolved": report.mandatory_resolved,
                     "mandatory_applicable": report.mandatory_applicable, "debt": [d.req_id for d in report.debt]},
        "proof": {"eligible_for_approval": proof.eligible_for_approval, "reasons": list(proof.reasons),
                  "deployment": proof.deployment, "note": "approval happens in a project via /ucpo and /approvals"},
    }
    (out / "report.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    if preview is not None:
        summary["preview"] = preview.describe()
        print(f"preview (loopback only): {preview.reachable_endpoint}", flush=True)
        try:
            time.sleep(preview_seconds or 0)
        except KeyboardInterrupt:
            pass
        summary["preview"] = preview.stop().describe()
    code = 3 if build.status == "BLOCKED_ISOLATION" else (0 if proof.eligible_for_approval else 1)
    return code, summary


__all__ = ["run_local"]
