"""H3 causal visual repair: defect -> dependency hypothesis -> proposal -> isolated render -> independent evaluation.

* A defect comes only from a failed independent check, with the evaluation as
  evidence. Causes are listed as hypotheses. A check that could not run is reported
  as missing evidence, never turned into a defect or a pass.
* A proposal changes the smallest set of objects: the defect's target plus the
  objects that depend on it (``dependency_closure``). Protected geometry is never in
  a transformation; exact text can only be restored to the brief, never rewritten.
* The repaired scene is re-emitted in full and compared with the parent: any element
  outside the declared affected set that changed is cache divergence, and the repair
  is rejected. The repair is rendered in its own work directory and evaluated by the
  same independent evaluator; it is accepted only when the targeted check passes and
  no check that passed before now fails. Otherwise the parent is kept (rollback).
* At most ``MAX_ATTEMPTS`` proposals per defect. A repaired scene is a new candidate:
  it never inherits the parent's approval (approvals bind to content hashes).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from services.langgraph.agency.execution_fabric.verifiers import delta_e76
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from . import svg
from .contracts import (BrandIR, DefectIR, EvaluationReport, IntentIR, RepairProposal, Result, SceneIR, TransformationRecord)
from .evaluate import evaluate
from .scene import GLYPH_ADVANCE_EM

MAX_ATTEMPTS = 3
Renderer = Callable[[str, int, int, Path], dict]


def dependency_closure(scene: SceneIR, roots: set[str]) -> tuple[str, ...]:
    """``roots`` plus every object that (transitively) depends on, is parented by, or clips to them."""
    out = set(roots)
    changed = True
    while changed:
        changed = False
        for o in scene.objects:
            if o.object_id in out:
                continue
            links = set(o.dependencies) | ({o.parent_id} if o.parent_id else set()) | (
                {o.geometry.clip_to} if o.geometry.clip_to else set())
            if links & out:
                out.add(o.object_id)
                changed = True
    return tuple(o.object_id for o in scene.objects if o.object_id in out)


def _defect_id(*parts: str) -> str:
    return "def-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def detect(scene: SceneIR, report: EvaluationReport, brand: BrandIR) -> tuple[tuple[DefectIR, ...], tuple[str, ...]]:
    """(defects, missing_evidence). Only FAILed checks become defects."""
    ev = f"evaluation:{report.digest()}"
    defects: list[DefectIR] = []
    missing = tuple(f"{c.check}:{c.result.value}" for c in report.checks if c.result in {Result.BLOCKED, Result.NOT_MEASURED})
    constraints = {c.constraint_id: c for c in scene.constraints}
    for c in report.checks:
        if c.result != Result.FAIL:
            continue
        refs = (f"{ev}#{c.check}",)
        if c.check.startswith("contrast."):
            target = constraints[c.check].target[0]
            defects.append(DefectIR(defect_id=_defect_id(scene.scene_hash, c.check), artifact_version=scene.scene_hash,
                                    kind="contrast", region_refs=(target,), requirement_refs=scene.object(target).requirement_refs,
                                    symptoms=c.detail, evidence_refs=refs,
                                    candidate_causes=(f"{target} colour too close in luminance to the ground",
                                                      "the ground colour changed upstream"),
                                    confidence=0.9, severity="CRITICAL",
                                    dependency_refs=dependency_closure(scene, {target}),
                                    repair_options=("recolor the foreground to the highest-contrast palette colour",),
                                    verification_plan=f"re-render and re-run {c.check}"))
        elif c.check == "palette":
            offenders = [o.object_id for o in scene.objects if any(
                p and p.startswith("#") and min(delta_e76(p, q) for q in brand.palette.values()) > 2.3
                for p in (o.appearance.fill, o.appearance.stroke))]
            defects.append(DefectIR(defect_id=_defect_id(scene.scene_hash, c.check), artifact_version=scene.scene_hash,
                                    kind="off_palette", region_refs=tuple(offenders) or ("document",), symptoms=c.detail,
                                    evidence_refs=refs, candidate_causes=("a colour was introduced outside the brand palette",),
                                    confidence=0.95, severity="CRITICAL",
                                    dependency_refs=dependency_closure(scene, set(offenders)),
                                    repair_options=("snap each off-palette colour to its nearest palette colour",),
                                    verification_plan="re-run palette conformance"))
        elif c.check == "accent_budget":
            defects.append(DefectIR(defect_id=_defect_id(scene.scene_hash, c.check), artifact_version=scene.scene_hash,
                                    kind="accent_budget", region_refs=("document",), symptoms=c.detail, evidence_refs=refs,
                                    candidate_causes=("a second accent was introduced by an edit or variant",),
                                    confidence=0.9, severity="MAJOR",
                                    repair_options=("recolor every non-primary accent to the ink colour",),
                                    verification_plan="re-run accent budget"))
        elif c.check.startswith("text_fit."):
            target = c.check.split(".", 1)[1]
            defects.append(DefectIR(defect_id=_defect_id(scene.scene_hash, c.check), artifact_version=scene.scene_hash,
                                    kind="text_overflow", region_refs=(target,), requirement_refs=scene.object(target).requirement_refs,
                                    symptoms=c.detail, evidence_refs=refs,
                                    candidate_causes=("font size too large for the line length", "text was lengthened"),
                                    confidence=0.7, severity="MAJOR", dependency_refs=dependency_closure(scene, {target}),
                                    repair_options=("reduce the font size until the estimated line fits",),
                                    verification_plan=f"re-run {c.check} and confirm the text still renders"))
        elif c.check.startswith("exact_text."):
            target = c.check.split(".", 1)[1]
            defects.append(DefectIR(defect_id=_defect_id(scene.scene_hash, c.check), artifact_version=scene.scene_hash,
                                    kind="exact_text", region_refs=(target,), requirement_refs=scene.object(target).requirement_refs,
                                    symptoms=c.detail, evidence_refs=refs, candidate_causes=("the text was edited away from the brief",),
                                    confidence=1.0, severity="CRITICAL",
                                    repair_options=("restore the exact text from the brief",),
                                    verification_plan=f"re-run {c.check}"))
        elif c.check in {"nonblank", "headline_rendered"}:
            defects.append(DefectIR(defect_id=_defect_id(scene.scene_hash, c.check), artifact_version=scene.scene_hash,
                                    kind="blank_render", region_refs=("document",), symptoms=c.detail, evidence_refs=refs,
                                    candidate_causes=("the renderer painted nothing", "objects are transparent or off-canvas",
                                                      "the font is unavailable to the renderer"),
                                    confidence=0.5, severity="CRITICAL", repair_options=(),
                                    verification_plan="human review of the preview; no automatic repair"))
    return tuple(defects), missing


def propose(scene: SceneIR, defect: DefectIR, *, brand: BrandIR, intent: IntentIR, attempt: int) -> Optional[RepairProposal]:
    ground = scene.object("background").appearance.fill if any(o.object_id == "background" for o in scene.objects) else None
    recs: list[TransformationRecord] = []
    protected = {o.object_id for o in scene.objects if o.protected}
    if defect.kind == "contrast" and ground and ground.startswith("#"):
        target = scene.object(defect.region_refs[0])
        fld = "fill" if (target.appearance.fill or "none").startswith("#") else "stroke"
        current = getattr(target.appearance, fld)
        ranked = sorted(brand.palette.values(), key=lambda h: -wcag_contrast_ratio(h, ground))
        choice = ranked[min(attempt - 1, len(ranked) - 1)]
        if choice != current:
            recs.append(TransformationRecord(object_id=target.object_id, field=f"appearance.{fld}", before=current, after=choice))
    elif defect.kind == "off_palette":
        for oid in defect.region_refs:
            if oid == "document":
                continue
            o = scene.object(oid)
            for fld in ("fill", "stroke"):
                v = getattr(o.appearance, fld)
                if v and v.startswith("#") and min(delta_e76(v, q) for q in brand.palette.values()) > 2.3:
                    recs.append(TransformationRecord(object_id=oid, field=f"appearance.{fld}", before=v,
                                                     after=min(brand.palette.values(), key=lambda q: delta_e76(v, q))))
    elif defect.kind == "accent_budget":
        primary = brand.palette.get(brand.roles.get("accent", ""), None)
        accents = {brand.palette[k] for r, k in brand.roles.items() if r.startswith("accent")} - {primary}
        ink = brand.palette[brand.roles["ink"]]
        for o in scene.objects:
            for fld in ("fill", "stroke"):
                if getattr(o.appearance, fld) in accents:
                    recs.append(TransformationRecord(object_id=o.object_id, field=f"appearance.{fld}",
                                                     before=getattr(o.appearance, fld), after=ink))
    elif defect.kind == "text_overflow":
        o = scene.object(defect.region_refs[0])
        avail = scene.document.width - o.geometry.params["x"] - scene.composition.margin
        size = round(avail / max(1, len(o.text or "") * GLYPH_ADVANCE_EM) * (1 - 0.04 * (attempt - 1)), 2)
        if o.appearance.font_size and size < o.appearance.font_size and size >= 8:
            recs.append(TransformationRecord(object_id=o.object_id, field="appearance.font_size", before=o.appearance.font_size,
                                             after=size))
    elif defect.kind == "exact_text":
        o = scene.object(defect.region_refs[0])
        exact = dict(zip(intent.exact_text_ids(), intent.exact_text))
        want = next((exact[r] for r in o.requirement_refs if r in exact), None)
        if want is not None and want != o.text:
            recs.append(TransformationRecord(object_id=o.object_id, field="text", before=o.text, after=want))
    if not recs:
        return None
    for r in recs:  # protected-region invariance: a repair may recolour or restore, never move protected geometry
        if r.object_id in protected and r.field.startswith("geometry"):
            return None
    affected = dependency_closure(scene, {r.object_id for r in recs})
    pid = "rep-" + hashlib.sha256(f"{defect.defect_id}|{attempt}|{recs}".encode()).hexdigest()[:12]
    return RepairProposal(proposal_id=pid, defect_id=defect.defect_id, parent_scene_hash=scene.scene_hash, affected=affected,
                          transformations=tuple(recs), hypothesis=defect.candidate_causes[0],
                          rebuild="incremental" if len(affected) < len(scene.objects) else "full", attempt=attempt)


def apply(scene: SceneIR, proposal: RepairProposal) -> SceneIR:
    if proposal.parent_scene_hash != scene.scene_hash:
        raise ValueError("proposal was made for a different scene version")
    objs = {o.object_id: o for o in scene.objects}
    for t in proposal.transformations:
        o = objs[t.object_id]
        if t.field == "text":
            o = o.model_copy(update={"text": t.after})
        elif t.field.startswith("appearance."):
            o = o.model_copy(update={"appearance": o.appearance.model_copy(update={t.field.split(".", 1)[1]: t.after})})
        else:
            raise ValueError(f"repair cannot change {t.field}")
        objs[t.object_id] = o
    return SceneIR.model_validate(scene.model_copy(update={"objects": tuple(objs[o.object_id] for o in scene.objects)}).model_dump())


def divergence(parent_svg: str, child_svg: str, affected: tuple[str, ...]) -> list[str]:
    """Element ids outside ``affected`` whose attributes or text changed: unintended change (cache divergence)."""
    from xml.etree import ElementTree as ET

    def table(text: str) -> dict[str, tuple]:
        return {el.attrib["id"]: (tuple(sorted(el.attrib.items())), "".join(el.itertext()) if el.tag.endswith("text") else None)
                for el in ET.fromstring(text).iter() if "id" in el.attrib}
    a, b = table(parent_svg), table(child_svg)
    allowed = set(affected) | {"avic-title"}
    return sorted(k for k in set(a) | set(b) if k not in allowed and a.get(k) != b.get(k))


@dataclass
class RepairOutcome:
    defect: DefectIR
    accepted: bool
    proposal: Optional[RepairProposal] = None
    scene: Optional[SceneIR] = None
    svg_text: Optional[str] = None
    png: Optional[bytes] = None
    report: Optional[EvaluationReport] = None
    attempts: list[dict[str, Any]] = field(default_factory=list)


def repair(scene: SceneIR, svg_text: str, report: EvaluationReport, *, brand: BrandIR, intent: IntentIR, render: Renderer,
           work_dir: Path, renderer: str, renderer_version: Optional[str]) -> tuple[list[RepairOutcome], tuple[str, ...]]:
    """Repair every defect in turn on the latest accepted scene. Returns outcomes and missing evidence."""
    defects, missing = detect(scene, report, brand)
    outcomes: list[RepairOutcome] = []
    current, current_svg, current_report = scene, svg_text, report
    for defect in defects:
        outcome = RepairOutcome(defect=defect, accepted=False)
        passing_before = {c.check for c in current_report.checks if c.result == Result.PASS}
        target_check = defect.evidence_refs[0].split("#", 1)[1]
        for attempt in range(1, MAX_ATTEMPTS + 1):
            live = next((d for d in detect(current, current_report, brand)[0] if d.kind == defect.kind and d.region_refs == defect.region_refs),
                        None)
            if live is None:  # an earlier repair already fixed it
                outcome.accepted = True
                break
            proposal = propose(current, live, brand=brand, intent=intent, attempt=attempt)
            if proposal is None:
                outcome.attempts.append({"attempt": attempt, "result": "NO_SAFE_PROPOSAL"})
                break
            child = apply(current, proposal)
            child_svg = svg.emit(child)
            diverged = divergence(current_svg, child_svg, proposal.affected)
            if diverged:
                outcome.attempts.append({"attempt": attempt, "result": "REJECTED_DIVERGENCE", "elements": diverged})
                continue
            r = render(child_svg, child.document.width, child.document.height, work_dir / proposal.proposal_id)
            child_report = evaluate(child, child_svg, intent=intent, brand=brand, png_bytes=r.get("png"), renderer=renderer,
                                    renderer_version=renderer_version, parent_svg=svg_text)
            results = {c.check: c.result for c in child_report.checks}
            regressions = sorted(k for k in passing_before if results.get(k) != Result.PASS)
            fixed = results.get(target_check) == Result.PASS
            outcome.attempts.append({"attempt": attempt, "proposal": proposal.proposal_id, "fixed": fixed,
                                     "regressions": regressions, "render": r.get("status")})
            if fixed and not regressions:
                outcome.accepted, outcome.proposal = True, proposal
                outcome.scene, outcome.svg_text, outcome.png, outcome.report = child, child_svg, r.get("png"), child_report
                current, current_svg, current_report = child, child_svg, child_report
                break
            # rollback: keep ``current``; the failed child is discarded
        outcomes.append(outcome)
    return outcomes, missing


__all__ = ["MAX_ATTEMPTS", "RepairOutcome", "apply", "dependency_closure", "detect", "divergence", "propose", "repair"]
