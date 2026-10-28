"""Creative-direction service: the eight stages over existing owners. No new store, scheduler or approval path.

1 INTAKE / 2 COMPILE  ``create_intent``: approved genome projection + brief -> CreativeIntent (stored once per
                      dependency hash; an unchanged brief and genome return the stored intent).
3 GENERATE / IMPORT   ``generate`` runs a pinned, authorized route through ``fabric_service`` (local deterministic
                      composition; mock for tests); every hosted route is DISABLED and is refused with a manual-handoff
                      offer. ``import_candidate`` stores operator-supplied bytes with USER_REPORTED provenance.
4 RECORD              candidates are Project OS ``media_asset`` artifacts plus a JSON record; observed facts and
                      reported metadata are separate fields.
5 REVIEW              ``create_review`` computes and stores an immutable ReviewSession (``qa_report``). It writes
                      nothing else: no generation, spend, approval, master mutation or publication.
6 SELECT              ``request_selection`` opens the existing artifact approval on the candidate's exact bytes;
                      a recommendation is never an approval.
7 RECONSTRUCT         ``reconstruct`` only for roles that need editable paths, only after the selection approval.
8 FREEZE              ``freeze`` turns an approved, release-reviewed master into a genome DRAFT (master artifact id +
                      sha256) and submits it to the existing genome review. The brand book and identity production
                      read the master only through the approved genome, pinned by hash.

Everything is stored in the target project through ``foundry.studio.store``; the per-intent ledger is revised with a
compare-and-set on its head hash, so concurrent writers cannot lose each other's entries.
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.kernel.roles import assert_role_may_produce
from services.langgraph.security.auth import Principal

from .. import service as genome_service
from ..genome import GenomeDocument, Scope, document_from_flat
from . import intent as intentmod
from . import measure, reconstruct, review as reviewmod
from .providers import Task, decide
from .records import (LOGO_ROLES, ApprovalBinding, CandidateObserved, CandidateReported, CreativeIntent, DirectionBrief, FindingIn,
                      GenerationCandidate, ProvenanceClass, ReviewMode, ReviewSession, Verdict, VectorReconstruction, record_id)

OUTPUTS: dict[str, tuple[str, str, str]] = {
    "intent": ("creative_director", "creative_concept", "application/json"),
    "ledger": ("creative_director", "creative_concept", "application/json"),
    "candidate": ("creative_director", "creative_concept", "application/json"),
    "png": ("creative_director", "media_asset", "image/png"),
    "svg": ("creative_director", "media_asset", "image/svg+xml"),
    "review": ("brand_safety_reviewer", "qa_report", "application/json"),
    "reconstruction": ("brand_safety_reviewer", "qa_report", "application/json"),
}
APPROVAL_POLICY = "amc-vnexus-directions/v1"
SUBJECT_SELECTION = "VNEXUS_DIRECTION_SELECTION"
MAX_IMPORT_BYTES = 12_000_000
NEAR_DUPLICATE_BITS = 4


class DirectionBlocked(ValueError):
    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


class NotRequired(DirectionBlocked):
    pass


# --------------------------------------------------------------------------- storage


def _adapter():
    from services.langgraph.api.routes._project_common import storage_adapter

    return storage_adapter()


def _key(intent_id: str, suffix: str) -> str:
    name = f"vdx-{intent_id.removeprefix('vdi-')}-{suffix}"
    if len(f"foundry-{name}") > 64:
        raise ValueError(f"artifact key {name!r} would be truncated by Project OS")
    return name


def _put(principal: Principal, project_id: str, name: str, data: bytes, kind: str, *, depends_on: tuple[str, ...] = (),
         expect_head_hash: Optional[str] = None, v2: Optional[dict] = None) -> dict:
    from services.langgraph.agency.foundry.studio import store

    role, artifact_type, mime = OUTPUTS[kind]
    assert_role_may_produce(role, artifact_type)
    entry = store(principal, project_id, name, data, mime=mime, artifact_type=artifact_type, subtype=f"vnexus_direction_{kind}",
                  adapter=_adapter(), depends_on=depends_on, expect_head_hash=expect_head_hash, v2=v2)
    return {**entry, "sha256": hashlib.sha256(data).hexdigest()}


def _artifact_id(project_id: str, name: str) -> str:
    from services.langgraph.persistence.projects import project_artifact_id

    return project_artifact_id(project_id, f"foundry-{name}")


def _read(project_id: str, name: str) -> Optional[tuple[bytes, dict]]:
    from services.langgraph.agency.foundry.studio import observe

    try:
        return observe(_artifact_id(project_id, name), _adapter())
    except LookupError:
        return None


def _json(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def _now() -> str:
    from services.langgraph.persistence import vnexus as db

    return db.now_iso()


def _ledger(project_id: str, intent_id: str) -> tuple[dict, Optional[str]]:
    stored = _read(project_id, _key(intent_id, "ledger"))
    if stored is None:
        return {"intent_id": intent_id, "candidates": [], "sessions": [], "reconstructions": [], "bindings": [], "events": []}, None
    return json.loads(stored[0]), hashlib.sha256(stored[0]).hexdigest()


def _update_ledger(principal: Principal, project_id: str, intent_id: str, change: Callable[[dict], None]) -> dict:
    from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError

    for _ in range(4):
        ledger, sha = _ledger(project_id, intent_id)
        change(ledger)
        ledger["events"] = ledger["events"][-200:]
        try:
            _put(principal, project_id, _key(intent_id, "ledger"), _json(ledger), "ledger", expect_head_hash=sha)
            return ledger
        except StaleArtifactVersionError:
            continue
    raise genome_service.db.VnexusConflict("the direction ledger kept changing; retry")


def _event(ledger: dict, op: str, status: str, started: float, **ids: Any) -> None:
    # Minimal telemetry: ids, hashes, status, duration, error code, measured cost. Never bytes, prompts or secrets.
    ledger["events"].append({"op": op, "status": status, "at": _now(), "duration_ms": round((time.monotonic() - started) * 1000),
                             **{k: v for k, v in ids.items() if v is not None}})


# --------------------------------------------------------------------------- intent


def _target(principal: Principal, brand_id: str, project_id: str, *, write: bool) -> dict:
    brand = genome_service.brand_for(principal, brand_id)
    genome_service.authorize(principal, project_id, write=write)
    return brand


def _projection(principal: Principal, brand_id: str, scope: Scope, scope_ref: str):
    from ..production import approved_projection

    return approved_projection(principal, brand_id, scope=scope, scope_ref=scope_ref)


def create_intent(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str,
                  brief: DirectionBrief) -> dict[str, Any]:
    started = time.monotonic()
    _target(principal, brand_id, project_id, write=True)
    p, meta = _projection(principal, brand_id, scope, scope_ref)
    intent = intentmod.compile_intent(tenant_id=principal.tenant_id, project_id=project_id, brand_id=brand_id, scope=scope.value,
                                      scope_ref=scope_ref, projection=p, brand_constraints=meta["constraints"], brief=brief)
    data = _json(intent.model_dump(mode="json"))
    existing = _read(project_id, _key(intent.intent_id, "intent"))
    unchanged = existing is not None and existing[0] == data
    if not unchanged:
        _put(principal, project_id, _key(intent.intent_id, "intent"), data, "intent")
    _update_ledger(principal, project_id, intent.intent_id,
                   lambda led: _event(led, "intent", "COMPLETE_UNCHANGED" if unchanged else intent.status, started,
                                      dependency_hash=intent.dependency_hash))
    return {"intent": intent.model_dump(mode="json"), "stored": "COMPLETE_UNCHANGED" if unchanged else "COMPLETE"}


def load_intent(principal: Principal, brand_id: str, intent_id: str, project_id: str, *, write: bool = False) -> CreativeIntent:
    _target(principal, brand_id, project_id, write=write)
    if not intent_id.startswith("vdi-") or len(intent_id) != 20:
        raise LookupError("unknown intent")
    stored = _read(project_id, _key(intent_id, "intent"))
    if stored is None:
        raise LookupError("unknown intent")
    intent = CreativeIntent.model_validate(json.loads(stored[0]))
    if intent.brand_id != brand_id or intent.tenant_id != principal.tenant_id or intent.project_id != project_id:
        raise LookupError("unknown intent")
    return intent


def _current_genome_ref(principal: Principal, intent: CreativeIntent) -> str:
    try:
        p, _ = _projection(principal, intent.brand_id, Scope(intent.scope), intent.scope_ref)
        return p.genome_ref
    except genome_service.GenomeBlocked:
        return "no-approved-genome"


def handoff(principal: Principal, brand_id: str, intent_id: str, project_id: str) -> dict[str, Any]:
    return intentmod.handoff_package(load_intent(principal, brand_id, intent_id, project_id))


# --------------------------------------------------------------------------- candidates


def _candidate_name(intent_id: str, cid: str, suffix: str = "") -> str:
    return _key(intent_id, f"c{cid.removeprefix('vdc-')[:12]}{suffix}")


def _store_candidate(principal: Principal, intent: CreativeIntent, cand: GenerationCandidate) -> None:
    _put(principal, intent.project_id, _candidate_name(intent.intent_id, cand.candidate_id, "-rec"), _json(cand.model_dump(mode="json")),
         "candidate", depends_on=tuple(x for x in (cand.observed.artifact_id,) if x))


def load_candidate(project_id: str, intent_id: str, candidate_id: str) -> GenerationCandidate:
    stored = _read(project_id, _candidate_name(intent_id, candidate_id, "-rec")) if candidate_id.startswith("vdc-") else None
    if stored is None:
        raise LookupError("unknown candidate")
    return GenerationCandidate.model_validate(json.loads(stored[0]))


def candidate_bytes(cand: GenerationCandidate) -> tuple[bytes, bool]:
    """The stored bytes read back now, and whether they still hash to the recorded value."""
    from services.langgraph.agency.foundry.studio import observe

    if cand.observed.artifact_id:
        data, _ = observe(cand.observed.artifact_id, _adapter())
    else:
        data = _adapter().get_bytes(cand.observed.storage_uri or "")
    return data, hashlib.sha256(data).hexdigest() == cand.observed.sha256


def _dims(data: bytes, mime: str) -> tuple[Optional[int], Optional[int]]:
    from services.langgraph.agency.avic import png

    if mime == "image/png":
        return png.dimensions(data)
    return measure.svg_size(data.decode("utf-8", errors="replace"))


def _phash(data: bytes, mime: str) -> Optional[str]:
    from services.langgraph.agency.avic import png

    if mime != "image/png":
        return None   # SVG concepts would need a Chromium render just for this; distinctness is then reviewed, not hashed
    try:
        return measure.dhash(png.decode(data))
    except png.PngError:
        return None


def _near_duplicate(project_id: str, intent_id: str, ledger: dict, phash: Optional[str], sha: str) -> Optional[str]:
    for cid in ledger["candidates"]:
        other = load_candidate(project_id, intent_id, cid)
        if other.observed.sha256 == sha:
            return other.candidate_id
        if phash and other.perceptual_hash and measure.hamming(phash, other.perceptual_hash) <= NEAR_DUPLICATE_BITS:
            return other.candidate_id
    return None


def _validate_bytes(data: bytes, mime: str) -> str:
    from services.langgraph.agency.avic import png

    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError(f"import exceeds {MAX_IMPORT_BYTES} bytes")
    if mime == "image/png":
        try:
            png.decode(data)
        except png.PngError as exc:
            raise ValueError(f"not a decodable PNG: {exc}") from exc
        return "RASTER"
    if mime == "image/svg+xml":
        geo = measure.geometry(data.decode("utf-8", errors="replace"))
        if not geo.get("parseable"):
            raise ValueError(geo.get("error") or "SVG_MALFORMED")
        if geo["classification"] != "RASTER_IN_SVG" and not geo.get("safe"):
            raise ValueError(f"SVG refused by the safety verifier: {geo.get('safety_detail')}")
        if geo.get("external_refs"):
            raise ValueError("SVG with external references is refused")
        if geo["classification"] == "RASTER_IN_SVG" and reconstruct_active(data):
            raise ValueError("SVG with active content is refused")
        return "RASTER_IN_SVG" if geo["classification"] == "RASTER_IN_SVG" else "VECTOR"
    raise ValueError("only image/png and image/svg+xml are accepted")


def reconstruct_active(data: bytes) -> bool:
    from ..brandbook.assets import _ACTIVE

    return bool(_ACTIVE.search(data.decode("utf-8", errors="replace")))


def _record_candidate(principal: Principal, intent: CreativeIntent, *, slot: int, data: bytes, mime: str, route_id: str,
                      provenance: ProvenanceClass, reported: CandidateReported, stored: dict, cost_measured: Optional[int],
                      derived_from: Optional[str] = None, reconstruction_id: Optional[str] = None,
                      direction: Optional[str] = None) -> GenerationCandidate:
    instr = next((s for s in intent.image_instructions if s.slot == slot), None)
    sha = hashlib.sha256(data).hexdigest()
    ledger, _ = _ledger(intent.project_id, intent.intent_id)
    phash = _phash(data, mime)
    width, height = _dims(data, mime)
    cid = record_id("vdc", {"intent": intent.intent_id, "slot": slot, "sha": sha, "route": route_id, "from": derived_from})
    cand = GenerationCandidate(
        candidate_id=cid, intent_id=intent.intent_id, slot=slot, direction=direction or (instr.direction if instr else "imported"),
        prompt_hash=instr.prompt_hash if instr else "", genome_ref=intent.genome_ref, intent_dependency_hash=intent.dependency_hash,
        route_id=route_id, provenance=provenance,
        observed=CandidateObserved(sha256=sha, readback_sha256=stored["readback_sha256"], mime=mime, bytes=len(data), width=width,
                                   height=height, stored_at=_now(), artifact_id=stored.get("artifact_id"),
                                   artifact_version=stored.get("version"), storage_uri=stored.get("storage_uri"),
                                   format_class=_validate_bytes(data, mime)),
        reported=reported, cost_measured_minor=cost_measured,
        near_duplicate_of=None if derived_from else _near_duplicate(intent.project_id, intent.intent_id,
                                                                    {**ledger, "candidates": [c for c in ledger["candidates"] if c != cid]},
                                                                    phash, sha),
        derived_from=derived_from, reconstruction_id=reconstruction_id, perceptual_hash=phash,
        created_by=principal.user_id, created_at=_now())
    _store_candidate(principal, intent, cand)
    return cand


def import_candidate(principal: Principal, brand_id: str, intent_id: str, project_id: str, *, slot: int, mime: str, data_base64: str,
                     reported: CandidateReported) -> dict[str, Any]:
    """Manual route: the operator generated elsewhere under their own authorization. Provenance stays USER_REPORTED."""
    from services.langgraph.agency.foundry.studio import observe

    started = time.monotonic()
    intent = load_intent(principal, brand_id, intent_id, project_id, write=True)
    if intent.status != "READY":
        raise DirectionBlocked("the intent is blocked; resolve its inputs first", {"blockers": list(intent.blockers)})
    if slot not in {s.slot for s in intent.image_instructions}:
        raise ValueError(f"slot {slot} is not one of the intent's {len(intent.image_instructions)} direction slots")
    try:
        data = base64.b64decode(data_base64, validate=True)
    except ValueError as exc:
        raise ValueError("data_base64 is not valid base64") from exc
    _validate_bytes(data, mime)
    sha = hashlib.sha256(data).hexdigest()
    name = _key(intent_id, f"i{slot}-{sha[:12]}")
    entry = _put(principal, project_id, name, data, "png" if mime == "image/png" else "svg",
                 depends_on=(_artifact_id(project_id, _key(intent_id, "intent")),),
                 v2={"provenance_ref": f"vnexus-direction-import:{intent_id}", "synthetic": True})
    readback, head = observe(entry["artifact_id"], _adapter())
    stored = {"artifact_id": entry["artifact_id"], "version": entry["version"], "readback_sha256": hashlib.sha256(readback).hexdigest()}
    cand = _record_candidate(principal, intent, slot=slot, data=data, mime=mime, route_id="manual.handoff",
                             provenance=ProvenanceClass.USER_REPORTED, reported=reported, stored=stored, cost_measured=None)
    _update_ledger(principal, project_id, intent_id, lambda led: (
        led["candidates"].append(cand.candidate_id) if cand.candidate_id not in led["candidates"] else None,
        _event(led, "import", "COMPLETE", started, candidate_id=cand.candidate_id, sha256=sha)))
    return {"candidate": cand.model_dump(mode="json"), "provenance_note": "USER_REPORTED: provider, model, seed and cost are the "
            "importer's statement and are not verified; only the stored bytes are"}


def generate(principal: Principal, brand_id: str, intent_id: str, project_id: str, *, route_id: str, run_key: str) -> dict[str, Any]:
    """Run the pinned route for every slot. A refused route calls nothing and offers the manual handoff."""
    from .. import fabric_service
    from ..media_fabric import Capability, MediaRequest

    started = time.monotonic()
    intent = load_intent(principal, brand_id, intent_id, project_id, write=True)
    if intent.status != "READY":
        raise DirectionBlocked("the intent is blocked; resolve its inputs first", {"blockers": list(intent.blockers)})
    task = {"local.foundry_compose": Task.CONCEPT_COMPOSE, "mock.simulated": Task.SIMULATED}.get(route_id, Task.TEXT_TO_IMAGE)
    decision = decide(route_id, task, budget_minor=intent.brief.budget_minor)
    if decision.allowed and route_id == "local.foundry_compose" and not all(s.compose_mark for s in intent.image_instructions):
        decision = decision.model_copy(update={"allowed": False, "offer": "manual.handoff", "blockers": (
            f"ROLE_UNSUPPORTED: local composition makes marks and icons, not {intent.asset_role.value}",)})
    if not decision.allowed:
        _update_ledger(principal, project_id, intent_id,
                       lambda led: _event(led, "generate", "BLOCKED", started, route_id=route_id, error=decision.blockers[0][:80]))
        return {"status": "BLOCKED", "decision": decision.model_dump(mode="json"), "candidates": [],
                "handoff": intentmod.handoff_package(intent) if decision.offer else None}
    results = []
    values = None
    for s in intent.image_instructions:
        if route_id == "local.foundry_compose":
            if values is None:
                values = _compose_inputs(principal, intent)
            svg = values(s.compose_mark)
            request = MediaRequest(capability=Capability.VECTOR_SVG, spec={"svg": svg}, label=f"direction {s.slot}: {s.compose_mark}")
            provider = "local.svg"
        else:
            request = MediaRequest(capability=Capability.VECTOR_SVG, spec={"mock": "ok", "mock_key": f"{run_key}:{s.slot}"},
                                   width=s.parameters["width"], height=s.parameters["height"], label=f"direction {s.slot} (simulated)")
            provider = "mock.simulated"
        job = fabric_service.execute(principal, project_id, provider_id=provider, request=request,
                                     idempotency_key=f"vdx:{intent_id}:{run_key}:{s.slot}",
                                     depends_on=(_artifact_id(project_id, _key(intent_id, "intent")),))
        if job["state"] != "QC_PASSED":
            # Ambiguous or failed jobs are reported, never regenerated here: a replay reconciles through the job's idempotency key.
            results.append({"slot": s.slot, "status": "RECONCILE_REQUIRED" if job["state"] in ("RUNNING", "QUEUED") else "FAILED",
                            "job_id": job["job_id"], "state": job["state"], "error": job.get("error")})
            continue
        art = job["artifact"]
        data, ok = candidate_bytes(GenerationCandidate.model_construct(observed=CandidateObserved.model_construct(
            artifact_id=art.get("artifact_id"), storage_uri=art.get("storage_uri"), sha256=art["sha256"])))
        if not ok:
            results.append({"slot": s.slot, "status": "FAILED", "job_id": job["job_id"], "error": "INTEGRITY: read-back mismatch"})
            continue
        simulated = bool(art.get("simulated"))
        reported = CandidateReported(provider=provider, model=decision.route_id, model_version=art.get("renderer_version"),
                                     parameters={"compose_mark": s.compose_mark} if s.compose_mark else dict(s.parameters),
                                     generated_at=job.get("updated_at"), job_ref=job["job_id"], receipt_ref=f"vnexus-job:{job['job_id']}",
                                     cost_minor=int((job.get("estimate") or {}).get("amount_minor", 0)), currency="USD",
                                     rights_basis="composed locally from the approved genome" if not simulated else None)
        cand = _record_candidate(principal, intent, slot=s.slot, data=data, mime=art["mime"], route_id=route_id,
                                 provenance=ProvenanceClass.SIMULATED if simulated else ProvenanceClass.RECORDED, reported=reported,
                                 stored={"artifact_id": art.get("artifact_id"), "version": art.get("version"),
                                         "storage_uri": art.get("storage_uri"), "readback_sha256": art["readback_sha256"]},
                                 cost_measured=int((job.get("estimate") or {}).get("amount_minor", 0)))
        results.append({"slot": s.slot, "status": "COMPLETE", "job_id": job["job_id"], "candidate_id": cand.candidate_id,
                        "provenance": cand.provenance.value})
    done = [r["candidate_id"] for r in results if r.get("candidate_id")]
    status = "COMPLETE" if len(done) == len(results) else ("PROVISIONAL" if done else "FAILED_VALIDATION")
    _update_ledger(principal, project_id, intent_id, lambda led: (
        led["candidates"].extend(c for c in done if c not in led["candidates"]),
        _event(led, "generate", status, started, route_id=route_id, candidates=len(done), cost_minor_measured=0)))
    return {"status": status, "decision": decision.model_dump(mode="json"), "candidates": results, "handoff": None,
            "note": "simulated output is never a selectable asset" if route_id == "mock.simulated" else ""}


def _compose_inputs(principal: Principal, intent: CreativeIntent) -> Callable[[str], str]:
    from ..brandbook.service import _composer

    brand = genome_service.brand_for(principal, intent.brand_id)
    p, _ = _projection(principal, intent.brand_id, Scope(intent.scope), intent.scope_ref)
    compose = _composer(dict(p.values), brand["display_name"], p.genome_ref, p.resolution_hash, intent.project_id)

    def svg_for(mark_id: Optional[str]) -> str:
        svg = compose(mark_id or "")
        if svg is None:
            raise ValueError(f"unknown mark {mark_id}")
        return svg
    return svg_for


# --------------------------------------------------------------------------- review


def create_review(principal: Principal, brand_id: str, intent_id: str, project_id: str, *, mode: ReviewMode, candidate_ids: list[str],
                  findings: list[FindingIn], base_session_id: Optional[str] = None) -> dict[str, Any]:
    started = time.monotonic()
    intent = load_intent(principal, brand_id, intent_id, project_id, write=True)
    ledger, _ = _ledger(project_id, intent_id)
    unknown = [c for c in candidate_ids if c not in ledger["candidates"]]
    if unknown:
        raise LookupError(f"unknown candidate(s) {unknown}")
    cands = []
    for cid in dict.fromkeys(candidate_ids):
        cand = load_candidate(project_id, intent_id, cid)
        data, ok = candidate_bytes(cand)
        cands.append((cand, data, ok))
    base = load_session(principal, brand_id, intent_id, project_id, base_session_id) if base_session_id else None
    with tempfile.TemporaryDirectory(prefix="amc-vnexus-review-") as work:
        session = reviewmod.review(intent, cands, mode, human=findings, reviewer=principal.user_id,
                                   current_genome_ref=_current_genome_ref(principal, intent), work=Path(work),
                                   tenant_id=principal.tenant_id, created_at=_now(), base=base)
    _put(principal, project_id, _key(intent_id, f"r{session.session_id.removeprefix('vdr-')[:12]}"), _json(session.model_dump(mode="json")),
         "review", depends_on=tuple(c.observed.artifact_id for c, _, _ in cands if c.observed.artifact_id))
    _update_ledger(principal, project_id, intent_id, lambda led: (
        led["sessions"].append(session.session_id) if session.session_id not in led["sessions"] else None,
        _event(led, "review", session.recommendation.verdict.value, started, session_id=session.session_id, mode=mode.value)))
    return {"session": session.model_dump(mode="json")}


def load_session(principal: Principal, brand_id: str, intent_id: str, project_id: str, session_id: str) -> ReviewSession:
    load_intent(principal, brand_id, intent_id, project_id)
    stored = _read(project_id, _key(intent_id, f"r{session_id.removeprefix('vdr-')[:12]}")) if session_id.startswith("vdr-") else None
    if stored is None:
        raise LookupError("unknown review session")
    session = ReviewSession.model_validate(json.loads(stored[0]))
    if session.session_id != session_id:
        raise LookupError("unknown review session")
    return session


# --------------------------------------------------------------------------- selection (human, existing approval)


def _head(artifact_id: str) -> dict:
    from services.langgraph.persistence.agency_kernel import get_artifact

    head = get_artifact(artifact_id)
    if head is None:
        raise LookupError(artifact_id)
    return head


def request_selection(principal: Principal, brand_id: str, intent_id: str, project_id: str, *, candidate_id: str,
                      session_id: str) -> dict[str, Any]:
    """Open the existing approval on the candidate's exact bytes. The reviewer decides on /approvals/{id}/decide."""
    from services.langgraph.agency.intake.release import open_artifact_approval

    started = time.monotonic()
    intent = load_intent(principal, brand_id, intent_id, project_id, write=True)
    cand = load_candidate(project_id, intent_id, candidate_id)
    session = load_session(principal, brand_id, intent_id, project_id, session_id)
    outcome = next((o for o in session.outcomes if o.candidate_id == candidate_id), None)
    reasons = []
    if cand.provenance is ProvenanceClass.SIMULATED:
        reasons.append("SIMULATED_NOT_SELECTABLE")
    if outcome is None:
        reasons.append("CANDIDATE_NOT_IN_SESSION")
    elif outcome.verdict in (Verdict.BLOCKED, Verdict.REVISE):
        reasons.append(f"REVIEW_{outcome.verdict.value}")
    if session.mode not in (ReviewMode.COMPARE, ReviewMode.FULL, ReviewMode.RELEASE):
        reasons.append(f"SESSION_MODE_{session.mode.value}: selection needs a COMPARE, FULL or RELEASE review")
    if outcome is not None and outcome.asset_hash != cand.observed.sha256:
        reasons.append("SESSION_REVIEWED_OTHER_BYTES")
    data, ok = candidate_bytes(cand)
    if not ok:
        reasons.append("STORED_BYTES_CHANGED")
    if _current_genome_ref(principal, intent) != intent.genome_ref:
        reasons.append("GENOME_CHANGED")
    if reasons:
        return {"status": "BLOCKED", "reasons": reasons}
    head = _head(cand.observed.artifact_id or "")
    approval = open_artifact_approval(
        principal, tenant_id=principal.tenant_id, project_id=project_id,
        mission_id=f"{project_id}:vnexus-direction:{intent_id}:{candidate_id}",
        contract_hash=canonical_hash({"policy": APPROVAL_POLICY, "intent": intent.dependency_hash, "session": session_id}),
        artifact_id=head["artifact_id"], version=int(head["version"]), content_hash=head["content_hash"],
        run_pipeline="vnexus.directions", policy_version=APPROVAL_POLICY, subject_type=SUBJECT_SELECTION,
        reason=f"Select direction {outcome.label if outcome else ''} for {intent.asset_role.value} ({brand_id}); "
               f"review verdict {outcome.verdict.value if outcome else 'n/a'} is a recommendation, not an approval",
        metadata={"brand_id": brand_id, "intent_id": intent_id, "candidate_id": candidate_id, "session_id": session_id})
    binding = ApprovalBinding(binding_id=record_id("vdb", {"kind": "SELECTION", "c": candidate_id, "a": approval["approval_id"]}),
                              kind="SELECTION", intent_id=intent_id, subject_artifact_id=head["artifact_id"],
                              subject_version=int(head["version"]), subject_sha256=cand.observed.sha256,
                              approval_id=approval["approval_id"], status="PENDING", created_by=principal.user_id, created_at=_now())
    _update_ledger(principal, project_id, intent_id, lambda led: (
        led["bindings"].append(binding.model_dump(mode="json")) if binding.binding_id not in
        {b["binding_id"] for b in led["bindings"]} else None,
        _event(led, "selection", "PENDING", started, candidate_id=candidate_id, approval_id=approval["approval_id"])))
    return {"status": "PENDING", "approval_id": approval["approval_id"], "binding": binding.model_dump(mode="json")}


