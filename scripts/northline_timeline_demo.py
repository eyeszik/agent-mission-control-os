#!/usr/bin/env python3
"""Render fictional Northline timeline drafts locally, without external actions.

Uses the disposable synthetic database created by northline_local_demo.py and
requires its current approved test-fixture brand. Produces a silent 30-second
procedural animation and two 15-second re-edits from the same master shot
sources, with on-screen text alternatives in WebVTT. These are review drafts,
not a finished cinematic film, real-client approval, release or deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = "tenant-northline-synthetic"
PROJECT = "prj-northline-synthetic"
BRAND = "brand-northline-synthetic"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-dir", type=Path, required=True, help="Disposable demo from northline_local_demo.py")
    parser.add_argument("--chromium", type=Path, required=True, help="Local Chromium executable")
    parser.add_argument("--output-name", default="timeline-draft", help="New directory name within the demo; no overwrite")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", args.output_name):
        raise SystemExit("Output name must contain only lowercase letters, digits and hyphens")
    demo, chromium = args.demo_dir.expanduser().resolve(), args.chromium.expanduser().resolve()
    report_file = demo / "northline-report.json"
    if not report_file.is_file() or not (demo / "northline.db").is_file() or not chromium.is_file():
        raise SystemExit("Synthetic demo report/database or local Chromium missing")
    website_report = json.loads(report_file.read_text(encoding="utf-8"))
    if ((website_report.get("tenant"), website_report.get("project"), website_report.get("brand")) != (TENANT, PROJECT, BRAND)
            or "FICTIONAL / SYNTHETIC LOCAL DEMO" not in website_report.get("label", "")):
        raise SystemExit("Refusing anything other than the disposable synthetic Northline demo")
    output = demo / args.output_name
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing draft")
    output.mkdir()
    os.environ.update({"AMC_DATABASE_BACKEND": "sqlite", "AMC_DB_PATH": str(demo / "northline.db"),
                       "AMC_EXPORT_ROOT": str(demo / "objects"), "AMC_OBJECT_STORAGE_BACKEND": "local",
                       "AMC_AUTH_MODE": "local", "AMC_ENV": "local"})
    os.environ.pop("AMC_ALLOW_SELF_APPROVAL", None)

    from services.langgraph.agency.foundry.studio import observe, store
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter
    from services.langgraph.agency.timeline import ClipSpec, Timebase, Timeline, validate_cutdown
    from services.langgraph.agency.ucpo.brand_web import current_brand
    from services.langgraph.agency.visual import browser
    from services.langgraph.agency.vnexus import fabric_service, production, timeline_render, video
    from services.langgraph.agency.vnexus.bridge import GenomeProjection, creative_genome
    from services.langgraph.agency.vnexus.graph import NodeKind
    from services.langgraph.agency.vnexus.media_fabric import Capability, MediaRequest
    from services.langgraph.security.auth import Principal

    browser.chromium_path = lambda: chromium  # local render tool; never canonical website QA
    available = browser.probe_browser()
    if not available["available"] or not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("Required local renderer, verifier or isolation unavailable: " + "; ".join(available["blockers"]))
    principal = Principal("alice-synthetic", TENANT, "operator", frozenset({PROJECT}))
    adapter = LocalStorageAdapter(demo / "objects")
    resolution, layers = current_brand(principal, PROJECT, BRAND)
    if layers[-1]["version_id"] != website_report["v2"]["brand_version"]:
        raise SystemExit("Approved synthetic brand changed since the website demo")
    values = resolution.values
    projection = GenomeProjection(resolution, brand_name=values["verbal.messaging.organization"], genome_ref=layers[-1]["version_id"])
    genome = creative_genome(projection, project_id=PROJECT)

    def current() -> None:
        now, now_layers = current_brand(principal, PROJECT, BRAND)
        if now.resolution_hash != resolution.resolution_hash or now_layers != layers:
            raise RuntimeError("Synthetic approved brand changed; draft production stopped")

    def clip(cid: str, role: str, duration: int, *, source: str | None = None, overlap: int = 0) -> ClipSpec:
        return ClipSpec(clip_id=cid, shot_ref=source or cid, role=role, duration_frames=duration,
                        transition_in="dissolve" if overlap else "cut", overlap_frames=overlap)

    timebase = Timebase(fps="30")
    # These are synthetic statements, not evidence-backed proof claims.
    roles = ("hook", "headline", "message", "message", "message", "cta")
    master = Timeline(timeline_id="northline-master-30", kind="master", timebase=timebase,
        clips=tuple(clip(f"m{i + 1}", role, 160, overlap=0 if i == 0 else 12) for i, role in enumerate(roles)))
    a = Timeline(timeline_id="northline-cut-15a", kind="cutdown", master_timeline_id=master.timeline_id, timebase=timebase,
        clips=(clip("a1", "hook", 154, source="m1"), clip("a2", "message", 160, source="m4", overlap=12),
               clip("a3", "cta", 160, source="m6", overlap=12)))
    b = Timeline(timeline_id="northline-cut-15b", kind="cutdown", master_timeline_id=master.timeline_id, timebase=timebase,
        clips=(clip("b1", "headline", 160, source="m2"), clip("b2", "message", 154, source="m3", overlap=12),
               clip("b3", "cta", 160, source="m6", overlap=12)))
    assert master.total_frames() == 900 and master.total_seconds() == "30"
    validate_cutdown(master, a, target_seconds="15")
    validate_cutdown(master, b, target_seconds="15")
    copy = (genome.brand_name, values["verbal.messaging.index_heading"], values["verbal.messaging.services_heading"],
            values["verbal.messaging.process_heading"], values["verbal.messaging.workflow_diagnostic_heading"],
            values["verbal.messaging.cta"])
    kinds = (video.ShotKind.MARK_REVEAL, video.ShotKind.HEADLINE, video.ShotKind.HEADLINE,
             video.ShotKind.HEADLINE, video.ShotKind.HEADLINE, video.ShotKind.CALL_TO_ACTION)
    shots = {f"m{i + 1}": video.Shot(shot_id=f"m{i + 1}", kind=kind, duration_s=160 / 30, text=(copy[i],),
                                    camera="procedural text/mark; not filmed footage", transition="cut",
                                    path="A_PROCEDURAL") for i, kind in enumerate(kinds)}
    width, height, fps = 640, 360, 30

    def provenance(executable: Path, version_flag: str) -> dict:
        digest = hashlib.sha256()
        with executable.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        if (executable.parent / "lib").is_dir():
            env["LD_LIBRARY_PATH"] = str(executable.parent / "lib")
        result = subprocess.run([str(executable), version_flag], capture_output=True, text=True, timeout=15, check=True, env=env)
        lines = (result.stdout or result.stderr).splitlines()
        if not lines:
            raise RuntimeError(f"Could not read {executable.name} version")
        return {"executable": executable.name, "sha256": digest.hexdigest(), "version": lines[0][:300]}

    tools = {"chromium": provenance(chromium, "--version"),
             "ffmpeg": provenance(Path(shutil.which("ffmpeg")).resolve(), "-version"),
             "ffprobe": provenance(Path(shutil.which("ffprobe")).resolve(), "-version")}
    plan = {"schema": "amc-northline-procedural-edit-draft/v1", "label": "FICTIONAL SILENT PROCEDURAL DRAFT",
            "approval": "synthetic test fixture only", "resolution_hash": resolution.resolution_hash,
            "genome_ref": projection.genome_ref, "brand_layers": layers, "projection_trace": projection.trace(),
            "creative_genome": genome.model_dump(mode="json"), "width": width, "height": height, "fps": fps,
            "master": master.model_dump(mode="json"), "cutdowns": [a.model_dump(mode="json"), b.model_dump(mode="json")],
            "shot_sources": {k: v.model_dump(mode="json") for k, v in shots.items()}, "tools": tools,
            "rights": "procedural shapes and synthetic text; no music, voice, footage or external image used; system font rights not independently verified",
            "caption_note": "WebVTT is a text alternative to on-screen copy, not a transcript of speech; cue starts use estimated opacity",
            "limitations": ["640x360 draft", "silent", "human creative and accessibility review not performed",
                            "cross-dissolves can visibly overlap title layers; transition typography needs review",
                            "font license clearance not verified", "no footage or media-level continuity review",
                            "not approved or authorized for release"]}
    plan_bytes = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode()
    (output / "editable-timeline.json").write_bytes(plan_bytes)
    current()
    plan_head = store(principal, PROJECT, f"{args.output_name}-editable-timeline.json", plan_bytes, mime="application/json",
                      artifact_type="media_asset", subtype="vnexus_procedural_timeline", adapter=adapter,
                      v2={"provenance_ref": f"vnexus:{projection.genome_ref}", "synthetic": True})
    readback, _ = observe(plan_head["artifact_id"], adapter)
    if hashlib.sha256(readback).hexdigest() != plan_head["content_hash"]:
        raise RuntimeError("Timeline plan readback failed")
    results: list[dict] = []
    master_id: str | None = None
    master_still_svg: str | None = None
    for edit, name in ((master, "master-30s"), (a, "cutdown-a-15s"), (b, "cutdown-b-15s")):
        current()
        frames = timeline_render.compose_frames(master, edit, shots, genome, width=width, height=height)
        if edit == master:
            master_still_svg = frames[-1]
        if len(frames) != edit.total_frames():
            raise RuntimeError("Compositor returned a different frame count from the validated edit")
        dependencies = (plan_head["artifact_id"],) + ((master_id,) if master_id else ())
        job = fabric_service.execute(principal, PROJECT, provider_id="local.svg_motion", idempotency_key=f"{args.output_name}:{name}",
            depends_on=dependencies, request=MediaRequest(capability=Capability.MOTION_MP4,
                spec={"frames": frames, "fps": fps}, width=width, height=height, label=name))
        if job["state"] != "QC_PASSED" or not job.get("artifact", {}).get("artifact_id"):
            raise RuntimeError(f"{name} render failed: {job.get('error')}; QC={job.get('qc')}")
        art = job["artifact"]
        current()
        data, head = observe(art["artifact_id"], adapter)
        sha = hashlib.sha256(data).hexdigest()
        if sha != art["sha256"] or head["content_hash"] != sha:
            raise RuntimeError(f"{name} readback hash mismatch")
        path = output / f"{name}.mp4"
        path.write_bytes(data)
        streams = video.probe_streams(path)
        video_streams = [s for s in streams.get("streams", []) if s.get("codec_type") == "video"]
        if (streams.get("status") != "OK" or len(video_streams) != 1
                or video_streams[0].get("nb_read_frames") != str(edit.total_frames())
                or (video_streams[0].get("width"), video_streams[0].get("height")) != (width, height)
                or any(s.get("codec_type") == "audio" for s in streams["streams"])):
            raise RuntimeError(f"{name} did not independently match its expected silent video streams")
        if master_id is None:
            master_id = art["artifact_id"]
        vtt = timeline_render.captions(master, edit, shots, width=width, height=height).encode()
        vtt_head = store(principal, PROJECT, f"{args.output_name}-{name}.vtt", vtt, mime="text/vtt", artifact_type="media_asset",
                         subtype="captions", adapter=adapter, depends_on=(art["artifact_id"], plan_head["artifact_id"]))
        checked_vtt, vtt_observed = observe(vtt_head["artifact_id"], adapter)
        if hashlib.sha256(checked_vtt).hexdigest() != vtt_head["content_hash"]:
            raise RuntimeError(f"{name} captions failed readback")
        (output / f"{name}.vtt").write_bytes(checked_vtt)
        production.link_output(principal, BRAND, label=f"{name} procedural draft", kind=NodeKind.ASSET, ref=art["artifact_id"],
            attributes={"sha256": sha, "timeline_hash": edit.content_hash(), "demo": "silent synthetic draft"},
            genome_version_id=projection.genome_ref, job_id=job["job_id"])
        results.append({"name": name, "file": path.name, "sha256": sha, "artifact_id": art["artifact_id"], "job_id": job["job_id"],
                        "captions": f"{name}.vtt", "captions_sha256": vtt_head["content_hash"],
                        "captions_artifact_id": vtt_head["artifact_id"], "frames": edit.total_frames(),
                        "fps": fps, "duration_seconds": edit.total_seconds(), "timeline_hash": edit.content_hash(),
                        "stream_probe": streams, "qc": job["qc"], "dependencies": list(dependencies)})
        (output / "progress.json").write_text(json.dumps({"status": "IN_PROGRESS", "completed": results}, indent=2) + "\n")
        print(f"{name}: {edit.total_frames()} frames; readback verified", flush=True)
    current()
    if not master_id or not master_still_svg:
        raise RuntimeError("Master frame is unavailable for the reduced-motion alternative")
    still_vector = fabric_service.execute(principal, PROJECT, provider_id="local.svg",
        idempotency_key=f"{args.output_name}:reduced-motion:svg", depends_on=(master_id, plan_head["artifact_id"]),
        request=MediaRequest(capability=Capability.VECTOR_SVG, spec={"svg": master_still_svg},
                             width=width, height=height, label="master-reduced-motion.svg"))
    if still_vector["state"] != "QC_PASSED" or not still_vector.get("artifact", {}).get("artifact_id"):
        raise RuntimeError(f"Reduced-motion SVG failed: {still_vector.get('error')}")
    vector_art = still_vector["artifact"]
    still_raster = fabric_service.execute(principal, PROJECT, provider_id="local.chromium_raster",
        idempotency_key=f"{args.output_name}:reduced-motion:png", depends_on=(master_id, vector_art["artifact_id"]),
        request=MediaRequest(capability=Capability.RASTER_PNG, spec={"svg": master_still_svg},
                             width=width, height=height, label="master-reduced-motion.png"))
    if still_raster["state"] != "QC_PASSED" or not still_raster.get("artifact", {}).get("artifact_id"):
        raise RuntimeError(f"Reduced-motion PNG failed: {still_raster.get('error')}")
    still_outputs = {}
    for kind, job in (("svg", still_vector), ("png", still_raster)):
        art = job["artifact"]
        content, stored_head = observe(art["artifact_id"], adapter)
        if hashlib.sha256(content).hexdigest() != art["sha256"] or stored_head["content_hash"] != art["sha256"]:
            raise RuntimeError(f"Reduced-motion {kind} readback mismatch")
        name = f"master-reduced-motion.{kind}"
        (output / name).write_bytes(content)
        production.link_output(principal, BRAND, label=f"{name} procedural draft", kind=NodeKind.ASSET, ref=art["artifact_id"],
            attributes={"sha256": art["sha256"], "demo": "synthetic reduced-motion alternative"},
            genome_version_id=projection.genome_ref, job_id=job["job_id"])
        still_outputs[kind] = {"file": name, "sha256": art["sha256"], "artifact_id": art["artifact_id"],
                               "job_id": job["job_id"], "qc": job["qc"]}
    current()
    final = {"label": "FICTIONAL SILENT PROCEDURAL DRAFTS; NOT AUTHORIZED FOR RELEASE", "external_effects": "none",
             "rights_status": "NOT_MEASURED: system-font clearance and source inventory not independently verified",
             "plan_artifact_id": plan_head["artifact_id"], "plan_sha256": plan_head["content_hash"], "outputs": results, "tools": tools,
             "reduced_motion": {"source": "last uncompressed master frame", "width": width, "height": height,
                                "alt": f"{genome.brand_name}: {copy[-1]}. Dark text with an orange underline on a pale background.",
                                "outputs": still_outputs},
             "limitations": plan["limitations"], "website_qa": website_report["v2"]["browser_qa_status"],
             "note": "Cutdowns are re-rendered from the same frame-addressed master shot sources; they are not extracted from the encoded master."}
    result_bytes = (json.dumps(final, indent=2, sort_keys=True) + "\n").encode()
    (output / "timeline-report.json").write_bytes(result_bytes)
    (output / "progress.json").unlink()
    print(json.dumps({"drafts": len(results), "report": str(output / "timeline-report.json"),
                      "report_sha256": hashlib.sha256(result_bytes).hexdigest(), "release": "NOT_AUTHORIZED"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
