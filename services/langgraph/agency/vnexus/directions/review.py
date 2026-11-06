"""Stage 5-6: the review board (14 PROPOSED lenses, six modes), gates, verdicts, work orders and the recommendation.

The board is one coordinated schema, not fourteen calls. Two kinds of assessor can contribute:

* LOCAL_MEASUREMENT: deterministic facts about the stored bytes (``measure.py``). They produce findings and gate
  evidence, never creative scores.
* HUMAN: findings and 0-10 rubric scores supplied by a named reviewer through the API.

No vision model route is enabled (``gemini.image_critique`` is DISABLED), so a lens that needs perception and has no
human input is NOT_REVIEWED. Required lenses that are not reviewed block readiness; they are never filled in.

The review function only computes a record. It cannot regenerate, spend, approve, mutate a master or publish; the
session's ``effects`` say so and the service stores nothing but the session.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash

from . import measure
from .records import (NONE, RASTER_NATIVE, VECTOR_REQUIRED, Assessor, AssessorKind, AssetRole, CandidateOutcome, CreativeIntent,
                      CriterionAssessment, DirectionRecommendation, EvidenceClass, EvidenceSource, FindingIn, Gate, GateResult,
                      GateStatus, GenerationCandidate, ProvenanceClass, ReviewFinding, ReviewMode, ReviewSession, RevisionWorkOrder,
                      Severity, Verdict, record_id)

LENSES: dict[str, dict[str, Any]] = {
    "01": {"name": "Brand strategist", "criteria": ("positioning_fit", "audience_relevance", "category_relevance"), "local": False},
    "02": {"name": "Creative director", "criteria": ("concept_coherence", "differentiation"), "local": False},
    "03": {"name": "Identity designer", "criteria": ("silhouette", "symbolism", "system_potential"), "local": False},
    "04": {"name": "Typography specialist", "criteria": ("spelling", "hierarchy", "spacing_lettering"), "local": False},
    "05": {"name": "Composition specialist", "criteria": ("balance", "alignment", "proportion"), "local": False},
    "06": {"name": "Color specialist", "criteria": ("palette_roles", "reproduction", "applicable_contrast"), "local": True},
    "07": {"name": "Accessibility reviewer", "criteria": ("readability", "contrast", "non_color_cues"), "local": True},
    "08": {"name": "Imagery/art-direction reviewer", "criteria": ("framing", "lighting", "style_fit"), "local": False},
    "09": {"name": "Emotional-response reviewer", "criteria": ("intended_vs_apparent",), "local": False},
    "10": {"name": "Brand-memory reviewer", "criteria": ("distinguishing_cues", "category_overlap"), "local": False},
    "11": {"name": "Production/vector specialist", "criteria": ("paths_topology", "small_size", "exports"), "local": True},
    "12": {"name": "Application/UX reviewer", "criteria": ("channel_fit", "crop", "layout_fit"), "local": False},
    "13": {"name": "Brand-safety/rights reviewer", "criteria": ("prohibited_content", "privacy", "provenance"), "local": True},
    "14": {"name": "Evidence/QA reviewer", "criteria": ("substantiation", "uncertainty", "coverage"), "local": True},
}
MODE_LENSES: dict[ReviewMode, tuple[str, ...]] = {
    ReviewMode.QUICK: ("04", "06", "07", "13", "14"),
    ReviewMode.FULL: tuple(LENSES),
    ReviewMode.COMPARE: ("01", "02", "03", "04", "05", "06", "10", "13", "14"),
    ReviewMode.REFINE: ("14",),
    ReviewMode.VECTOR: ("03", "04", "06", "07", "11", "13", "14"),
    ReviewMode.RELEASE: ("04", "06", "07", "11", "12", "13", "14"),
}
CREATIVE_LENSES = ("01", "02", "03", "04", "05", "08", "09", "10", "12")
COMPARE_COVERAGE = 0.5
COMPARE_MARGIN = 1.0
SMALL_SIZE_RETENTION = 0.35
_VAGUE = re.compile(r"\b(make (it )?(look )?(more )?(premium|better|nicer|modern|pop|cleaner|sleeker)|improve (the )?aesthetics?|"
                    r"more premium|look better|make it pop|enhance (the )?design)\b", re.I)
VISION_GAP = "VISION_CRITIQUE_ROUTE_DISABLED: gemini.image_critique has no adapter; no human assessment was supplied"


def _applicable(lens: str, intent: CreativeIntent, *, exact: list[str]) -> Optional[str]:
    role = intent.asset_role
    if lens == "04" and not exact and role not in (AssetRole.WORDMARK, AssetRole.LOCKUP):
        return "no identity text in this brief"
    if lens == "08" and role in VECTOR_REQUIRED:
        return "imagery/art direction applies to illustration, photography, texture and hero images"
    if lens == "11" and role in RASTER_NATIVE:
        return "raster-native role: no vector production"
    return None


def active_lenses(mode: ReviewMode, intent: CreativeIntent, *, refine_seats: tuple[str, ...] = ()) -> tuple[tuple[str, ...], dict[str, str]]:
    exact = intent.vector_instructions.get("exact_text") or []
    wanted = tuple(sorted(set(MODE_LENSES[mode]) | set(refine_seats)))
    active, skipped = [], {}
    for lens in wanted:
        why = _applicable(lens, intent, exact=exact)
        if why:
            skipped[lens] = why
        else:
            active.append(lens)
    return tuple(active), skipped


class _Board:
    def __init__(self, intent: CreativeIntent, mode: ReviewMode, reviewer: str):
        self.intent, self.mode, self.reviewer = intent, mode, reviewer
        self.findings: list[ReviewFinding] = []
        self.local = Assessor(kind=AssessorKind.LOCAL_MEASUREMENT, id="local.measure", version=measure.MEASURE_VERSION)

    def add(self, cand: GenerationCandidate, *, criterion: str, seat: str, observation: str, evidence: EvidenceClass,
            source: EvidenceSource, severity: Severity, rationale: str = "", change: Optional[str] = None,
            check: Optional[str] = None, uncertainty: str = "", region: str = "whole asset", assessor: Optional[Assessor] = None,
            measurement: Optional[dict[str, Any]] = None) -> ReviewFinding:
        actionable = bool(change and check and not (_VAGUE.search(change) and len(change.split()) < 12))
        body = {"c": cand.candidate_id, "criterion": criterion, "seat": seat, "obs": observation, "n": len(self.findings),
                "by": (assessor or self.local).id}
        f = ReviewFinding(finding_id=record_id("vdf", body), candidate_id=cand.candidate_id, criterion=criterion, seat=seat,
                          asset_hash=cand.observed.sha256, region_or_element=region, evidence_class=evidence, evidence_source=source,
                          observation=observation, severity=severity, rationale=rationale, proposed_change=change, acceptance_check=check,
                          uncertainty=uncertainty, actionable=actionable, assessor=assessor or self.local, measurement=measurement)
        self.findings.append(f)
        return f


def _measure(cand: GenerationCandidate, data: bytes, intent: CreativeIntent, work: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"sha256": cand.observed.sha256, "mime": cand.observed.mime}
    if cand.observed.mime == "image/svg+xml":
        out["geometry"] = measure.geometry(data.decode("utf-8", errors="replace"))
    raster, note = measure.raster_for(data, cand.observed.mime, width=cand.observed.width, height=cand.observed.height, work=work)
    out["pixel_source"] = note
    palette = {k: v for k, v in intent.vector_instructions.get("palette_roles", {}).items() if isinstance(v, str)}
    out["pixels"] = measure.pixels(raster, palette) if raster is not None else None
    return out


def _local_findings(board: _Board, cand: GenerationCandidate, m: dict[str, Any], active: tuple[str, ...]) -> None:
    px, geo = m.get("pixels"), m.get("geometry")
    final = board.mode in (ReviewMode.VECTOR, ReviewMode.RELEASE)
    if px is None:
        board.add(cand, criterion="coverage", seat="14", observation=f"pixel checks not run: {m['pixel_source']}",
                  evidence=EvidenceClass.UNKNOWN, source=EvidenceSource.NONE, severity=Severity.MAJOR,
                  uncertainty="no rendered-image inspection; visual lenses cannot use measured facts")
    else:
        if not px["nonblank"]:
            board.add(cand, criterion="exports", seat="11", observation="the rendered asset is a single flat colour",
                      evidence=EvidenceClass.OBSERVED, source=EvidenceSource.PIXELS, severity=Severity.BLOCKER, measurement=px)
        if "06" in active and px["off_palette_share"] > 0.05:
            worst = max((d for d in px["dominant"] if (d["delta_e76"] or 99) > measure.OFF_PALETTE_DELTA_E),
                        key=lambda d: d["share"], default=None)
            target = f" with the nearest approved role colour ({worst['nearest_role']})" if worst and worst["nearest_role"] else ""
            board.add(cand, criterion="palette_roles", seat="06",
                      observation=f"{px['off_palette_share']:.0%} of pixels are in dominant colours more than "
                                  f"{measure.OFF_PALETTE_DELTA_E:g} dE76 from every approved palette role"
                                  + (f" (largest: {worst['hex']}, {worst['share']:.0%})" if worst else ""),
                      evidence=EvidenceClass.OBSERVED, source=EvidenceSource.PIXELS, severity=Severity.MAJOR if final else Severity.MINOR,
                      rationale="masters use approved palette roles only; a concept may explore but the master may not",
                      change=(f"Replace {worst['hex']}{target}; preserve the silhouette and composition." if worst else None),
                      check="Re-render the stored bytes: off-palette share at most 5% of pixels.", measurement={
                          "off_palette_share": px["off_palette_share"], "dominant": px["dominant"]})
        if "11" in active or "07" in active:
            r32 = px["retention_32"]
            if r32 is not None and r32 < SMALL_SIZE_RETENTION:
                board.add(cand, criterion="small_size", seat="11",
                          observation=f"at 32 px the luminance spread falls to {r32:.0%} of the full-size asset",
                          evidence=EvidenceClass.INFERRED, source=EvidenceSource.PIXELS, severity=Severity.MAJOR,
                          rationale="detail that disappears at 32 px is lost at favicon and app-icon sizes (a proxy, not legibility testing)",
                          change="Open the smallest counters and thicken the thinnest strokes until they survive a 32 px raster; "
                                 "preserve the outer silhouette.",
                          check="Render at 32 px and full size; 32 px luminance retention at least 35% and counters visibly open.",
                          uncertainty="luminance spread is a proxy; a human must confirm legibility", measurement={"retention_32": r32})
    if geo is not None:
        if not geo.get("parseable") or not geo.get("safe", False):
            board.add(cand, criterion="prohibited_content", seat="13",
                      observation=f"SVG refused by the safety verifier: {geo.get('safety_detail') or geo.get('error')}",
                      evidence=EvidenceClass.OBSERVED, source=EvidenceSource.GEOMETRY, severity=Severity.BLOCKER)
        if geo.get("classification") == "RASTER_IN_SVG":
            board.add(cand, criterion="paths_topology", seat="11", observation="the SVG embeds a raster image; it is raster, not vector",
                      evidence=EvidenceClass.OBSERVED, source=EvidenceSource.GEOMETRY, severity=Severity.MAJOR if final else Severity.NOTE,
                      change="Rebuild the artwork as native shapes or paths; remove the embedded image.",
                      check="geometry: classification VECTOR and no <image> element")
        if geo.get("pii_like_text"):
            board.add(cand, criterion="privacy", seat="13", observation="text that looks like personal contact data: "
                      + "; ".join(geo["pii_like_text"]), evidence=EvidenceClass.OBSERVED, source=EvidenceSource.GEOMETRY,
                      severity=Severity.BLOCKER, change="Remove the personal data from the artwork.", check="geometry: no PII-like text")


def _human(board: _Board, cand_by_ref: dict[str, GenerationCandidate], f: FindingIn) -> tuple[GenerationCandidate, ReviewFinding]:
    cand = cand_by_ref.get(f.candidate)
    if cand is None:
        raise ValueError(f"finding refers to unknown candidate {f.candidate!r}")
    if f.criterion not in LENSES[f.seat]["criteria"] and f.criterion not in _GATE_CRITERIA:
        raise ValueError(f"criterion {f.criterion!r} is not in seat {f.seat}'s rubric")
    if f.gate_status and f.evidence_class is not EvidenceClass.OBSERVED:
        raise ValueError("a gate attestation must be an OBSERVED inspection")
    who = Assessor(kind=AssessorKind.HUMAN, id=board.reviewer)
    return cand, board.add(cand, criterion=f.criterion, seat=f.seat, observation=f.observation, evidence=f.evidence_class,
                           source=f.evidence_source, severity=f.severity, rationale=f.rationale, change=f.proposed_change,
                           check=f.acceptance_check, uncertainty=f.uncertainty, region=f.region_or_element, assessor=who)


_GATE_CRITERIA = {g.value.lower() for g in Gate}


def _gates(intent: CreativeIntent, cand: GenerationCandidate, m: dict[str, Any], mode: ReviewMode, *, current_genome_ref: str,
           stored_ok: bool, attest: dict[Gate, tuple[str, str]]) -> list[GateResult]:
    out: list[GateResult] = []
    final = mode in (ReviewMode.VECTOR, ReviewMode.RELEASE)
    px, geo = m.get("pixels"), m.get("geometry")
    exact = intent.vector_instructions.get("exact_text") or []

    def gate(g: Gate, status: GateStatus, evidence: str, cls: EvidenceClass) -> None:
        # A human OBSERVED attestation may settle an UNKNOWN; it never overrides an observed FAIL or PASS.
        if status is GateStatus.UNKNOWN and g in attest:
            verdict, fid = attest[g]
            out.append(GateResult(candidate_id=cand.candidate_id, gate=g, status=GateStatus(verdict),
                                  evidence=f"human inspection ({fid}); was UNKNOWN: {evidence}", evidence_class=EvidenceClass.OBSERVED,
                                  finding_ids=(fid,)))
            return
        out.append(GateResult(candidate_id=cand.candidate_id, gate=g, status=status, evidence=evidence, evidence_class=cls))

    # Output availability and provenance binding.
    if cand.provenance is ProvenanceClass.SIMULATED:
        gate(Gate.OUTPUT_PROVENANCE, GateStatus.FAIL, "SIMULATED output is a test stand-in, not an asset", EvidenceClass.OBSERVED)
    elif not stored_ok:
        gate(Gate.OUTPUT_PROVENANCE, GateStatus.FAIL, "stored bytes do not re-hash to the recorded sha256", EvidenceClass.OBSERVED)
    elif px is None and geo is None:
        gate(Gate.OUTPUT_PROVENANCE, GateStatus.UNKNOWN, m["pixel_source"], EvidenceClass.UNKNOWN)
    else:
        label = "recorded adapter output" if cand.provenance is ProvenanceClass.RECORDED else \
            "USER_REPORTED import: bytes bound by hash; provider/model/seed unverified"
        gate(Gate.OUTPUT_PROVENANCE, GateStatus.PASS, f"stored bytes re-hash to {cand.observed.sha256[:16]}; {label}", EvidenceClass.OBSERVED)

    # Exact identity text.
    texts = (geo or {}).get("text_elements") or []
    if intent.brief.exact_text == NONE:
        gate(Gate.EXACT_IDENTITY_TEXT, GateStatus.NOT_APPLICABLE, "identity text decided NONE", EvidenceClass.OBSERVED)
    elif not exact:
        gate(Gate.EXACT_IDENTITY_TEXT, GateStatus.UNKNOWN, "exact identity text was not supplied in the brief", EvidenceClass.UNKNOWN)
    elif texts:
        missing = [t for t in exact if t not in texts]
        gate(Gate.EXACT_IDENTITY_TEXT, GateStatus.FAIL if missing else GateStatus.PASS,
             (f"missing verbatim: {missing}" if missing else "every required string is present verbatim as editable text"),
             EvidenceClass.OBSERVED)
    elif not final:
        gate(Gate.EXACT_IDENTITY_TEXT, GateStatus.NOT_APPLICABLE,
             "concept stage: identity text is set from the approved face in vector production, never taken from generated pixels",
             EvidenceClass.OBSERVED)
    elif geo is not None:
        gate(Gate.EXACT_IDENTITY_TEXT, GateStatus.FAIL, "required identity text is absent as editable text in the master",
             EvidenceClass.OBSERVED)
    else:
        gate(Gate.EXACT_IDENTITY_TEXT, GateStatus.UNKNOWN, "raster master: text cannot be read without OCR; no OCR route",
             EvidenceClass.UNKNOWN)

    # Accessibility: only where a requirement applies to this role.
    role = intent.asset_role
    if role is AssetRole.ICON:
        pair = (px or {}).get("dominant_pair_contrast")
        if pair is None:
            gate(Gate.ACCESSIBILITY, GateStatus.UNKNOWN, "no measured pixels for the WCAG 1.4.11 non-text contrast check",
                 EvidenceClass.UNKNOWN)
        else:
            gate(Gate.ACCESSIBILITY, GateStatus.PASS if pair >= 3.0 else GateStatus.FAIL,
                 f"dominant figure/ground contrast {pair}:1 against the WCAG 2.2 1.4.11 3:1 floor", EvidenceClass.OBSERVED)
    elif role is AssetRole.HERO_IMAGE and exact:
        gate(Gate.ACCESSIBILITY, GateStatus.UNKNOWN, "text is overlaid downstream; contrast is checked on the composed layout",
             EvidenceClass.UNKNOWN)
    else:
        gate(Gate.ACCESSIBILITY, GateStatus.NOT_APPLICABLE,
             "logotypes are exempt from WCAG 1.4.3 and this role carries no required information-bearing graphics"
             if role in (AssetRole.LOGO_MARK, AssetRole.WORDMARK, AssetRole.LOCKUP) else "no information-bearing text or graphics declared",
             EvidenceClass.INFERRED)

    # Brand safety, privacy and rights.
    problems = []
    if geo is not None and (not geo.get("parseable") or not geo.get("safe")):
        problems.append("unsafe SVG")
    if (geo or {}).get("pii_like_text"):
        problems.append("PII-like text in the artwork")
    if intent.prohibited:
        problems.append("prohibited brief content")
    if problems:
        gate(Gate.SAFETY_PRIVACY_RIGHTS, GateStatus.FAIL, "; ".join(problems), EvidenceClass.OBSERVED)
    elif cand.provenance is ProvenanceClass.RECORDED and cand.route_id == "local.foundry_compose":
        gate(Gate.SAFETY_PRIVACY_RIGHTS, GateStatus.PASS, "composed locally from the approved genome; no external source material",
             EvidenceClass.OBSERVED)
    elif not cand.reported.rights_basis:
        gate(Gate.SAFETY_PRIVACY_RIGHTS, GateStatus.UNKNOWN, "no rights basis recorded for this import", EvidenceClass.UNKNOWN)
    else:
        gate(Gate.SAFETY_PRIVACY_RIGHTS, GateStatus.UNKNOWN,
             "rights basis is the importer's statement; third-party marks and likeness need a human inspection (seat 13)",
             EvidenceClass.UNKNOWN)

    # Canonical asset/rule integrity.
    if cand.genome_ref != current_genome_ref or intent.genome_ref != current_genome_ref:
        gate(Gate.CANONICAL_INTEGRITY, GateStatus.FAIL, f"STALE: compiled against genome {intent.genome_ref}, current is "
             f"{current_genome_ref}", EvidenceClass.OBSERVED)
    elif final and px is not None and px["off_palette_share"] > 0.05:
        gate(Gate.CANONICAL_INTEGRITY, GateStatus.FAIL, f"master uses {px['off_palette_share']:.0%} off-palette colour",
             EvidenceClass.OBSERVED)
    elif final and px is None:
        gate(Gate.CANONICAL_INTEGRITY, GateStatus.UNKNOWN, "palette conformance not measured: " + m["pixel_source"],
             EvidenceClass.UNKNOWN)
    else:
        gate(Gate.CANONICAL_INTEGRITY, GateStatus.PASS, "bound to the current approved genome" + (" and palette" if final else ""),
             EvidenceClass.OBSERVED)
    return out


def _work_orders(intent: CreativeIntent, findings: list[ReviewFinding]) -> list[RevisionWorkOrder]:
    protected = tuple(intent.vector_instructions.get("protected") or ()) + ("approved palette roles", "exact identity text")
    out = []
    for f in findings:
        if not f.actionable or f.severity is Severity.NOTE:
            continue
        out.append(RevisionWorkOrder(
            work_order_id=record_id("vdw", {"f": f.finding_id}), candidate_id=f.candidate_id, asset_hash=f.asset_hash,
            change=f.proposed_change or "", why=f"{f.observation} ({f.rationale})" if f.rationale else f.observation,
            protected_invariants=protected,
            dependencies={"asset_sha256": f.asset_hash, "intent_id": intent.intent_id, "genome_ref": intent.genome_ref,
                          "intent_dependency_hash": intent.dependency_hash, "criterion": f.criterion, "seat": f.seat},
            verification=f.acceptance_check or "", finding_ids=(f.finding_id,)))
    return out


def _labels(cands: list[GenerationCandidate], blinded: bool) -> dict[str, str]:
    ordered = sorted(cands, key=lambda c: c.observed.sha256) if blinded else sorted(cands, key=lambda c: (c.slot, c.candidate_id))
    return {chr(ord("A") + i): c.candidate_id for i, c in enumerate(ordered)}


_METRICS = {"off_palette_share": "lower", "retention_32": "higher", "dominant_pair_contrast": "higher"}


def review(intent: CreativeIntent, candidates: list[tuple[GenerationCandidate, bytes, bool]], mode: ReviewMode, *,
           human: list[FindingIn], reviewer: str, current_genome_ref: str, work: Path, tenant_id: str, created_at: str,
           base: Optional[ReviewSession] = None) -> ReviewSession:
    """``candidates`` are (record, stored bytes read back now, stored hash matched) triples."""
    if not candidates:
        raise ValueError("a review needs at least one candidate")
    if mode is ReviewMode.COMPARE and len(candidates) < 2:
        raise ValueError("COMPARE needs at least two candidates")
    if mode is ReviewMode.REFINE and base is None:
        raise ValueError("REFINE needs the base review session")
    cands = [c for c, _, _ in candidates]
    blinded = mode is ReviewMode.COMPARE
    labels = _labels(cands, blinded)
    label_of = {cid: lab for lab, cid in labels.items()}
    by_ref = {**{c.candidate_id: c for c in cands}, **{lab: next(c for c in cands if c.candidate_id == cid) for lab, cid in labels.items()}}
    refine_seats = tuple(sorted({wo.dependencies["seat"] for wo in base.work_orders})) if base else ()
    active, skipped = active_lenses(mode, intent, refine_seats=refine_seats)
    board = _Board(intent, mode, reviewer)
    measurements: dict[str, dict[str, Any]] = {}
    for i, (cand, data, _) in enumerate(candidates):
        sub = work / f"c{i}"
        sub.mkdir(parents=True, exist_ok=True)
        measurements[cand.candidate_id] = _measure(cand, data, intent, sub)
        _local_findings(board, cand, measurements[cand.candidate_id], active)
    attest: dict[str, dict[Gate, tuple[str, str]]] = {c.candidate_id: {} for c in cands}
    human_seen: dict[str, set[str]] = {c.candidate_id: set() for c in cands}
    scores: dict[tuple[str, str, str], list[tuple[int, str, str]]] = {}
    emotional = []
    for f in human:
        cand, rf = _human(board, by_ref, f)
        human_seen[cand.candidate_id].add(f.seat)
        if f.gate and f.gate_status:
            attest[cand.candidate_id][f.gate] = (f.gate_status, rf.finding_id)
        if f.score is not None:
            scores.setdefault((cand.candidate_id, f.seat, f.criterion), []).append((f.score, rf.finding_id, reviewer))
        if f.trait or f.cue:
            emotional.append({"candidate": label_of[cand.candidate_id], "target_trait": f.trait, "visible_cue": f.cue,
                              "reviewer_interpretation": f.observation, "possible_mismatch": f.severity in (Severity.MAJOR, Severity.BLOCKER),
                              "finding_id": rf.finding_id})
    gates: list[GateResult] = []
    for cand, data, stored_ok in candidates:
        gates += _gates(intent, cand, measurements[cand.candidate_id], mode, current_genome_ref=current_genome_ref, stored_ok=stored_ok,
                        attest=attest[cand.candidate_id])
    # Criterion assessments: scores only from human assessors; measurements never become creative scores.
    assessments: list[CriterionAssessment] = []
    missing: set[str] = set()
    for cand in cands:
        px_ok = measurements[cand.candidate_id].get("pixels") is not None or measurements[cand.candidate_id].get("geometry") is not None
        for lens in active:
            local_ok = LENSES[lens]["local"] and px_ok
            reviewed = local_ok or lens in human_seen[cand.candidate_id]
            if not reviewed:
                missing.add(lens)
            for crit in LENSES[lens]["criteria"]:
                got = scores.get((cand.candidate_id, lens, crit))
                if got:
                    assessments.append(CriterionAssessment(
                        candidate_id=cand.candidate_id, criterion=crit, seat=lens, score=round(sum(s for s, _, _ in got) / len(got)),
                        status="ASSESSED", finding_ids=tuple(fid for _, fid, _ in got),
                        assessors=tuple(Assessor(kind=AssessorKind.HUMAN, id=who) for _, _, who in got)))
                else:
                    assessments.append(CriterionAssessment(
                        candidate_id=cand.candidate_id, criterion=crit, seat=lens, status="NOT_REVIEWED",
                        reason=("measured facts only; scores are rubric judgments by a reviewer" if local_ok else VISION_GAP)))
    for lens, why in skipped.items():
        for cand in cands:
            for crit in LENSES[lens]["criteria"]:
                assessments.append(CriterionAssessment(candidate_id=cand.candidate_id, criterion=crit, seat=lens, status="NOT_APPLICABLE",
                                                       reason=why))
    regressions, wo_checks = _refine(base, cands, measurements, gates) if base else ([], [])
    for chk in wo_checks:
        if chk["status"] == "NOT_MET":
            regressions.append({"kind": "WORK_ORDER_NOT_MET", **chk})
    outcomes = [_verdict(mode, c, gates, board.findings, missing, label_of[c.candidate_id], regressions) for c in cands]
    recommendation = _recommend(mode, cands, outcomes, assessments, active, label_of)
    work_orders = _work_orders(intent, board.findings)
    session_body = {"intent": intent.intent_id, "mode": mode.value, "cands": sorted(c.observed.sha256 for c in cands),
                    "human": [f.model_dump(mode="json") for f in human], "reviewer": reviewer, "at": created_at,
                    "base": base.session_id if base else None}
    from .providers import ROUTES, health

    return ReviewSession(
        session_id=record_id("vdr", session_body), intent_id=intent.intent_id, tenant_id=tenant_id, project_id=intent.project_id,
        brand_id=intent.brand_id, genome_ref=current_genome_ref, mode=mode, blinded=blinded, labels=labels,
        candidates={c.candidate_id: c.observed.sha256 for c in cands}, lenses_active=active,
        lenses_required_missing=tuple(sorted(missing)),
        routes={r.route_id: health(r)[0].value for r in ROUTES if r.route_id in ("gemini.image_critique", "local.measure")},
        findings=tuple(board.findings), assessments=tuple(assessments), gates=tuple(gates), outcomes=tuple(outcomes),
        recommendation=recommendation, work_orders=tuple(work_orders),
        emotional_map={"targets": intent.shared.get("emotional_targets") or [], "targets_source": intent.shared.get("emotional_targets_source"),
                       "entries": emotional, "status": "ASSESSED" if emotional else "NOT_ASSESSED",
                       "note": "reviewer interpretation of visible cues; not a measurement of audience emotion"},
        brand_memory=_memory(cands, measurements, board.findings, label_of),
        regressions=tuple(regressions + [{"kind": "WORK_ORDER_CHECK", **c} for c in wo_checks if c["status"] != "NOT_MET"]),
        base_session_id=base.session_id if base else None, created_by=reviewer, created_at=created_at,
        measurements={k: _public_measure(v) for k, v in measurements.items()},
    )


def _public_measure(m: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in m.items() if k in ("sha256", "mime", "pixel_source", "pixels", "geometry")}


def _verdict(mode: ReviewMode, cand: GenerationCandidate, gates: list[GateResult], findings: list[ReviewFinding], missing: set[str],
             label: str, regressions: list[dict[str, Any]]) -> CandidateOutcome:
    mine = [g for g in gates if g.candidate_id == cand.candidate_id]
    out = next(g for g in mine if g.gate is Gate.OUTPUT_PROVENANCE)
    reasons: list[str] = []

    def result(v: Verdict) -> CandidateOutcome:
        return CandidateOutcome(candidate_id=cand.candidate_id, label=label, asset_hash=cand.observed.sha256, verdict=v,
                                reasons=tuple(reasons))
    if out.status is not GateStatus.PASS:
        reasons.append(f"OUTPUT_PROVENANCE {out.status.value}: {out.evidence}")
        return result(Verdict.BLOCKED)
    failed = [g for g in mine if g.status is GateStatus.FAIL]
    severe = [f for f in findings if f.candidate_id == cand.candidate_id and f.severity in (Severity.BLOCKER, Severity.MAJOR)
              and f.evidence_class in (EvidenceClass.OBSERVED, EvidenceClass.INFERRED)]
    regress = [r for r in regressions if r.get("candidate_id") == cand.candidate_id]
    if failed or severe or regress:
        reasons += [f"GATE_FAILED {g.gate.value}: {g.evidence}" for g in failed]
        reasons += [f"{f.severity.value} {f.criterion}: {f.observation}" for f in severe]
        reasons += [f"REGRESSION {r.get('metric') or r.get('work_order_id')}" for r in regress]
        return result(Verdict.REVISE)
    unknown = [g for g in mine if g.status is GateStatus.UNKNOWN]
    if missing:
        reasons.append("required lenses not reviewed: " + ", ".join(f"{s} {LENSES[s]['name']}" for s in sorted(missing)))
        return result(Verdict.BLOCKED if mode in (ReviewMode.FULL, ReviewMode.VECTOR, ReviewMode.RELEASE) else Verdict.INCONCLUSIVE)
    if unknown:
        reasons += [f"GATE_UNKNOWN {g.gate.value}: {g.evidence}" for g in unknown]
        return result(Verdict.BLOCKED if mode is ReviewMode.RELEASE else Verdict.INCONCLUSIVE)
    if mode is ReviewMode.QUICK:
        reasons.append("QUICK triage found no blocker or major defect; it cannot substitute for release review")
        return result(Verdict.INCONCLUSIVE)
    if mode is ReviewMode.COMPARE:
        reasons.append("eligible for comparison")
        return result(Verdict.INCONCLUSIVE)
    reasons.append("applicable checks satisfied; the existing human decision is pending")
    return result(Verdict.READY_FOR_APPROVAL)


def _recommend(mode: ReviewMode, cands: list[GenerationCandidate], outcomes: list[CandidateOutcome],
               assessments: list[CriterionAssessment], active: tuple[str, ...], label_of: dict[str, str]) -> DirectionRecommendation:
    if mode is not ReviewMode.COMPARE:
        if len(outcomes) == 1:
            o = outcomes[0]
            return DirectionRecommendation(verdict=o.verdict, candidate_id=o.candidate_id, label=o.label, reasons=o.reasons)
        ready = [o for o in outcomes if o.verdict is Verdict.READY_FOR_APPROVAL]
        return DirectionRecommendation(verdict=Verdict.INCONCLUSIVE, reasons=(
            f"{len(ready)} of {len(outcomes)} candidates satisfy the {mode.value} checks; use COMPARE to choose a direction",))
    eligible = [o for o in outcomes if o.verdict is Verdict.INCONCLUSIVE and "eligible for comparison" in o.reasons]
    if not eligible:
        kinds = {o.verdict for o in outcomes}
        worst = Verdict.INCONCLUSIVE if Verdict.INCONCLUSIVE in kinds else (Verdict.REVISE if Verdict.REVISE in kinds else Verdict.BLOCKED)
        return DirectionRecommendation(verdict=worst, reasons=("no candidate passed the non-compensatory gates and evidence floor",
                                                               *sorted({r for o in outcomes for r in o.reasons})[:6]))
    creative = [(lens, c) for lens in active if lens in CREATIVE_LENSES for c in LENSES[lens]["criteria"]]
    scored = {(a.candidate_id, a.seat, a.criterion): a.score for a in assessments if a.score is not None}
    common = [k for k in creative if all((o.candidate_id, *k) in scored for o in eligible)]
    coverage = len(common) / len(creative) if creative else 0.0
    if coverage < COMPARE_COVERAGE:
        return DirectionRecommendation(verdict=Verdict.INCONCLUSIVE, reasons=(
            f"criterion coverage {coverage:.0%} is below {COMPARE_COVERAGE:.0%} for every eligible candidate: "
            "comparison evidence is insufficient", VISION_GAP),
            aggregate={"coverage": round(coverage, 3), "criteria": len(creative), "common": len(common)})
    means = {o.candidate_id: sum(scored[(o.candidate_id, *k)] for k in common) / len(common) for o in eligible}
    ranked = sorted(means.items(), key=lambda kv: (-kv[1], label_of[kv[0]]))
    aggregate = {"weights": "equal across the common criteria", "coverage": round(coverage, 3),
                 "criteria_used": [f"{s}:{c}" for s, c in common],
                 "missing_criteria": [f"{s}:{c}" for s, c in creative if (s, c) not in common],
                 "means": {label_of[cid]: round(v, 2) for cid, v in ranked},
                 "note": "rubric judgments, not probabilities; a mean is not proof of quality"}
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < COMPARE_MARGIN:
        return DirectionRecommendation(verdict=Verdict.INCONCLUSIVE, aggregate=aggregate, reasons=(
            f"leading margin {ranked[0][1] - ranked[1][1]:.2f} is below {COMPARE_MARGIN} rubric point",))
    best = ranked[0][0]
    return DirectionRecommendation(verdict=Verdict.RECOMMENDED_DIRECTION, candidate_id=best, label=label_of[best], aggregate=aggregate,
                                   reasons=(f"passes every gate and leads on {len(common)} commonly assessed criteria",))


def _memory(cands: list[GenerationCandidate], measurements: dict[str, dict[str, Any]], findings: list[ReviewFinding],
            label_of: dict[str, str]) -> dict[str, Any]:
    entries = []
    for c in cands:
        px = measurements[c.candidate_id].get("pixels")
        overlap = [f.observation for f in findings if f.candidate_id == c.candidate_id and f.criterion == "category_overlap"]
        predicted = [f.observation for f in findings if f.candidate_id == c.candidate_id and f.criterion == "distinguishing_cues"
                     and f.assessor.kind is AssessorKind.HUMAN]
        entries.append({"candidate": label_of[c.candidate_id],
                        "observed_cues": ({"dominant_colours": [d["hex"] for d in px["dominant"][:4]], "figure_share": px["figure_share"],
                                           "aspect": px["aspect"]} if px else "NOT_RUN"),
                        "category_overlap": overlap or "UNKNOWN: no reviewer assessed category overlap",
                        "predicted_memorability": predicted or "NOT_ASSESSED",
                        "predicted_label": "PREDICTION by a reviewer, not measured recall"})
    return {"entries": entries, "measured_recall": "HUMAN_RECALL_NOT_TESTED",
            "recall_protocol": "a recall test needs participants, an exposure/delay protocol and recorded results; none exist",
            "trademark_clearance": "NOT_ASSESSED: no clearance search was performed and none is claimed"}


def _refine(base: ReviewSession, cands: list[GenerationCandidate], measurements: dict[str, dict[str, Any]],
            gates: list[GateResult]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare each revised candidate with the base session's candidates on the measured metrics and gates."""
    regressions: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    base_gates = {(g.candidate_id, g.gate): g.status for g in base.gates}
    base_px = {cid: (m.get("pixels") or {}) for cid, m in base.measurements.items()}
    for c in cands:
        px = measurements[c.candidate_id].get("pixels") or {}
        for bid in base.candidates:
            for metric, better in _METRICS.items():
                a, b = base_px.get(bid, {}).get(metric), px.get(metric)
                if a is None or b is None:
                    continue
                worse = b > a + 0.02 if better == "lower" else b < a - 0.02
                if worse:
                    regressions.append({"kind": "METRIC_REGRESSION", "candidate_id": c.candidate_id, "base_candidate_id": bid,
                                        "metric": metric, "before": a, "after": b})
            for g in Gate:
                if base_gates.get((bid, g)) is GateStatus.PASS and any(x.candidate_id == c.candidate_id and x.gate is g and
                                                                       x.status is GateStatus.FAIL for x in gates):
                    regressions.append({"kind": "GATE_REGRESSION", "candidate_id": c.candidate_id, "base_candidate_id": bid, "metric": g.value})
        for wo in base.work_orders:
            metric = {"palette_roles": "off_palette_share", "small_size": "retention_32"}.get(wo.dependencies["criterion"])
            if metric is None or px.get(metric) is None:
                checks.append({"work_order_id": wo.work_order_id, "candidate_id": c.candidate_id, "status": "NOT_VERIFIED",
                               "detail": "no automatic check for this criterion; a reviewer must verify it"})
                continue
            met = px[metric] <= 0.05 if metric == "off_palette_share" else px[metric] >= SMALL_SIZE_RETENTION
            checks.append({"work_order_id": wo.work_order_id, "candidate_id": c.candidate_id, "status": "MET" if met else "NOT_MET",
                           "metric": metric, "value": px[metric]})
    return regressions, checks


def session_hash(session: ReviewSession) -> str:
    return canonical_hash(session.model_dump(mode="json"))


__all__ = ["CREATIVE_LENSES", "LENSES", "MODE_LENSES", "VISION_GAP", "active_lenses", "review", "session_hash"]