def selection_verdict(principal: Principal, project_id: str, binding: dict) -> dict[str, Any]:
    from services.langgraph.agency.intake.release import artifact_release_verdict

    head = _head(binding["subject_artifact_id"])
    v = artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=binding["subject_artifact_id"],
                                 verified_version=binding["subject_version"], verified_hash=head["content_hash"]
                                 if int(head["version"]) == binding["subject_version"] else None,
                                 approval_id=binding.get("approval_id"), tenant_id=principal.tenant_id, project_id=project_id)
    return {"selected": v.allowed, "reasons": list(v.reasons)}


def _selected(principal: Principal, project_id: str, intent_id: str, candidate_id: str) -> Optional[dict]:
    ledger, _ = _ledger(project_id, intent_id)
    cand = load_candidate(project_id, intent_id, candidate_id)
    for b in reversed(ledger["bindings"]):
        if b["kind"] == "SELECTION" and b["subject_sha256"] == cand.observed.sha256 and selection_verdict(principal, project_id, b)["selected"]:
            return b
    return None


# --------------------------------------------------------------------------- reconstruction


def reconstruct_candidate(principal: Principal, brand_id: str, intent_id: str, project_id: str, *, candidate_id: str,
                          method: str, svg: Optional[str] = None, text_region: Optional[tuple[int, int, int, int]] = None,
                          optional_requested: bool = False) -> dict[str, Any]:
    from services.langgraph.agency.foundry.studio import observe

    started = time.monotonic()
    intent = load_intent(principal, brand_id, intent_id, project_id, write=True)
    cand = load_candidate(project_id, intent_id, candidate_id)
    need, why = reconstruct.decide(intent, cand)
    if need in ("KEEP_RASTER", "NOT_REQUIRED") or (need == "OPTIONAL" and not optional_requested):
        raise NotRequired(why, {"decision": need, "reason": why})
    binding = _selected(principal, project_id, intent_id, candidate_id)
    if binding is None:
        raise DirectionBlocked("reconstruction needs an approved human selection of this candidate's exact bytes",
                               {"candidate_id": candidate_id})
    data, ok = candidate_bytes(cand)
    if not ok:
        raise DirectionBlocked("the selected candidate's stored bytes changed", {"candidate_id": candidate_id})
    with tempfile.TemporaryDirectory(prefix="amc-vnexus-vector-") as w:
        work = Path(w)
        ref = reconstruct.reference_raster(cand, data, work / "ref")
        if method == "controlled_trace":
            out_svg, trace_meta = reconstruct.trace(intent, cand, data, text_box=text_region, work=work)
        elif method == "native_path_import":
            if not svg:
                raise ValueError("native_path_import needs the designer's SVG")
            out_svg, trace_meta = reconstruct.check_svg_import(svg), {"method_state": "designer geometry, validated and measured"}
        else:
            raise ValueError(f"unknown method {method}")
        cls, checks, geo = reconstruct.validate(out_svg, intent)
        fid = reconstruct.fidelity(out_svg, ref, text_box=text_region, work=work / "fid") if cls == "VECTOR" else \
            {"status": "NOT_RUN", "reason": f"classification {cls}"}
    checks.append({"check": "rendered_fidelity", "status": {"PASS": "PASS", "FAIL": "FAIL"}.get(fid["status"], "NOT_VERIFIED"),
                   "detail": json.dumps(fid.get("measured") or fid.get("reason"))})
    failed = [c for c in checks if c["status"] == "FAIL"] + ([{"check": "classification"}] if cls != "VECTOR" else [])
    status = "FAILED" if failed else ("NOT_VERIFIED" if fid["status"] != "PASS" else "PASSED")
    rid = record_id("vdv", {"c": candidate_id, "svg": hashlib.sha256(out_svg.encode()).hexdigest(), "m": method})
    stored = None
    new_cand = None
    if cls != "REJECTED":
        name = _key(intent_id, f"v{rid.removeprefix('vdv-')[:12]}-svg")
        entry = _put(principal, project_id, name, out_svg.encode(), "svg", depends_on=tuple(x for x in (cand.observed.artifact_id,) if x),
                     v2={"provenance_ref": f"vnexus-direction-reconstruction:{rid}", "synthetic": True})
        readback, _ = observe(entry["artifact_id"], _adapter())
        stored = {"artifact_id": entry["artifact_id"], "version": entry["version"],
                  "readback_sha256": hashlib.sha256(readback).hexdigest()}
        new_cand = _record_candidate(
            principal, intent, slot=cand.slot, data=out_svg.encode(), mime="image/svg+xml",
            route_id="local.trace" if method == "controlled_trace" else "manual.handoff",
            provenance=ProvenanceClass.RECORDED if method == "controlled_trace" else ProvenanceClass.USER_REPORTED,
            reported=CandidateReported(provider="local" if method == "controlled_trace" else "designer",
                                       model="avic.optimize" if method == "controlled_trace" else None,
                                       parameters={"method": method, **({"text_region": list(text_region)} if text_region else {}),
                                                   **{k: v for k, v in trace_meta.items() if k != "method_state"}},
                                       rights_basis=cand.reported.rights_basis),
            stored=stored, cost_measured=0 if method == "controlled_trace" else None, derived_from=candidate_id, reconstruction_id=rid,
            direction=f"vector reconstruction of {cand.direction}")
    rec = VectorReconstruction(
        reconstruction_id=rid, intent_id=intent_id, candidate_id=candidate_id, candidate_sha256=cand.observed.sha256,
        selection_approval_id=binding["approval_id"], need=intent.vector_need, method=method,  # type: ignore[arg-type]
        artifact_id=stored["artifact_id"] if stored else None, artifact_version=stored["version"] if stored else None,
        sha256=hashlib.sha256(out_svg.encode()).hexdigest() if stored else None, classification=cls,  # type: ignore[arg-type]
        checks=tuple(checks), fidelity=fid, status=status,  # type: ignore[arg-type]
        reasons=tuple(f"{c['check']}: {c.get('detail', '')}" for c in failed), text_handling=intent.vector_instructions["exact_text_rule"],
        created_by=principal.user_id, created_at=_now())
    _put(principal, project_id, _key(intent_id, f"v{rid.removeprefix('vdv-')[:12]}"), _json(rec.model_dump(mode="json")),
         "reconstruction", depends_on=tuple(x for x in ((stored or {}).get("artifact_id"),) if x))
    _update_ledger(principal, project_id, intent_id, lambda led: (
        led["reconstructions"].append(rid) if rid not in led["reconstructions"] else None,
        led["candidates"].append(new_cand.candidate_id) if new_cand and new_cand.candidate_id not in led["candidates"] else None,
        _event(led, "reconstruct", status, started, reconstruction_id=rid, method=method)))
    return {"reconstruction": rec.model_dump(mode="json"), "candidate": new_cand.model_dump(mode="json") if new_cand else None,
            "trace": {k: v for k, v in trace_meta.items()}}


