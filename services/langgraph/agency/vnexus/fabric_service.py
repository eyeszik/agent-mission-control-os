"""VNEXUS render jobs: a truthful lifecycle over the provider-neutral media fabric.

    PLANNED -> VALIDATED -> AUTHORIZED -> QUEUED -> RUNNING -> ARTIFACT_RECEIVED -> QC_PASSED
       \\           \\             \\          \\          \\                \\
        FAILED/CANCELED at every step that can fail; RUNNING -> QUEUED for a bounded retry

Rules that hold regardless of provider:

* the idempotency key is unique per tenant: a replay returns the same job, a
  different request under the same key is refused;
* a job whose estimate exceeds its budget ceiling fails validation; a job
  with a non-zero estimate is authorized only by an approval decided by
  someone else on the existing approval route; zero-cost local work is
  authorized by the requesting principal's write access and recorded so;
* ARTIFACT_RECEIVED needs bytes whose hash matches what the provider
  reported; they are then stored and read back; QC_PASSED needs the format
  checks to pass on the stored bytes;
* simulated (mock) output can pass the lifecycle for testing but is stored
  outside the project's deliverables and can never be claimed as generated;
* a provider exception is contained in its job: it fails that job only.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import vnexus as db
from services.langgraph.security.auth import Principal

from . import service
from .media_fabric import (
    MIME,
    Capability,
    MediaRequest,
    ProviderKind,
    ProviderPermanentError,
    ProviderTransientError,
    can_claim_generated,
    get_provider,
    work_dir,
)

TERMINAL = frozenset({"QC_PASSED", "CANCELED"})
CANCELABLE = ("PLANNED", "VALIDATED", "AUTHORIZED", "QUEUED")
SUBJECT_MEDIA_JOB = "VNEXUS_MEDIA_JOB"


class RateLimited(RuntimeError):
    pass


def _job(principal: Principal, job_id: str) -> dict:
    row = db.get_media_job(job_id)
    if row is None or row["tenant_id"] != principal.tenant_id:
        raise db.VnexusNotFound(f"media job {job_id} not found")
    service.authorize(principal, row["project_id"])
    return row


def public(row: dict) -> dict:
    artifact = row.get("artifact") or {}
    return {**{k: row.get(k) for k in ("job_id", "project_id", "provider_id", "capability", "request_hash", "idempotency_key", "state",
                                       "estimate", "budget_ceiling_minor", "currency", "authorized_by", "authorized_at", "attempts",
                                       "max_attempts", "provider_job_ref", "artifact", "qc", "error", "created_by", "created_at",
                                       "updated_at", "version")},
            "label": (row.get("request") or {}).get("label", ""),
            "claimable_as_generated": can_claim_generated(row["state"], artifact), "simulated": bool(artifact.get("simulated"))}


def plan(principal: Principal, project_id: str, *, provider_id: str, request: MediaRequest, idempotency_key: str,
         budget_ceiling_minor: int = 0, max_attempts: int = 2) -> dict:
    service.authorize(principal, project_id, write=True)
    get_provider(provider_id)
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts is between 1 and 3")
    body = request.model_dump(mode="json")
    row, _ = db.create_media_job(tenant_id=principal.tenant_id, project_id=project_id, provider_id=provider_id,
                                 capability=request.capability.value, request=body, request_hash=canonical_hash(body),
                                 idempotency_key=idempotency_key, budget_ceiling_minor=budget_ceiling_minor,
                                 max_attempts=max_attempts, actor=principal.user_id)
    return row


def validate(principal: Principal, job_id: str) -> dict:
    row = _job(principal, job_id)
    service.authorize(principal, row["project_id"], write=True)
    if row["state"] != "PLANNED":
        return row
    provider = get_provider(row["provider_id"])
    request = MediaRequest.model_validate(row["request"])
    try:
        check = provider.validate(request)
        estimate = provider.estimate(request)
    except Exception as exc:  # noqa: BLE001 - a provider fault fails this job only
        return db.transition_media_job(job_id, expected_version=row["version"], from_state="PLANNED", to_state="FAILED",
                                       actor=principal.user_id, reason="provider fault during validation", error=f"PROVIDER_FAULT: {exc}"[:500])
    errors = list(check.errors)
    if estimate.amount_minor > row["budget_ceiling_minor"]:
        errors.append(f"BUDGET_EXCEEDED: estimate {estimate.amount_minor} > ceiling {row['budget_ceiling_minor']}")
    if errors:
        return db.transition_media_job(job_id, expected_version=row["version"], from_state="PLANNED", to_state="FAILED",
                                       actor=principal.user_id, reason="validation failed", error="; ".join(errors)[:500],
                                       estimate=estimate.model_dump(mode="json"))
    return db.transition_media_job(job_id, expected_version=row["version"], from_state="PLANNED", to_state="VALIDATED",
                                   actor=principal.user_id, reason="validated", estimate=estimate.model_dump(mode="json"),
                                   currency=estimate.currency)


def authorize(principal: Principal, job_id: str) -> dict:
    row = _job(principal, job_id)
    service.authorize(principal, row["project_id"], write=True)
    if row["state"] != "VALIDATED":
        return row
    estimate = row.get("estimate") or {}
    if int(estimate.get("amount_minor", 0)) == 0:
        return db.transition_media_job(job_id, expected_version=row["version"], from_state="VALIDATED", to_state="AUTHORIZED",
                                       actor=principal.user_id, reason="zero-cost local work; requester has write access",
                                       authorized_by=principal.user_id, authorized_at=db.now_iso())
    return _spend_authorization(principal, row)


def _spend_authorization(principal: Principal, row: dict) -> dict:
    """Any non-zero estimate needs a human approval bound to the exact request and estimate."""
    from services.langgraph.agency.intake.release import open_artifact_approval
    from services.langgraph.persistence.approvals import get_approval

    estimate = row["estimate"]
    subject_hash = canonical_hash({"request_hash": row["request_hash"], "estimate": {k: estimate.get(k) for k in ("amount_minor", "currency")}})
    approval_id = estimate.get("approval_id")
    if not approval_id:
        approval = open_artifact_approval(
            principal, tenant_id=row["tenant_id"], project_id=row["project_id"], mission_id=f"vnexus-media:{row['job_id']}",
            contract_hash=subject_hash, artifact_id=row["job_id"], version=int(row["version"]), content_hash=subject_hash,
            run_pipeline="vnexus.media_spend", policy_version="amc-vnexus-spend/v1", subject_type=SUBJECT_MEDIA_JOB,
            reason=f"Authorize spend of {estimate.get('amount_minor')} {estimate.get('currency')} (minor units) on {row['provider_id']}")
        return db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="VALIDATED", to_state="VALIDATED",
                                       actor=principal.user_id, reason="spend approval requested",
                                       estimate={**estimate, "approval_id": approval["approval_id"], "subject_hash": subject_hash})
    approval = get_approval(approval_id)
    if approval is None or approval.get("status") != "resolved":
        return row
    if approval.get("decision") != "approve":
        return db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="VALIDATED", to_state="CANCELED",
                                       actor=approval.get("reviewer") or "system", reason="spend rejected")
    if approval.get("subject_hash") != subject_hash or approval.get("reviewer") == row["created_by"]:
        return db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="VALIDATED", to_state="FAILED",
                                       actor="system", reason="spend approval does not match", error="SPEND_APPROVAL_INVALID")
    return db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="VALIDATED", to_state="AUTHORIZED",
                                   actor=approval["reviewer"], reason="spend approved", authorized_by=approval["reviewer"],
                                   authorized_at=approval.get("decided_at") or db.now_iso())


def cancel(principal: Principal, job_id: str) -> dict:
    row = _job(principal, job_id)
    service.authorize(principal, row["project_id"], write=True)
    if row["state"] not in CANCELABLE:
        raise db.VnexusConflict(f"a {row['state']} job cannot be canceled")
    return db.transition_media_job(job_id, expected_version=row["version"], from_state=row["state"], to_state="CANCELED",
                                   actor=principal.user_id, reason="canceled by requester")


def retry(principal: Principal, job_id: str) -> dict:
    """A failed job may be re-queued only if its last failure was transient and attempts remain."""
    row = _job(principal, job_id)
    service.authorize(principal, row["project_id"], write=True)
    if row["state"] != "FAILED" or not (row.get("error") or "").startswith("TRANSIENT") or row["attempts"] >= row["max_attempts"]:
        raise db.VnexusConflict("only a transiently failed job with attempts left can be retried")
    db.transition_media_job(job_id, expected_version=row["version"], from_state="FAILED", to_state="QUEUED",
                            actor=principal.user_id, reason="manual retry")
    return run(principal, job_id)


def _rate_check(row: dict, limit: int) -> None:
    since = (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if db.recent_runs(row["tenant_id"], row["provider_id"], since) >= limit:
        raise RateLimited(f"{row['provider_id']} allows {limit} runs per minute for this tenant")


def run(principal: Principal, job_id: str, *, depends_on: tuple[str, ...] = ()) -> dict:
    row = _job(principal, job_id)
    service.authorize(principal, row["project_id"], write=True)
    if row["state"] == "AUTHORIZED":
        row = db.transition_media_job(job_id, expected_version=row["version"], from_state="AUTHORIZED", to_state="QUEUED",
                                      actor=principal.user_id, reason="queued")
    if row["state"] != "QUEUED":
        return row
    provider = get_provider(row["provider_id"])
    caps = provider.capabilities()
    request = MediaRequest.model_validate(row["request"])
    while True:
        _rate_check(row, caps.rate_limit_per_minute)
        row = db.transition_media_job(job_id, expected_version=row["version"], from_state="QUEUED", to_state="RUNNING",
                                      actor=principal.user_id, reason=f"attempt {row['attempts'] + 1}", attempts=row["attempts"] + 1)
        started = time.monotonic()
        try:
            job = provider.submit(request, job_key=job_id, work_dir=work_dir())
            artifact = provider.retrieve(job.provider_job_ref)
            if time.monotonic() - started > caps.timeout_s:
                raise ProviderTransientError(f"TIMEOUT after {caps.timeout_s}s")
        except ProviderTransientError as exc:
            if row["attempts"] < row["max_attempts"]:
                row = db.transition_media_job(job_id, expected_version=row["version"], from_state="RUNNING", to_state="QUEUED",
                                              actor="system", reason=f"transient failure, retrying: {exc}"[:500])
                continue
            return db.transition_media_job(job_id, expected_version=row["version"], from_state="RUNNING", to_state="FAILED",
                                           actor="system", reason="attempts exhausted", error=f"TRANSIENT: {exc}"[:500])
        except ProviderPermanentError as exc:
            return db.transition_media_job(job_id, expected_version=row["version"], from_state="RUNNING", to_state="FAILED",
                                           actor="system", reason="permanent failure", error=f"PERMANENT: {exc}"[:500])
        except Exception as exc:  # noqa: BLE001 - any adapter fault is isolated to this job
            return db.transition_media_job(job_id, expected_version=row["version"], from_state="RUNNING", to_state="FAILED",
                                           actor="system", reason="provider fault", error=f"PROVIDER_FAULT: {type(exc).__name__}: {exc}"[:500])
        return _receive(principal, row, provider, request, artifact, job.provider_job_ref, depends_on=depends_on)


def _receive(principal: Principal, row: dict, provider: Any, request: MediaRequest, artifact: Any, ref: str,
             *, depends_on: tuple[str, ...]) -> dict:
    observed = hashlib.sha256(artifact.data).hexdigest()
    if observed != artifact.sha256:
        return db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="RUNNING", to_state="FAILED",
                                       actor="system", reason="received bytes do not match the provider's hash",
                                       error=f"INTEGRITY: reported {artifact.sha256[:16]} observed {observed[:16]}", provider_job_ref=ref)
    from services.langgraph.agency.foundry.studio import observe, store
    from services.langgraph.api.routes._project_common import storage_adapter

    adapter = storage_adapter()
    simulated = artifact.simulated or provider.kind is ProviderKind.MOCK
    if simulated:
        stored = adapter.put_bytes(tenant_id=row["tenant_id"], project_id=row["project_id"], data=artifact.data)
        readback = adapter.get_bytes(stored.storage_uri)
        record = {"storage_uri": stored.storage_uri, "artifact_id": None, "version": None}
    else:
        name = f"vnexus-{row['capability'].lower()}-{row['job_id'][-12:]}{_ext(request.capability)}"
        head = store(principal, row["project_id"], name, artifact.data, mime=artifact.mime, artifact_type="media_asset",
                     subtype=f"vnexus_{row['capability'].lower()}", adapter=adapter, depends_on=depends_on,
                     v2={"provenance_ref": f"vnexus-job:{row['job_id']}", "renderer": artifact.renderer,
                         "renderer_version": artifact.renderer_version, "synthetic": True})
        readback, stored_head = observe(head["artifact_id"], adapter)
        record = {"artifact_id": head["artifact_id"], "version": head["version"], "storage_uri": stored_head.get("content_location")}
    read_sha = hashlib.sha256(readback).hexdigest()
    record.update({"sha256": observed, "readback_sha256": read_sha, "bytes": len(artifact.data), "mime": artifact.mime,
                   "simulated": simulated, "renderer": artifact.renderer, "renderer_version": artifact.renderer_version,
                   "label": "SIMULATED: test output, not a generated asset" if simulated else "synthetic render (not a photograph)"})
    if read_sha != observed:
        return db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="RUNNING", to_state="FAILED",
                                       actor="system", reason="stored bytes did not read back", error="INTEGRITY: read-back mismatch",
                                       artifact=record, provider_job_ref=ref)
    row = db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="RUNNING", to_state="ARTIFACT_RECEIVED",
                                  actor="system", reason="artifact stored and read back", artifact=record, provider_job_ref=ref)
    result = quality_control(readback, request, simulated=simulated)
    target = "QC_PASSED" if result["passed"] else "FAILED"
    return db.transition_media_job(row["job_id"], expected_version=row["version"], from_state="ARTIFACT_RECEIVED", to_state=target,
                                   actor="system", reason="quality control", qc=result,
                                   error=None if result["passed"] else "QC: " + ", ".join(c["check"] for c in result["checks"] if not c["passed"]))


def _ext(capability: Capability) -> str:
    return {"image/svg+xml": ".svg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf", "video/mp4": ".mp4"}[MIME[capability]]


def quality_control(data: bytes, request: MediaRequest, *, simulated: bool) -> dict[str, Any]:
    """Format checks on the stored bytes. A format without a verifier is reported, never passed silently."""
    from services.langgraph.agency.visual.verify import verify_media

    mime = "image/svg+xml" if simulated else MIME[request.capability]
    expect: dict[str, Any] = {k: v for k, v in (("width", request.width), ("height", request.height)) if v}
    if request.capability is Capability.MOTION_MP4 and not simulated:
        expect.update({"fps": request.spec.get("fps"), "frames": len(request.spec.get("frames") or [])})
    if mime in {"image/png", "image/svg+xml", "video/mp4"}:
        if mime == "image/png":
            expect.setdefault("min_unique_colours", int(request.spec.get("min_unique_colours", 2)))
        v = verify_media(data, mime_type=mime, expect=expect)
        checks = [{"check": c["check"], "level": c["level"], "passed": bool(c["passed"]), "detail": c["detail"]} for c in v.checks
                  if c["passed"] is not None]
        inconclusive = [c["check"] for c in v.checks if c["passed"] is None]
    elif mime == "image/webp":
        checks, inconclusive = _webp_checks(data, expect), []
    elif mime == "application/pdf":
        checks, inconclusive = _pdf_checks(data), []
    else:
        checks, inconclusive = [], [f"NO_VERIFIER_FOR:{mime}"]
    passed = bool(checks) and all(c["passed"] for c in checks) and not inconclusive
    return {"checks": checks, "inconclusive": inconclusive, "passed": passed, "simulated": simulated,
            "verdict": "SIMULATED_ONLY" if simulated and passed else ("PASSED" if passed else "FAILED")}


def _webp_checks(data: bytes, expect: dict) -> list[dict[str, Any]]:
    out = [{"check": "webp_signature", "level": "Q0", "passed": data[:4] == b"RIFF" and data[8:12] == b"WEBP", "detail": f"{len(data)} bytes"}]
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            im.load()
            dims = f"{im.width}x{im.height}"
            out.append({"check": "webp_decodes", "level": "Q1", "passed": im.format == "WEBP", "detail": dims})
            if expect.get("width"):
                out.append({"check": "dimensions", "level": "Q2", "passed": (im.width, im.height) == (expect["width"], expect["height"]),
                            "detail": dims})
    except Exception as exc:  # noqa: BLE001
        out.append({"check": "webp_decodes", "level": "Q1", "passed": False, "detail": str(exc)[:200]})
    return out


def _pdf_checks(data: bytes) -> list[dict[str, Any]]:
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    return [{"check": "pdf_header", "level": "Q0", "passed": data.startswith(b"%PDF-"), "detail": data[:8].decode("latin-1")},
            {"check": "pdf_trailer", "level": "Q1", "passed": b"%%EOF" in data[-1024:], "detail": f"{len(data)} bytes"},
            {"check": "pdf_pages", "level": "Q2", "passed": pages >= 1, "detail": f"{pages} page(s)"}]


def execute(principal: Principal, project_id: str, *, provider_id: str, request: MediaRequest, idempotency_key: str,
            budget_ceiling_minor: int = 0, depends_on: tuple[str, ...] = ()) -> dict:
    """Plan, validate, authorize and run in one call. Stops wherever the lifecycle stops (e.g. awaiting spend approval)."""
    row = plan(principal, project_id, provider_id=provider_id, request=request, idempotency_key=idempotency_key,
               budget_ceiling_minor=budget_ceiling_minor)
    row = validate(principal, row["job_id"])
    row = authorize(principal, row["job_id"])
    if row["state"] in ("AUTHORIZED", "QUEUED"):
        row = run(principal, row["job_id"], depends_on=depends_on)
    return row


def get_job(principal: Principal, job_id: str) -> dict:
    row = _job(principal, job_id)
    return {**public(row), "transitions": db.media_job_transitions(job_id)}


def list_jobs(principal: Principal, project_id: str) -> list[dict]:
    service.authorize(principal, project_id)
    return [public(r) for r in db.list_media_jobs(project_id)]


__all__ = ["CANCELABLE", "RateLimited", "TERMINAL", "authorize", "cancel", "execute", "get_job", "list_jobs", "plan", "public",
           "quality_control", "retry", "run", "validate"]
