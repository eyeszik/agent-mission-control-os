"""AVIC on Project OS: compile, edit, approval request and local release of one visual asset.

Storage is the existing Project OS artifact store through ``foundry.studio.store``
(content-addressed bytes, CAS versions, ``depends_on`` lineage, blast-radius
invalidation). Each stage is stored by its N3 role after ``assert_role_may_produce``.
Approval is ``intake.release.open_artifact_approval`` bound to the SVG's exact
content hash and decided only via ``/approvals/{id}/decide``; release is the shared
``artifact_release_verdict`` and never performs an external effect. No table,
migration, approval store or scheduler is added.

Failed candidates are never promoted: an edit whose evaluation fails (after bounded
repair) is returned as ``REJECTED`` and the stored head is left as it was.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry.studio import observe, store
from services.langgraph.agency.kernel.roles import assert_role_may_produce
from services.langgraph.agency.project_os.storage import StorageAdapter
from services.langgraph.agency.prompt_compiler import AssetRequirement
from services.langgraph.security.auth import Principal

from . import edits as edit_ops
from . import png
from . import references as refmod
from . import render as rendermod
from . import repair as repairmod
from . import svg
from .contracts import (COMPILER_VERSION, POLICY_VERSION, SCHEMA_VERSION, BrandIR, CandidateStatus, EvaluationReport, IntentIR,
                        ReleaseManifest, Result, SceneIR, VectorCandidate)
from .evaluate import evaluate
from .intent import compile_intent
from .materials import MaterialSpec
from .profiles import ProfileUnavailable, get_profile
from .scene import compile_scene, requirement_coverage

APPROVAL_POLICY = "amc-avic-approval/v1"
RUN_PIPELINE = "avic_visual"
ASSET_ID = r"^[a-z0-9][a-z0-9-]{0,39}$"

# Stage -> (N3 role, N1 artifact type, mime, release-package file name)
STAGES: dict[str, tuple[str, str, str, str]] = {
    "intent": ("creative_director", "asset_prompt_set", "application/json", "requirements.json"),
    "references": ("creative_director", "creative_concept", "application/json", "reference.json"),
    "brand": ("design_lead", "design_system_spec", "application/json", "brand.json"),
    "scene": ("creative_director", "creative_concept", "application/json", "scene.json"),
    "svg": ("creative_director", "media_asset", "image/svg+xml", "master.svg"),
    "preview": ("creative_director", "media_asset", "image/png", "preview.png"),
    "evaluation": ("brand_safety_reviewer", "qa_report", "application/json", "evaluation.json"),
    "provenance": ("brand_safety_reviewer", "qa_report", "application/json", "provenance.json"),
    "release": ("release_manager", "release_record", "application/json", "release.json"),
}


class AvicAccessDenied(PermissionError):
    pass


def _authorize(principal: Principal, project_id: str) -> None:
    from services.langgraph.persistence.projects import get_project_workspace

    ws = get_project_workspace(project_id)
    if ws is None or ws.tenant_id != principal.tenant_id or not principal.can_access_project(project_id):
        raise AvicAccessDenied("project is outside the principal's tenant or scope")


def _json(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def _put(principal: Principal, project_id: str, asset_id: str, stage: str, data: bytes, *, adapter: StorageAdapter,
         depends_on: tuple[str, ...] = (), expect_head_hash: Optional[str] = None) -> dict:
    """Store one stage after the N3 role check. Lineage and versions live in the records themselves (Project OS
    keeps only its own v2 metadata keys). ``expect_head_hash`` refuses a write over a head the caller never saw."""
    role, artifact_type, mime, filename = STAGES[stage]
    assert_role_may_produce(role, artifact_type)
    entry = store(principal, project_id, f"avic-{asset_id}-{stage}", data, mime=mime, artifact_type=artifact_type,
                  subtype=f"avic_{stage}", adapter=adapter, depends_on=depends_on, expect_head_hash=expect_head_hash)
    return {**entry, "stage": stage, "role": role, "file": filename, "sha256": hashlib.sha256(data).hexdigest()}


def _artifact_id(project_id: str, asset_id: str, stage: str) -> str:
    from services.langgraph.persistence.projects import project_artifact_id

    return project_artifact_id(project_id, f"foundry-avic-{asset_id}-{stage}")


def cache_identity(req: AssetRequirement, *, brand: BrandIR, style_profile: str, seed: int, reference_hashes: list[str],
                   material: Optional[MaterialSpec], output_profile: str, renderer_version: Optional[str]) -> str:
    return canonical_hash({"normalized_input": canonical_hash(req.model_dump(mode="json")), "brand": brand.digest(),
                           "style_profile": style_profile, "seed": seed, "references": sorted(reference_hashes),
                           "material": material.model_dump(mode="json") if material else None,
                           "compiler_version": COMPILER_VERSION, "renderer_version": renderer_version,
                           "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION, "output_profile": output_profile})


def _render_fn(work_dir: Path):
    return lambda text, w, h, d: rendermod.render(text, width=w, height=h, work_dir=d)


# Chromium's software rasterizer is not bit-exact across runs: identical SVG has been measured to differ by up to
# 2/255 per channel on ~1% of pixels (soft blurs, gradients). Within this tolerance a stored preview of the same SVG
# is reused, so identical inputs stay idempotent; anything larger is a real change.
RENDER_TOLERANCE = 2
TELEMETRY_ONLY = frozenset({"render_variance_vs_stored", "renderer_status"})


def _produce(scene: SceneIR, intent: IntentIR, brand: BrandIR, work_dir: Path, *, parent_svg: Optional[str] = None,
             stored: Optional[tuple[str, bytes]] = None
             ) -> tuple[SceneIR, str, Optional[bytes], EvaluationReport, list[dict], dict]:
    """Emit, render, evaluate; on failure run bounded H3 repair. Returns the best scene and its evidence.

    ``stored`` is ``(svg_sha256, preview_png)`` of the current head, reused when this render matches it within
    ``RENDER_TOLERANCE``.
    """
    t0 = time.perf_counter()
    text = svg.emit(scene)
    compile_ms = round((time.perf_counter() - t0) * 1000, 1)
    r = rendermod.render(text, width=scene.document.width, height=scene.document.height, work_dir=work_dir / "render")
    variance = None
    if stored and r["png"] and stored[0] == hashlib.sha256(text.encode()).hexdigest():
        variance = png.max_channel_difference(r["png"], stored[1])
        if variance is not None and variance <= RENDER_TOLERANCE:
            r = {**r, "png": stored[1]}
    t1 = time.perf_counter()
    report = evaluate(scene, text, intent=intent, brand=brand, png_bytes=r["png"], renderer=rendermod.RENDERER,
                      renderer_version=r["renderer_version"], parent_svg=parent_svg)
    # Latencies are measured but variable: they go to the caller (telemetry), never into content-addressed records.
    metrics = {"compile_latency_ms": compile_ms, "render_latency_ms": r["render_ms"],
               "verify_latency_ms": round((time.perf_counter() - t1) * 1000, 1), "svg_bytes": len(text.encode()),
               "svg_elements": text.count("<") - text.count("</") - 1, "repair_attempts": 0,
               "render_variance_vs_stored": variance}
    repairs: list[dict] = []
    png_bytes = r["png"]
    if report.failures() and r["status"] == "PASSED":
        outcomes, missing = repairmod.repair(scene, text, report, brand=brand, intent=intent, render=_render_fn(work_dir),
                                             work_dir=work_dir / "repair", renderer=rendermod.RENDERER,
                                             renderer_version=r["renderer_version"])
        for o in outcomes:
            repairs.append({"defect": o.defect.model_dump(mode="json"), "accepted": o.accepted, "attempts": o.attempts,
                            "proposal": o.proposal.model_dump(mode="json") if o.proposal else None})
            metrics["repair_attempts"] += len(o.attempts)
            if o.accepted and o.scene is not None:
                scene, text, png_bytes, report = o.scene, o.svg_text or text, o.png, o.report or report
        metrics["missing_evidence"] = list(missing)
    metrics["repair_success_rate"] = (round(sum(x["accepted"] for x in repairs) / len(repairs), 3) if repairs else None)
    return scene, text, png_bytes, report, repairs, {**metrics, "renderer_status": r["status"]}


def compile_asset(principal: Principal, project_id: str, req: AssetRequirement, *, brand: BrandIR, style_profile: str,
                  adapter: StorageAdapter, work_dir: Path, references: tuple[refmod.ReferenceInput, ...] = (), seed: int = 0,
                  material: Optional[MaterialSpec] = None) -> dict:
    """INGEST .. EVALUATE (+ bounded repair) .. persist. Returns stage entries, evaluation and candidate."""
    _authorize(principal, project_id)
    import re

    if not re.fullmatch(ASSET_ID, req.asset_id):
        raise ValueError(f"asset_id must match {ASSET_ID}")
    intent = compile_intent(req, style_profile=style_profile)
    blocked = intent.blocked()
    if blocked:
        return {"status": "BLOCKED", "reasons": [f"{i.item_id}:{i.classification.value}:{i.reason}" for i in blocked],
                "intent": intent.model_dump(mode="json")}
    try:
        profile = get_profile(style_profile)
    except ProfileUnavailable as exc:
        return {"status": "BLOCKED", "reasons": [str(exc)], "intent": intent.model_dump(mode="json")}
    if not brand.approved:
        brand_note = "brand projection is not approved; outputs stay unapprovable until a human approves the release"
    else:
        brand_note = "approved brand projection"
    manifest, ref_evidence = refmod.analyze(list(references))
    scene = compile_scene(intent, brand, profile, manifest, seed=seed, material=material, reference_evidence=ref_evidence)
    coverage = requirement_coverage(intent, scene)
    work = work_dir / f"{req.asset_id}-{scene.scene_hash[:12]}"
    stored = None
    try:
        old_svg, _ = observe(_artifact_id(project_id, req.asset_id, "svg"), adapter)
        old_png, _ = observe(_artifact_id(project_id, req.asset_id, "preview"), adapter)
        stored = (hashlib.sha256(old_svg).hexdigest(), old_png)
    except LookupError:
        pass
    scene, text, png_bytes, report, repairs, metrics = _produce(scene, intent, brand, work, stored=stored)
    key = cache_identity(req, brand=brand, style_profile=style_profile, seed=seed,
                         reference_hashes=[r.sha256 for r in manifest.references], material=material,
                         output_profile=intent.output_profile.value, renderer_version=report.renderer_version)
    # Cache divergence: the same identity must give the same bytes as the stored head.
    divergence = None
    try:  # Project OS keeps only its own v2 keys, so the identity lives in the stored provenance record.
        prov = json.loads(observe(_artifact_id(project_id, req.asset_id, "provenance"), adapter)[0])
        old_svg = prov.get("files", {}).get("svg", {}).get("sha256")
        if prov.get("cache_identity") == key and old_svg and old_svg != hashlib.sha256(text.encode()).hexdigest():
            divergence = "CACHE_DIVERGENCE: same identity, different SVG bytes"
    except LookupError:
        pass
    if divergence:
        return {"status": "REJECTED", "reasons": [divergence]}
    passed = report.passed and not coverage["unmapped"]
    from services.langgraph.persistence.agency_kernel import get_artifact

    if not passed and get_artifact(_artifact_id(project_id, req.asset_id, "svg")) is not None:
        # Never replace an existing head with a failed candidate: report it and keep the parent.
        return {"status": "REJECTED", "parent_kept": True, "evaluation": report.model_dump(mode="json"), "coverage": coverage,
                "repairs": repairs, "reasons": [f"{c.check}:{c.result.value}" for c in report.failures()] +
                [f"UNMAPPED:{u}" for u in coverage["unmapped"]]}
    entries: dict[str, dict] = {}
    entries["intent"] = _put(principal, project_id, req.asset_id, "intent", _json({"requirement": req.model_dump(mode="json"),
                             "intent": intent.model_dump(mode="json"), "coverage": coverage}), adapter=adapter)
    entries["brand"] = _put(principal, project_id, req.asset_id, "brand", _json({**brand.model_dump(mode="json"),
                            "authority": "PROJECTION", "note": brand_note}), adapter=adapter)
    entries["references"] = _put(principal, project_id, req.asset_id, "references", _json(manifest.model_dump(mode="json")),
                                 adapter=adapter)
    up = tuple(entries[k]["artifact_id"] for k in ("intent", "brand", "references"))
    entries["scene"] = _put(principal, project_id, req.asset_id, "scene", _json(scene.model_dump(mode="json")), adapter=adapter,
                            depends_on=up)
    entries["svg"] = _put(principal, project_id, req.asset_id, "svg", text.encode(), adapter=adapter,
                          depends_on=(entries["scene"]["artifact_id"],))
    if png_bytes is not None:
        entries["preview"] = _put(principal, project_id, req.asset_id, "preview", png_bytes, adapter=adapter,
                                  depends_on=(entries["svg"]["artifact_id"],))
    status = "EVALUATED" if passed else ("BLOCKED" if png_bytes is None else "REJECTED")
    candidate = VectorCandidate(candidate_id="cand-" + scene.scene_hash[:16], scene_hash=scene.scene_hash,
                                svg_sha256=report.svg_sha256, output_profile=intent.output_profile,
                                status=CandidateStatus.EVALUATED if status == "EVALUATED" else CandidateStatus.REJECTED,
                                evaluation_hash=report.digest(),
                                metrics={k: v for k, v in metrics.items() if k not in TELEMETRY_ONLY and
                                         not k.endswith("_latency_ms")})
    entries["evaluation"] = _put(principal, project_id, req.asset_id, "evaluation", _json({
        "report": report.model_dump(mode="json"), "coverage": coverage, "repairs": repairs, "candidate":
        candidate.model_dump(mode="json"), "passed": status == "EVALUATED"}), adapter=adapter,
        depends_on=tuple(entries[k]["artifact_id"] for k in ("svg", "preview") if k in entries))
    entries["provenance"] = _put(principal, project_id, req.asset_id, "provenance", _json({
        "compiler_version": COMPILER_VERSION, "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
        "renderer": rendermod.RENDERER, "renderer_version": report.renderer_version, "cache_identity": key,
        "requirement_hash": intent.requirement_hash, "intent_hash": intent.intent_hash, "scene_hash": scene.scene_hash,
        "brand": {"source": brand.source, "hash": brand.digest(), "approved": brand.approved},
        "references": [{"ref_id": r.ref_id, "sha256": r.sha256, "role": r.role.value} for r in manifest.references],
        "excluded_references": list(manifest.excluded), "evidence": [e.model_dump(mode="json") for e in scene.evidence],
        "files": {k: {"artifact_id": v["artifact_id"], "version": v["version"], "sha256": v["sha256"]} for k, v in entries.items()},
    }), adapter=adapter, depends_on=(entries["evaluation"]["artifact_id"],))
    return {"status": status, "asset_id": req.asset_id, "candidate": candidate.model_dump(mode="json"),
            "evaluation": report.model_dump(mode="json"), "coverage": coverage, "repairs": repairs, "metrics": metrics,
            "artifacts": {k: {f: v[f] for f in ("artifact_id", "version", "action", "sha256", "role", "file")}
                          for k, v in entries.items()}}


def _load(project_id: str, asset_id: str, adapter: StorageAdapter) -> tuple[IntentIR, BrandIR, SceneIR, str, dict[str, str]]:
    """Read the inputs of a change. The last value is the content hash of each head read (the CAS base for writes)."""
    intent_doc, _ = observe(_artifact_id(project_id, asset_id, "intent"), adapter)
    brand_doc, _ = observe(_artifact_id(project_id, asset_id, "brand"), adapter)
    scene_doc, _ = observe(_artifact_id(project_id, asset_id, "scene"), adapter)
    svg_bytes, _ = observe(_artifact_id(project_id, asset_id, "svg"), adapter)
    b = json.loads(brand_doc)
    b.pop("authority", None)
    b.pop("note", None)
    heads = {"scene": hashlib.sha256(scene_doc).hexdigest(), "svg": hashlib.sha256(svg_bytes).hexdigest()}
    return (IntentIR.model_validate(json.loads(intent_doc)["intent"]), BrandIR.model_validate(b),
            SceneIR.model_validate(json.loads(scene_doc)), svg_bytes.decode(), heads)


def _commit(principal: Principal, project_id: str, asset_id: str, *, intent: IntentIR, scene: SceneIR, text: str,
            png_bytes: bytes, report: EvaluationReport, repairs: list[dict], adapter: StorageAdapter, tag: dict,
            expect: Optional[dict[str, str]], prov_edit: Optional[dict] = None) -> dict[str, dict]:
    """Write the derived stages in dependency order. The scene is the commit record: every later stage is a pure
    function of it, so a crash part-way leaves stages that ``consistency`` detects and ``recompile_asset`` re-derives.
    ``expect`` holds the head hashes the change was computed from; a mismatch raises ``StaleArtifactVersionError``."""
    expect = expect or {}
    e: dict[str, dict] = {}
    e["scene"] = _put(principal, project_id, asset_id, "scene", _json(scene.model_dump(mode="json")), adapter=adapter,
                      expect_head_hash=expect.get("scene"))
    e["svg"] = _put(principal, project_id, asset_id, "svg", text.encode(), adapter=adapter, expect_head_hash=expect.get("svg"))
    e["preview"] = _put(principal, project_id, asset_id, "preview", png_bytes, adapter=adapter)
    e["evaluation"] = _put(principal, project_id, asset_id, "evaluation", _json({
        "report": report.model_dump(mode="json"), "coverage": requirement_coverage(intent, scene), "repairs": repairs,
        **tag, "passed": True}), adapter=adapter)
    prov = json.loads(observe(_artifact_id(project_id, asset_id, "provenance"), adapter)[0])
    identity = prov.get("cache_identity") if prov.get("scene_hash") == scene.scene_hash else None
    e["provenance"] = _put(principal, project_id, asset_id, "provenance", _json({
        **prov, **({"edits": [*prov.get("edits", []), prov_edit]} if prov_edit else {}), "cache_identity": identity, "scene_hash": scene.scene_hash,
        "renderer_version": report.renderer_version,
        "files": {**prov.get("files", {}), **{k: {"artifact_id": v["artifact_id"], "version": v["version"], "sha256": v["sha256"]}
                                              for k, v in e.items() if k != "provenance"}}}), adapter=adapter)
    return e


def _artifacts_view(entries: dict[str, dict]) -> dict:
    return {k: {f: v[f] for f in ("artifact_id", "version", "action", "sha256")} for k, v in entries.items()}


def edit_asset(principal: Principal, project_id: str, asset_id: str, *, op: str, args: dict, adapter: StorageAdapter,
               work_dir: Path, base_svg_sha256: Optional[str] = None) -> dict:
    """Apply one edit; store it only when the independent evaluation passes. Otherwise keep the parent head.

    ``base_svg_sha256`` is the SVG the operator was looking at. If the head has moved on, nothing is stored and the
    result is ``CONFLICT``. Writes also carry the head hashes read here, so a writer that slips in between the read
    and the write is detected too (never silently overwritten).
    """
    from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError

    _authorize(principal, project_id)
    intent, brand, scene, parent_svg, heads = _load(project_id, asset_id, adapter)
    if base_svg_sha256 is not None and base_svg_sha256 != heads["svg"]:
        return {"status": "CONFLICT", "reasons": ["STALE_BASE: the SVG changed after it was opened; reload and re-apply"],
                "head_svg_sha256": heads["svg"]}
    try:
        if op == "recolor":
            child, records = edit_ops.recolor(scene, brand, args["object_id"], args["palette_key"], field=args.get("field", "fill"))
        elif op == "change_text":
            child, records = edit_ops.change_text(scene, intent, args["object_id"], args["text"])
        elif op == "set_geometry":
            child, records = edit_ops.set_geometry(scene, args["object_id"], args["params"])
        else:
            return {"status": "REJECTED", "reasons": [f"unknown operation {op!r}"]}
    except edit_ops.EditRejected as exc:
        return {"status": "REJECTED", "reasons": [str(exc)]}
    child, text, png_bytes, report, repairs, metrics = _produce(child, intent, brand, work_dir / f"edit-{child.scene_hash[:12]}",
                                                          parent_svg=parent_svg)
    if not report.passed or png_bytes is None:
        return {"status": "REJECTED", "reasons": [f"{c.check}:{c.result.value}" for c in report.failures()] or ["NOT_RENDERED"],
                "evaluation": report.model_dump(mode="json"), "repairs": repairs, "parent_kept": True}
    edit_record = {"op": op, "parent_svg_sha256": heads["svg"], "transformations": [r.model_dump(mode="json") for r in records]}
    try:
        e = _commit(principal, project_id, asset_id, intent=intent, scene=child, text=text, png_bytes=png_bytes, report=report,
                    repairs=repairs, adapter=adapter, tag={"edit": op}, expect=heads, prov_edit=edit_record)
    except StaleArtifactVersionError as exc:
        return {"status": "CONFLICT", "reasons": [f"STALE_BASE: {exc}"]}
    return {"status": "EVALUATED", "transformations": [r.model_dump(mode="json") for r in records], "metrics": metrics,
            "artifacts": _artifacts_view({k: v for k, v in e.items() if k != "provenance"})}


def consistency(project_id: str, asset_id: str, *, adapter: StorageAdapter) -> dict:
    """Is every derived stage still a function of the scene (the commit record)? ``stale`` names the ones that are not."""
    scene_bytes, _ = observe(_artifact_id(project_id, asset_id, "scene"), adapter)
    scene = SceneIR.model_validate(json.loads(scene_bytes))
    stale: list[str] = []
    svg_bytes, _ = observe(_artifact_id(project_id, asset_id, "svg"), adapter)
    try:
        svg_ok = svg.emit(scene).encode() == svg_bytes
    except Exception:  # an unemittable scene cannot match any stored SVG
        svg_ok = False
    sha = hashlib.sha256(svg_bytes).hexdigest()
    if not svg_ok:
        stale.append("svg")
    evaluation = json.loads(observe(_artifact_id(project_id, asset_id, "evaluation"), adapter)[0])
    rep = evaluation.get("report", {})
    eval_ok = svg_ok and rep.get("scene_hash") == scene.scene_hash and rep.get("svg_sha256") == sha
    if not eval_ok:
        stale.append("evaluation")
    try:
        preview_bytes, _ = observe(_artifact_id(project_id, asset_id, "preview"), adapter)
        preview_ok = eval_ok and rep.get("png_sha256") == hashlib.sha256(preview_bytes).hexdigest()
    except LookupError:
        preview_ok = False
    if not preview_ok:
        stale.append("preview")
    prov = json.loads(observe(_artifact_id(project_id, asset_id, "provenance"), adapter)[0])
    if prov.get("scene_hash") != scene.scene_hash:
        stale.append("provenance")
    return {"consistent": not stale, "stale": stale}


def recompile_asset(principal: Principal, project_id: str, asset_id: str, *, adapter: StorageAdapter, work_dir: Path) -> dict:
    """Re-derive svg, preview, evaluation and provenance from the stored scene. The recovery path after a crash or a
    conflict that left stages behind; idempotent when nothing is stale."""
    from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError

    _authorize(principal, project_id)
    intent, brand, scene, _svg_text, heads = _load(project_id, asset_id, adapter)
    stored = None
    try:  # a stored preview is only a valid reuse candidate if the evaluation ties it to the stored SVG
        ev = json.loads(observe(_artifact_id(project_id, asset_id, "evaluation"), adapter)[0])["report"]
        old_png, _ = observe(_artifact_id(project_id, asset_id, "preview"), adapter)
        if ev.get("svg_sha256") == heads["svg"] and ev.get("png_sha256") == hashlib.sha256(old_png).hexdigest():
            stored = (heads["svg"], old_png)
    except (LookupError, KeyError, ValueError):
        pass
    scene2, text, png_bytes, report, repairs, metrics = _produce(scene, intent, brand, work_dir / f"recompile-{scene.scene_hash[:12]}",
                                                                 stored=stored)
    if not report.passed or png_bytes is None:
        return {"status": "REJECTED", "reasons": [f"{c.check}:{c.result.value}" for c in report.failures()] or ["NOT_RENDERED"],
                "evaluation": report.model_dump(mode="json"), "repairs": repairs}
    try:
        e = _commit(principal, project_id, asset_id, intent=intent, scene=scene2, text=text, png_bytes=png_bytes, report=report,
                    repairs=repairs, adapter=adapter, tag={"recompiled_from_scene": True}, expect=heads)
    except StaleArtifactVersionError as exc:
        return {"status": "CONFLICT", "reasons": [f"STALE_BASE: {exc}"]}
    return {"status": "EVALUATED", "metrics": metrics, "artifacts": _artifacts_view(e)}


def _verified(project_id: str, asset_id: str, adapter: StorageAdapter) -> tuple[dict, dict, str]:
    """Re-read the stored SVG and evaluation and re-validate the bytes now (Q7/Q8): stale or tampered bytes fail."""
    from services.langgraph.agency.project_os.storage import StorageIntegrityError
    from services.langgraph.persistence.agency_kernel import get_artifact

    try:
        svg_bytes, svg_head = observe(_artifact_id(project_id, asset_id, "svg"), adapter)
    except StorageIntegrityError:
        head = get_artifact(_artifact_id(project_id, asset_id, "svg")) or {}
        return head, {"report": {"svg_sha256": head.get("content_hash")}}, "STORED_BYTES_MISMATCH"
    eval_bytes, _ = observe(_artifact_id(project_id, asset_id, "evaluation"), adapter)
    evaluation = json.loads(eval_bytes)
    sha = hashlib.sha256(svg_bytes).hexdigest()
    problems = []
    if sha != svg_head.get("content_hash"):
        problems.append("STORED_BYTES_MISMATCH")
    if evaluation["report"]["svg_sha256"] != sha:
        problems.append("EVALUATION_STALE: the SVG changed after it was evaluated")
    if not evaluation.get("passed"):
        problems.append("EVALUATION_NOT_PASSED")
    scene = SceneIR.model_validate(json.loads(observe(_artifact_id(project_id, asset_id, "scene"), adapter)[0]))
    if evaluation["report"].get("scene_hash") != scene.scene_hash:
        problems.append("EVALUATION_SCENE_MISMATCH: the scene changed after it was evaluated")
    recheck = svg.validate(svg_bytes.decode(), profile=scene.document.output_profile, max_bytes=scene.compilation.max_svg_bytes)
    problems += [f"REVALIDATION:{c.check}" for c in recheck if c.result != Result.PASS]
    return svg_head, evaluation, ";".join(problems)


def request_approval(principal: Principal, project_id: str, asset_id: str, *, adapter: StorageAdapter) -> dict:
    from services.langgraph.agency.intake.release import open_artifact_approval

    _authorize(principal, project_id)
    head, evaluation, problems = _verified(project_id, asset_id, adapter)
    if problems:
        return {"status": "BLOCKED", "reasons": problems.split(";")}
    opened = open_artifact_approval(
        principal, tenant_id=principal.tenant_id, project_id=project_id, mission_id=f"{project_id}:avic:{asset_id}",
        contract_hash=canonical_hash({"artifact": head["artifact_id"], "policy": APPROVAL_POLICY}),
        artifact_id=head["artifact_id"], version=int(head["version"]), content_hash=head["content_hash"],
        run_pipeline=RUN_PIPELINE, policy_version=APPROVAL_POLICY, subject_type="CREATIVE_ARTIFACT",
        reason="Compiled SVG requires human visual, brand and accessibility review before local release",
        metadata={"compiler_version": COMPILER_VERSION, "evaluation_svg_sha256": evaluation["report"]["svg_sha256"]})
    return {**opened, "status": "PENDING", "approval_status": opened.get("status")}


def release_local(principal: Principal, project_id: str, asset_id: str, *, approval_id: Optional[str],
                  adapter: StorageAdapter) -> dict:
    """Seal a local release record. Allowed only for a verified, current, human-approved SVG. No external effect."""
    from services.langgraph.agency.intake.release import artifact_release_verdict

    _authorize(principal, project_id)
    head, evaluation, problems = _verified(project_id, asset_id, adapter)
    if "STORED_BYTES_MISMATCH" in problems:
        return {"status": "BLOCKED", "reasons": problems.split(";"), "manifest": None}
    verdict = artifact_release_verdict(simulated=False, verification_passed=not problems, artifact_id=head["artifact_id"],
                                       verified_version=int(head["version"]), verified_hash=evaluation["report"]["svg_sha256"],
                                       approval_id=approval_id, tenant_id=principal.tenant_id, project_id=project_id)
    files = {}
    for stage in ("intent", "references", "brand", "scene", "svg", "preview", "evaluation", "provenance"):
        try:
            data, h = observe(_artifact_id(project_id, asset_id, stage), adapter)
        except LookupError:
            continue
        files[STAGES[stage][3]] = {"artifact_id": h["artifact_id"], "version": int(h["version"]),
                                   "sha256": hashlib.sha256(data).hexdigest()}
    report = evaluation["report"]
    reasons = tuple(verdict.reasons) + tuple(p for p in problems.split(";") if p)
    manifest = ReleaseManifest(project_id=project_id, output_profile=json.loads(observe(_artifact_id(
        project_id, asset_id, "scene"), adapter)[0])["document"]["output_profile"], renderer=report["renderer"],
        renderer_version=report.get("renderer_version"), files=files,
        source_hashes={"svg": report["svg_sha256"], "png": report.get("png_sha256") or "", "scene": report["scene_hash"]},
        quality={c["check"]: c["result"] for c in report["checks"]}, approval_id=approval_id,
        release_allowed=bool(verdict.allowed) and not problems, release_reasons=reasons)
    entry = _put(principal, project_id, asset_id, "release", _json(manifest.model_dump(mode="json")), adapter=adapter,
                 depends_on=(head["artifact_id"],))
    return {"status": "RELEASED_LOCAL" if manifest.release_allowed else "BLOCKED", "reasons": list(reasons),
            "manifest": manifest.model_dump(mode="json"), "artifact": {k: entry[k] for k in ("artifact_id", "version", "sha256")}}


def export_package(project_id: str, asset_id: str, *, adapter: StorageAdapter, out_dir: Path) -> dict[str, str]:
    """Write the stored release package files to ``out_dir`` (read-back of stored bytes, for local inspection)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for stage, (_, _, _, filename) in STAGES.items():
        try:
            data, _ = observe(_artifact_id(project_id, asset_id, stage), adapter)
        except LookupError:
            continue
        (out_dir / filename).write_bytes(data)
        written[filename] = hashlib.sha256(data).hexdigest()
    return written


__all__ = ["APPROVAL_POLICY", "AvicAccessDenied", "RUN_PIPELINE", "STAGES", "cache_identity", "compile_asset", "consistency",
           "edit_asset", "export_package", "recompile_asset", "release_local", "request_approval"]