def load_reconstruction(project_id: str, intent_id: str, rid: str) -> VectorReconstruction:
    stored = _read(project_id, _key(intent_id, f"v{rid.removeprefix('vdv-')[:12]}")) if rid.startswith("vdv-") else None
    if stored is None:
        raise LookupError("unknown reconstruction")
    return VectorReconstruction.model_validate(json.loads(stored[0]))


# --------------------------------------------------------------------------- freeze (existing genome review)


def master_keys(intent: CreativeIntent) -> tuple[str, str]:
    if intent.asset_role in LOGO_ROLES:
        return "visual.logo.master_artifact", "visual.logo.master_sha256"
    base = f"visual.assets.{intent.asset_role.value.lower()}"
    return f"{base}.master_artifact", f"{base}.master_sha256"


def freeze(principal: Principal, brand_id: str, intent_id: str, project_id: str, *, master_candidate_id: str,
           session_id: str) -> dict[str, Any]:
    """Bind an approved, release-reviewed master into a genome DRAFT and submit it to the existing genome review."""
    started = time.monotonic()
    intent = load_intent(principal, brand_id, intent_id, project_id, write=True)
    master = load_candidate(project_id, intent_id, master_candidate_id)
    source_id = master.derived_from or master.candidate_id
    reasons = []
    if master.provenance is ProvenanceClass.SIMULATED:
        reasons.append("SIMULATED_NOT_A_MASTER")
    if _selected(principal, project_id, intent_id, source_id) is None:
        reasons.append("NO_APPROVED_SELECTION: the source direction has no approved human selection")
    source = load_candidate(project_id, intent_id, source_id)
    need, _ = reconstruct.decide(intent, source)
    if master.derived_from is None and need == "RECONSTRUCT":
        reasons.append("RECONSTRUCTION_REQUIRED: this role needs an editable vector master")
    if master.reconstruction_id:
        rec = load_reconstruction(project_id, intent_id, master.reconstruction_id)
        if rec.status != "PASSED":
            reasons.append(f"RECONSTRUCTION_{rec.status}")
    session = load_session(principal, brand_id, intent_id, project_id, session_id)
    outcome = next((o for o in session.outcomes if o.candidate_id == master_candidate_id), None)
    if session.mode is not ReviewMode.RELEASE:
        reasons.append("RELEASE_REVIEW_REQUIRED")
    if outcome is None or outcome.verdict is not Verdict.READY_FOR_APPROVAL or outcome.asset_hash != master.observed.sha256:
        reasons.append("MASTER_NOT_READY_FOR_APPROVAL")
    current = _current_genome_ref(principal, intent)
    if current != intent.genome_ref or session.genome_ref != current:
        reasons.append("GENOME_CHANGED")
    _, ok = candidate_bytes(master)
    if not ok:
        reasons.append("STORED_BYTES_CHANGED")
    if reasons:
        return {"status": "BLOCKED", "reasons": reasons}
    from services.langgraph.persistence import vnexus as db

    approved = db.approved_version(brand_id, intent.scope, intent.scope_ref)
    base = GenomeDocument.model_validate(approved["document"]) if approved else GenomeDocument()
    key_ref, key_sha = master_keys(intent)
    flat = {**base.flatten(), key_ref: master.observed.artifact_id, key_sha: master.observed.sha256}
    doc = document_from_flat(flat, constraints=base.constraints, provenance=base.provenance)
    draft = genome_service.create_draft(principal, brand_id, scope=Scope(intent.scope), scope_ref=intent.scope_ref, document=doc)
    submitted = genome_service.submit_version(principal, draft["version_id"])
    binding = ApprovalBinding(binding_id=record_id("vdb", {"kind": "MASTER", "c": master_candidate_id, "v": draft["version_id"]}),
                              kind="MASTER", intent_id=intent_id, subject_artifact_id=master.observed.artifact_id or "",
                              subject_version=int(master.observed.artifact_version or 0), subject_sha256=master.observed.sha256,
                              approval_id=submitted.get("approval_id"), genome_version_id=draft["version_id"],
                              genome_keys={key_ref: master.observed.artifact_id or "", key_sha: master.observed.sha256},
                              status="PENDING_GENOME_REVIEW", created_by=principal.user_id, created_at=_now())
    _update_ledger(principal, project_id, intent_id, lambda led: (
        led["bindings"].append(binding.model_dump(mode="json")),
        _event(led, "freeze", "PENDING_GENOME_REVIEW", started, genome_version_id=draft["version_id"], sha256=master.observed.sha256)))
    return {"status": "PENDING_GENOME_REVIEW", "binding": binding.model_dump(mode="json"), "genome_version_id": draft["version_id"],
            "approval_id": submitted.get("approval_id"),
            "note": "decide on /approvals/{id}/decide; the brand book and identity production read the master only after approval"}


