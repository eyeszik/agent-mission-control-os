"""One local AVIC run without a database: request JSON -> release-package directory.

Used by ``orchestrate_brand_pipeline.py avic``. It compiles, renders, evaluates and
(bounded) repairs, then writes the package files. A local run is never released:
``release.json`` says so, because approval needs a project and a second person
(``service.request_approval`` + ``/approvals/{id}/decide``). Exit codes: 0 evaluation
passed, 1 evaluation failed or blocked by policy, 3 renderer unavailable.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from services.langgraph.agency.prompt_compiler import AssetRequirement

from . import brand as brandmod
from . import optimize, png, references as refmod, render as rendermod, repair as repairmod, svg
from .contracts import COMPILER_VERSION, POLICY_VERSION, SCHEMA_VERSION, OutputProfile, ReferenceRole
from .evaluate import evaluate
from .intent import compile_intent
from .profiles import ProfileUnavailable, get_profile, psem_brand
from .scene import compile_scene, requirement_coverage


def _w(path: Path, obj) -> str:
    data = (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _render(text: str, w: int, h: int, d: Path) -> dict:
    return rendermod.render(text, width=w, height=h, work_dir=d)


def run_local(request: dict, out: Path, *, reference: Optional[Path] = None, variants: int = 0) -> tuple[int, dict]:
    out.mkdir(parents=True, exist_ok=True)
    work = out / ".work"
    req = AssetRequirement.model_validate(request["requirement"])
    profile_id = request.get("style_profile", "post-surrealist-editorial")
    seed = int(request.get("seed", 0))
    timings: dict[str, float] = {}
    intent = compile_intent(req, style_profile=profile_id)
    if intent.blocked():
        return 1, {"status": "BLOCKED", "reasons": [f"{i.item_id}:{i.classification.value}:{i.reason}" for i in intent.blocked()]}
    try:
        profile = get_profile(profile_id)
    except ProfileUnavailable as exc:
        return 1, {"status": "BLOCKED", "reasons": [str(exc)]}
    brand = psem_brand()
    inputs = []
    if reference is not None:  # a local file the operator supplies; rights are asserted by the operator running the CLI
        inputs.append(refmod.ReferenceInput("ref-local", reference.read_bytes(), ReferenceRole.COLOR, True))
    manifest, ref_evidence = refmod.analyze(inputs)
    t = time.perf_counter()
    scene = compile_scene(intent, brand, profile, manifest, seed=seed, reference_evidence=ref_evidence)
    text = svg.emit(scene)
    timings["compile_latency_ms"] = round((time.perf_counter() - t) * 1000, 1)
    r = _render(text, scene.document.width, scene.document.height, work / "render")
    timings["render_latency_ms"] = r["render_ms"] or 0
    if r["status"] == "BLOCKED":
        (out / "master.svg").write_text(text)
        return 3, {"status": "BLOCKED", "reasons": ["RENDERER_UNAVAILABLE", *r["findings"]]}
    t = time.perf_counter()
    report = evaluate(scene, text, intent=intent, brand=brand, png_bytes=r["png"], renderer=rendermod.RENDERER,
                      renderer_version=r["renderer_version"])
    timings["verify_latency_ms"] = round((time.perf_counter() - t) * 1000, 1)
    png_bytes = r["png"]
    repairs = []
    if report.failures():
        outcomes, missing = repairmod.repair(scene, text, report, brand=brand, intent=intent, render=_render,
                                             work_dir=work / "repair", renderer=rendermod.RENDERER,
                                             renderer_version=r["renderer_version"])
        for o in outcomes:
            repairs.append({"defect": o.defect.model_dump(mode="json"), "accepted": o.accepted, "attempts": o.attempts})
            if o.accepted and o.scene is not None:
                scene, text, png_bytes, report = o.scene, o.svg_text, o.png, o.report
    coverage = requirement_coverage(intent, scene)
    files = {"master.svg": hashlib.sha256(text.encode()).hexdigest()}
    (out / "master.svg").write_text(text)
    if png_bytes:
        (out / "preview.png").write_bytes(png_bytes)
        files["preview.png"] = hashlib.sha256(png_bytes).hexdigest()
    files["scene.json"] = _w(out / "scene.json", scene.model_dump(mode="json"))
    files["requirements.json"] = _w(out / "requirements.json", {"requirement": req.model_dump(mode="json"),
                                                                "intent": intent.model_dump(mode="json"), "coverage": coverage})
    files["brand.json"] = _w(out / "brand.json", {**brand.model_dump(mode="json"), "authority": "PROJECTION"})
    files["constraints.json"] = _w(out / "constraints.json", [c.model_dump(mode="json") for c in scene.constraints])
    files["evaluation.json"] = _w(out / "evaluation.json", {"report": report.model_dump(mode="json"), "repairs": repairs,
                                                            "passed": report.passed and not coverage["unmapped"]})
    files["complexity_report.json"] = _w(out / "complexity_report.json", {
        "svg_bytes": len(text.encode()), "elements": text.count("<") - text.count("</") - 1,
        "objects": len(scene.objects), "gradients": len(scene.gradients),
        "note": "complexity is reported, not treated as evidence of quality"})
    summary: dict = {"status": "EVALUATED" if report.passed and not coverage["unmapped"] else "REJECTED",
                     "checks": {c.check: c.result.value for c in report.checks}, "repairs": len(repairs),
                     "telemetry": timings, "coverage": coverage["coverage"]}
    if variants:
        branches = brandmod.explore(scene, intent=intent, brand=brand, profile=profile, refs=manifest, axes=("motif", "material"),
                                    n=variants, seed=seed, render=_render, work_dir=work / "variants",
                                    renderer=rendermod.RENDERER, renderer_version=r["renderer_version"])
        vdir = out / "variants"
        vdir.mkdir(exist_ok=True)
        rows = []
        for b, vtext, vpng in branches:
            (vdir / f"{b.branch_id}.svg").write_text(vtext)
            if vpng:
                (vdir / f"{b.branch_id}.png").write_bytes(vpng)
            rows.append(b.model_dump(mode="json"))
        files["variants.json"] = _w(out / "variants.json", rows)
        summary["variants"] = {b.branch_id: b.status.value for b, _, _ in branches}
    if reference is not None:
        ref = png.decode(reference.read_bytes()) if reference.read_bytes()[:8] == png.SIGNATURE else None
        if ref is not None:
            bench = []
            for c in optimize.candidates(reference.read_bytes(), budgets=(16, 64, 256)):
                rr = _render(c["svg"], ref.width, ref.height, work / f"fidelity-{c['budget']}")
                measured = optimize.compare(ref, png.decode(rr["png"]), size=max(ref.width, ref.height)) if rr["png"] else {}
                (out / f"fidelity-{c['budget']}.svg").write_text(c["svg"])
                bench.append({k: v for k, v in c.items() if k != "svg"} | {"measured_full_resolution": measured,
                                                                           "profile": OutputProfile.NATIVE_FIDELITY_VECTOR.value})
            rows = [{"budget": b["budget"], "de": b["measured_full_resolution"].get("mean_delta_e76", 1e9), "bytes": b["svg_bytes"]}
                    for b in bench]
            files["benchmark_results.json"] = _w(out / "benchmark_results.json", {
                "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(), "renderer": rendermod.RENDERER,
                "renderer_version": r["renderer_version"], "candidates": bench,
                "pareto_front": [x["budget"] for x in optimize.pareto(rows, ("de", "bytes"))],
                "method": "error-driven region split + least-squares linear gradients (CPU, stdlib)",
                "not_implemented": list(optimize.PROPOSED_METHODS)})
            summary["fidelity"] = {b["budget"]: b["measured_full_resolution"].get("mean_delta_e76") for b in bench}
    files["provenance.json"] = _w(out / "provenance.json", {
        "compiler_version": COMPILER_VERSION, "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
        "renderer": rendermod.RENDERER, "renderer_version": r["renderer_version"], "requirement_hash": intent.requirement_hash,
        "intent_hash": intent.intent_hash, "scene_hash": scene.scene_hash, "brand_hash": brand.digest(),
        "references": [{"ref_id": x.ref_id, "sha256": x.sha256, "role": x.role.value} for x in manifest.references],
        "evidence": [e.model_dump(mode="json") for e in scene.evidence]})
    _w(out / "release.json", {"release_allowed": False, "external_effects": "none",
                              "reasons": ["LOCAL_RUN: approval and release need a project and a second person "
                                          "(service.request_approval + /approvals/{id}/decide)"],
                              "files": files})
    import shutil

    shutil.rmtree(work, ignore_errors=True)
    return (0 if summary["status"] == "EVALUATED" else 1), summary


__all__ = ["run_local"]
