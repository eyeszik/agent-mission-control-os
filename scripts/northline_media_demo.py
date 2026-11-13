#!/usr/bin/env python3
"""Produce local, fictional Northline media previews from the synthetic demo.

This is a preview, not a client deliverable or release authorization. It uses
only the disposable demo database created by northline_local_demo.py, approved
SYNTHETIC values and local renderers. It never calls a hosted provider, spends,
publishes or deploys. The Chromium path is explicit and is NOT used as canonical
UCPO website QA. Human review, a 30-second film and two cutdowns remain open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = "tenant-northline-synthetic"
PROJECT = "prj-northline-synthetic"
BRAND = "brand-northline-synthetic"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-dir", type=Path, required=True, help="Output of northline_local_demo.py")
    parser.add_argument("--chromium", type=Path, required=True, help="Local Chromium executable; a sibling lib/ is supported")
    parser.add_argument("--output-name", default="media-preview-checked", help="New output directory within the demo (no overwrite)")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", args.output_name):
        raise SystemExit("Output name must contain only lowercase letters, digits and hyphens")
    demo, chromium = args.demo_dir.expanduser().resolve(), args.chromium.expanduser().resolve()
    report_path = demo / "northline-report.json"
    if not report_path.is_file() or not (demo / "northline.db").is_file() or not chromium.is_file():
        raise SystemExit("Missing synthetic demo report/database or local Chromium executable")
    previous = json.loads(report_path.read_text(encoding="utf-8"))
    if ((previous.get("tenant"), previous.get("project"), previous.get("brand")) != (TENANT, PROJECT, BRAND)
            or "FICTIONAL / SYNTHETIC LOCAL DEMO" not in previous.get("label", "")):
        raise SystemExit("Refusing anything other than the disposable synthetic Northline demo")
    out = demo / args.output_name
    if out.exists():
        raise SystemExit("Refusing to overwrite an existing preview directory")
    out.mkdir()
    (out / "social").mkdir()
    (out / "video").mkdir()
    os.environ.update({"AMC_DATABASE_BACKEND": "sqlite", "AMC_DB_PATH": str(demo / "northline.db"),
                       "AMC_EXPORT_ROOT": str(demo / "objects"), "AMC_OBJECT_STORAGE_BACKEND": "local",
                       "AMC_AUTH_MODE": "local", "AMC_ENV": "local"})
    os.environ.pop("AMC_ALLOW_SELF_APPROVAL", None)

    # Imports only after the disposable environment is fixed.
    from services.langgraph.agency.foundry import compose
    from services.langgraph.agency.foundry.studio import observe
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter
    from services.langgraph.agency.ucpo.brand_web import current_brand
    from services.langgraph.agency.visual import browser
    from services.langgraph.agency.vnexus import fabric_service, identity, production, video
    from services.langgraph.agency.vnexus.bridge import GenomeProjection, creative_genome
    from services.langgraph.agency.vnexus.genome import Scope
    from services.langgraph.agency.vnexus.graph import NodeKind
    from services.langgraph.agency.vnexus.media_fabric import Capability, MediaRequest
    from services.langgraph.security.auth import Principal

    browser.chromium_path = lambda: chromium  # explicit local diagnostic choice, not a site-QA override
    principal = Principal("alice-synthetic", TENANT, "operator", frozenset({PROJECT}))
    adapter = LocalStorageAdapter(demo / "objects")
    resolution, layers = current_brand(principal, PROJECT, BRAND)
    if layers[-1]["version_id"] != previous["v2"]["brand_version"]:
        raise SystemExit("Synthetic approved brand has changed; do not reuse the earlier demo report")
    values = resolution.values
    projection = GenomeProjection(resolution, brand_name=values["verbal.messaging.organization"], genome_ref=layers[-1]["version_id"])
    genome = creative_genome(projection, project_id=PROJECT)
    probe = browser.probe_browser()
    if not probe["available"]:
        raise SystemExit("Local browser unavailable: " + "; ".join(probe["blockers"]))
    lib = chromium.parent / "lib"
    version = subprocess.run([str(chromium), "--version"], capture_output=True, text=True, timeout=10,
                             env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LD_LIBRARY_PATH": str(lib)}).stdout.strip()
    browser_sha = hashlib.sha256(chromium.read_bytes()).hexdigest()
    headings = [
        ("01-clear-workflow", "verbal.messaging.index_heading"),
        ("02-start-with-work", "verbal.messaging.services_heading"),
        ("03-map-discuss-decide", "verbal.messaging.process_heading"),
        ("04-invisible-work", "verbal.messaging.workflow_diagnostic_heading"),
        ("05-priorities-plan", "verbal.messaging.implementation_planning_heading"),
        ("06-practical-design", "verbal.messaging.about_heading"),
    ]
    outputs = []
    for index, (name, key) in enumerate(headings, start=1):
        headline, cta = values[key], values["verbal.messaging.cta"]
        ir = compose.poster(genome, headline=headline, cta=cta, width=1080, height=1080, variant_seed=index)
        svg = compose.to_svg(ir, genome)
        with tempfile.TemporaryDirectory(prefix="northline-social-layout-") as work:
            rendered_layout = identity.rendered_text_layout(ir, genome, margin=0.06, work=Path(work))
        checks = [identity.palette_check(svg, genome), identity.text_contrast(ir, genome), identity.safe_area(ir, 0.06),
                  identity.text_overlap(ir), rendered_layout]
        if any(c["status"] != "PASSED" for c in checks):
            raise RuntimeError(f"{name} did not pass a local preflight: {checks}")
        vector = fabric_service.execute(principal, PROJECT, provider_id="local.svg", idempotency_key=f"{args.output_name}:social:{name}:svg",
            request=MediaRequest(capability=Capability.VECTOR_SVG, spec={"svg": svg}, width=1080, height=1080, label=name))
        if vector["state"] != "QC_PASSED":
            raise RuntimeError(f"{name} vector failed: {vector.get('error')}")
        vector_art = vector["artifact"]
        raster = fabric_service.execute(principal, PROJECT, provider_id="local.chromium_raster",
            idempotency_key=f"{args.output_name}:social:{name}:png", depends_on=(vector_art["artifact_id"],),
            request=MediaRequest(capability=Capability.RASTER_PNG, spec={"svg": svg}, width=1080, height=1080, label=name))
        if raster["state"] != "QC_PASSED":
            raise RuntimeError(f"{name} raster failed: {raster.get('error')}")
        image_art = raster["artifact"]
        for art, job, suffix in ((vector_art, vector, "svg"), (image_art, raster, "png")):
            data, head = observe(art["artifact_id"], adapter)
            if hashlib.sha256(data).hexdigest() != art["sha256"] or head["content_hash"] != art["sha256"]:
                raise RuntimeError(f"{name} {suffix} readback hash mismatch")
            (out / "social" / f"{name}.{suffix}").write_bytes(data)
            production.link_output(principal, BRAND, label=f"{name}.{suffix}", kind=NodeKind.ASSET, ref=art["artifact_id"],
                attributes={"sha256": art["sha256"], "mime": art["mime"], "demo": "synthetic preview"},
                genome_version_id=projection.genome_ref, job_id=job["job_id"])
        outputs.append({"name": name, "headline_key": key, "headline": headline, "cta_key": "verbal.messaging.cta",
                        "png": f"social/{name}.png", "svg": f"social/{name}.svg", "width": 1080, "height": 1080,
                        "alt": f"Northline Workflow Studio: {headline}. {cta}.",
                        "png_artifact_id": image_art["artifact_id"], "png_sha256": image_art["sha256"],
                        "svg_artifact_id": vector_art["artifact_id"], "svg_sha256": vector_art["sha256"],
                        "png_job_id": raster["job_id"], "preflight": checks, "qc": raster.get("qc")})
    # A shorter, cut-only procedural animation demonstrates the real local
    # media path. It is deliberately not labelled as the requested 30 s film.
    brief = video.VideoBrief(objective=values["strategy.positioning.statement"], headline=values["verbal.messaging.index_heading"],
        points=(values["verbal.messaging.services_heading"], values["verbal.messaging.process_heading"],
                values["verbal.messaging.workflow_diagnostic_heading"], values["verbal.messaging.implementation_planning_heading"]),
        cta=values["verbal.messaging.cta"], width=480, height=270, fps=10, max_duration_s=14)
    film = production.produce_video(principal, BRAND, scope=Scope.PROJECT, scope_ref=PROJECT, project_id=PROJECT,
                                    brief=brief, run_key=f"{args.output_name}:video-preview")
    for role, artifact_id in film["stages"]["master"]["deliverables"].items():
        suffix = {"master_silent": "mp4", "captions": "vtt", "reduced_motion_still": "png"}.get(role)
        if not suffix:
            continue
        data, head = observe(artifact_id, adapter)
        if hashlib.sha256(data).hexdigest() != head["content_hash"]:
            raise RuntimeError(f"{role} readback hash mismatch")
        (out / "video" / f"{role}.{suffix}").write_bytes(data)
    current, current_layers = current_brand(principal, PROJECT, BRAND)
    if current.resolution_hash != resolution.resolution_hash or current_layers != layers:
        raise RuntimeError("Synthetic brand changed during preview production; outputs must be regenerated")
    result = {"label": "FICTIONAL SYNTHETIC PREVIEWS ONLY; no real-client approval, publication or deployment",
              "external_effects": "none", "genome_ref": projection.genome_ref, "resolution_hash": projection.resolution_hash,
              "brand_layers": layers, "projection_trace": projection.trace(),
              "chromium": {"version": version, "sha256": browser_sha,
                           "note": "local media renderer only; not canonical UCPO website QA"},
              "social": outputs, "video_brief": brief.model_dump(mode="json"), "video": film,
              "rights_status": "NOT_MEASURED: declared procedural shapes and synthetic text; system-font clearance not verified",
              "remaining": ["human visual and accessibility review", "30-second finished film with requested transitions",
                            "two finished, reviewed 15-second cutdowns (separate procedural drafts may exist)",
                            "audio and rights where required", "canonical website browser QA",
                            "real client approval and release authorization"]}
    data = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    (out / "media-report.json").write_bytes(data)
    print(json.dumps({"social_previews": len(outputs), "video_state": film["status"],
                      "video_frames": film["stages"]["compositing"]["frames"],
                      "video_fps": brief.fps, "report": str(out / "media-report.json"),
                      "report_sha256": hashlib.sha256(data).hexdigest(), "release": "NOT_AUTHORIZED"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