# --------------------------------------------------------------------------- read model


def state(principal: Principal, brand_id: str, intent_id: str, project_id: str) -> dict[str, Any]:
    intent = load_intent(principal, brand_id, intent_id, project_id)
    ledger, _ = _ledger(project_id, intent_id)
    current = _current_genome_ref(principal, intent)
    cands = []
    for cid in ledger["candidates"]:
        c = load_candidate(project_id, intent_id, cid)
        _, ok = candidate_bytes(c)
        cands.append({**c.model_dump(mode="json"), "stored_bytes_match": ok, "stale": c.genome_ref != current,
                      "decision": reconstruct.decide(intent, c)[0]})
    sessions = []
    for sid in ledger["sessions"]:
        s = load_session(principal, brand_id, intent_id, project_id, sid)
        sessions.append({"session_id": s.session_id, "mode": s.mode.value, "verdict": s.recommendation.verdict.value,
                         "label": s.recommendation.label, "candidate_id": s.recommendation.candidate_id, "created_at": s.created_at,
                         "created_by": s.created_by, "stale": s.genome_ref != current, "lenses_required_missing": list(s.lenses_required_missing),
                         "work_orders": len(s.work_orders)})
    bindings = []
    for b in ledger["bindings"]:
        live = dict(b)
        if b["kind"] == "SELECTION":
            live.update(selection_verdict(principal, project_id, b))
        else:
            v = genome_service.get_version(principal, b["genome_version_id"])
            live["genome_status"] = v["status"]
        bindings.append(live)
    recs = [load_reconstruction(project_id, intent_id, r).model_dump(mode="json") for r in ledger["reconstructions"]]
    return {"intent": intent.model_dump(mode="json"), "current_genome_ref": current, "stale": current != intent.genome_ref,
            "candidates": cands, "sessions": sessions, "reconstructions": recs, "bindings": bindings, "events": ledger["events"][-50:]}


