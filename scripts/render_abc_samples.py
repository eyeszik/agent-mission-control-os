#!/usr/bin/env python3
"""Render the ABC-v6 sample media through the real durable pipeline and record their provenance.

    python scripts/render_abc_samples.py [--out runtime/abc/samples]

Uses a throwaway SQLite database and export root (never the configured one),
submits three jobs (R1 still, R5 turntable from R1 frames, R4 vector mark),
drives them with ``run_tick`` until each waits for approval, then copies the
persisted bytes, re-hashes them and writes ``provenance.json`` with the mission
genome, render receipts, the independent verification, the transition log and
tick telemetry. No approval is decided here: that is a human action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PALETTE = {"primary": "#5b1a22", "secondary": "#665d52", "surface": "#ece6da", "text": "#121212"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "runtime" / "abc" / "samples"))
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="amc-abc-samples-"))
    os.environ.update({"AMC_DB_PATH": str(work / "samples.db"), "AMC_EXPORT_ROOT": str(work / "exports"),
                       "AMC_OBJECT_STORAGE_BACKEND": "local", "AMC_DATABASE_BACKEND": "sqlite"})

    from services.langgraph.agency.durable.genome import Predicate, compile_genome
    from services.langgraph.agency.durable.observability import metrics
    from services.langgraph.agency.durable.ticks import run_tick
    from services.langgraph.agency.durable.visual_job import HANDLERS, submit_visual_job
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter
    from services.langgraph.agency.visual.capabilities import probe_all
    from services.langgraph.agency.visual.contracts import RealismContract, VisualIntent
    from services.langgraph.persistence import durable_runs as store
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import create_project_workspace
    from services.langgraph.security.auth import Principal

    export = Path(os.environ["AMC_EXPORT_ROOT"])
    tenant, project = "tenant-abc-samples", "prj-abc-samples"
    create_project_workspace(tenant_id=tenant, project_id=project, actor="sample-operator", display_name="ABC samples",
                             slug="abc-samples", brand_name="Maison Velune", export_root=export)
    principal = Principal(user_id="sample-operator", tenant_id=tenant, role="admin", allowed_project_ids=frozenset({project}))
    caps = probe_all()
    jobs = {
        "still": VisualIntent(category="product_still", width=960, height=1200, samples=160, seed=7, palette=PALETTE),
        "turntable": VisualIntent(category="product_turntable", output="video", width=480, height=600, frames=36, fps=24,
                                  samples=24, seed=7, palette=PALETTE),
        "mark": VisualIntent(category="brand_mark", output="svg", subject="Maison Velune", palette=PALETTE),
    }
    genome = compile_genome(
        mission_id="abc-v6-samples", tenant_id=tenant, project_resolution={"status": "BOUND", "project_id": project},
        objective="Local product still, turntable and vector mark for review", audience="internal reviewers",
        deliverables=({"id": "still", "capability": "R1"}, {"id": "turntable", "capability": "R5"},
                      {"id": "mark", "capability": "R4"}),
        predicates=(Predicate(predicate_id="P_READBACK", description="persisted bytes reopen and pass Q0-Q4",
                              verifier="media.readback"),
                    Predicate(predicate_id="P_REVIEW", description="human visual/brand/realism review (Q5-Q7)",
                              verifier="human.review", depends_on=("P_READBACK",))),
        capabilities={"R1": caps[next(r for r in caps if r.value == "R1_BLENDER_CYCLES")].status.value,
                      "R5": caps[next(r for r in caps if r.value == "R5_LOCAL_VIDEO")].status.value,
                      "R4": caps[next(r for r in caps if r.value == "R4_VECTOR")].status.value},
    )
    if genome.status != "READY":
        print(json.dumps({"genome_status": genome.status, "blockers": genome.blockers}, indent=2))
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    samples, job_ids = [], {}
    due = datetime.now(timezone.utc) - timedelta(seconds=1)
    for key, intent in jobs.items():
        job = submit_visual_job(principal, project, intent, artifact_key=key, mission_id="abc-v6-samples", export_root=export,
                                due_at=due)
        job_ids[key] = job["job_id"]
        report = run_tick(worker_id="sample-worker", handlers=HANDLERS, job_id=job["job_id"])
        print(f"{key}: {report.outcome} -> {report.final_state} {report.reasons}", flush=True)
        if report.final_state != "WAITING_APPROVAL":
            return 1
        head = get_artifact(HANDLERS["visual_render"].target(job))
        data = LocalStorageAdapter(export).get_bytes(head["content_location"])
        mime = head["metadata"]["v2"]["mime_type"]
        ext = {"image/png": "png", "video/mp4": "mp4", "image/svg+xml": "svg"}[mime]
        name = f"{key}.{ext}"
        (out / name).write_bytes(data)
        intent_row = store.list_intents(job["job_id"])[0]
        observation = intent_row["receipt"]["observation"]
        samples.append({
            "file": name, "sha256": hashlib.sha256((out / name).read_bytes()).hexdigest(), "byte_size": len(data),
            "mime_type": mime, "artifact_id": head["artifact_id"], "artifact_version": head["version"],
            "recorded_content_hash": head["content_hash"], "execution_mode": "REAL_EXECUTION",
            "intent": intent.model_dump(mode="json"), "route": observation.get("route"),
            "render_receipts": observation.get("receipts"), "verification": observation.get("verification"),
            "idempotency_key": intent_row["idempotency_key"], "approval_id": store.get_job(job["job_id"])["result"]["approval_id"],
            "review_state": "HUMAN_REQUIRED (Q5 visual constraints, Q6 realism/brand, Q7 approval)",
            "transitions": [(t["from_state"], t["to_state"]) for t in store.list_transitions(job["job_id"])],
        })
    realism = RealismContract(
        target_category="product still / turntable", reference_rights="procedural_owned",
        scene_or_model="procedural spool, thread, folded wool and needle on a plaster wall (blender_runner.py)",
        lighting_model="Cycles path tracing: area key, fill and rim lights", material_fidelity="procedural Principled BSDF "
        "with object-space wave/noise bump; no scanned textures", camera_model="85 mm, f/2.8, focus target",
        texture_resolution="procedural (resolution-independent)", color_pipeline="sRGB palette -> linear -> Filmic -> sRGB PNG",
        image_dimensions=(960, 1200), realism_criteria=("plausible light falloff and contact shadows", "material scale",
                                                        "no visible fireflies or banding"),
        allowed_variance="Cycles + OpenImageDenoise output is not bit-reproducible across runs",
        review_requirements=("human visual review", "brand review", "realism review"))
    ticks = [t for j in job_ids.values() for t in store.list_ticks(j)]
    doc = {
        "schema_version": "amc-abc-samples/v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "mission_genome": genome.model_dump(mode="json"), "genome_hash": genome.genome_hash,
        "realism_contract": realism.model_dump(mode="json"),
        "capabilities": {r.value: {"status": c.status.value, "version": c.version, "blockers": list(c.blockers)}
                         for r, c in caps.items()},
        "samples": samples,
        "telemetry": [t["telemetry"] for t in ticks],
        "metrics": metrics(ticks=ticks, transitions=[t for j in job_ids.values() for t in store.list_transitions(j)],
                           intents=[i for j in job_ids.values() for i in store.list_intents(j)]),
        "claims_not_made": ["photorealism (a decodable, non-blank image is not a photograph)",
                            "approval (every sample is WAITING_APPROVAL)", "bit-reproducibility of the Cycles renders"],
    }
    (out / "provenance.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({s["file"]: [s["byte_size"], s["verification"]["status"], s["verification"]["highest_passed"]]
                      for s in samples}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