def list_intents(principal: Principal, brand_id: str, project_id: str) -> list[dict[str, Any]]:
    from services.langgraph.persistence.projects import list_project_artifacts

    _target(principal, brand_id, project_id, write=False)
    out = []
    for a in list_project_artifacts(project_id, artifact_type="creative_concept", query="-intent", limit=1000):
        key = a.artifact_key or ""
        if key.startswith("foundry-vdx-") and key.endswith("-intent"):
            stored = _read(project_id, key.removeprefix("foundry-"))
            if stored:
                doc = json.loads(stored[0])
                if doc.get("brand_id") == brand_id and doc.get("tenant_id") == principal.tenant_id:
                    out.append({"intent_id": doc["intent_id"], "asset_role": doc["asset_role"], "status": doc["status"],
                                "objective": doc["brief"]["objective"], "genome_ref": doc["genome_ref"]})
    return out


def read_candidate(principal: Principal, brand_id: str, intent_id: str, project_id: str, candidate_id: str) -> tuple[bytes, str]:
    load_intent(principal, brand_id, intent_id, project_id)
    ledger, _ = _ledger(project_id, intent_id)
    if candidate_id not in ledger["candidates"]:
        raise LookupError("unknown candidate")
    cand = load_candidate(project_id, intent_id, candidate_id)
    data, ok = candidate_bytes(cand)
    if not ok:
        raise ValueError("stored bytes do not match the recorded hash")
    return data, cand.observed.mime


__all__ = ["DirectionBlocked", "NotRequired", "candidate_bytes", "create_intent", "create_review", "freeze", "generate", "handoff",
           "import_candidate", "list_intents", "load_candidate", "load_intent", "load_reconstruction", "load_session", "master_keys",
           "read_candidate", "reconstruct_candidate", "request_selection", "selection_verdict", "state"]
