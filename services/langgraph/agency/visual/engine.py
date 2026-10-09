"""Local visual production: route -> render -> persist bytes -> independent readback.

Persisted media are ordinary Project OS ``media_asset`` artifacts (N1/N4 rows,
versioned, CAS-protected), so approval, the release gate and lineage work on
them exactly as on any other artifact. A rerun with identical bytes adds no
version; changed bytes add one, which invalidates earlier verification and
approvals through the shared release gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.intake.contracts import ReleaseVerdict
from services.langgraph.agency.intake.release import artifact_release_verdict, open_artifact_approval
from services.langgraph.agency.project_os.storage import LocalStorageAdapter, StorageAdapter
from services.langgraph.security.auth import Principal

from .capabilities import probe_all
from .contracts import Capability, MediaVerification, RenderReceipt, Route, RouteDecision, VisualIntent
from .renderers import encode_video, render_blender, render_diffusion, render_vector_mark
from .router import route
from .verify import verify_media

RUN_PIPELINE = "visual_production"
SVG_MARK_SIZE = "1200x1200"
SVG_RENDER_SIZES = (32, 128, 512)
APPROVAL_POLICY_VERSION = "amc-visual-approval/v1"


class VisualJobResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str  # PRODUCED | BLOCKED | FAILED
    decision: RouteDecision
    receipts: tuple[RenderReceipt, ...] = ()
    artifact_id: Optional[str] = None
    version: Optional[int] = None
    content_hash: Optional[str] = None
    mime_type: Optional[str] = None
    verification: Optional[MediaVerification] = None
    reasons: tuple[str, ...] = ()


def intent_key(intent: VisualIntent) -> str:
    return canonical_hash(intent.model_dump(mode="json"))


def _persist(*, principal: Principal, project_id: str, artifact_key: str, data: bytes, mime: str, intent: VisualIntent,
             provenance_ref: str, adapter: StorageAdapter) -> tuple[str, int, str]:
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import (
        create_project_artifact,
        project_artifact_id,
        register_storage_object,
        revise_project_artifact,
    )

    stored = adapter.put_bytes(tenant_id=principal.tenant_id, project_id=project_id, data=data)
    register_storage_object(tenant_id=principal.tenant_id, project_id=project_id, stored=stored, mime_type=mime)
    dims = SVG_MARK_SIZE if mime == "image/svg+xml" else f"{intent.width}x{intent.height}"
    v2 = {"mime_type": mime, "media_type": "video" if mime.startswith("video/") else "image",
          "dimensions": dims, "provenance_ref": provenance_ref}
    if mime.startswith("video/"):
        v2["duration_seconds"] = round(intent.frames / intent.fps, 3)
    artifact_id = project_artifact_id(project_id, artifact_key)
    head = get_artifact(artifact_id)
    if head is None:
        meta = create_project_artifact(tenant_id=principal.tenant_id, project_id=project_id, actor=principal.user_id,
                                       artifact_key=artifact_key, artifact_type="media_asset", adapter=adapter,
                                       content_hash=stored.content_hash, storage_uri=stored.storage_uri,
                                       subtype="local_render", v2=v2)
        return meta.artifact_id, meta.version, stored.content_hash
    if head.get("content_hash") == stored.content_hash:
        return artifact_id, int(head["version"]), stored.content_hash
    revised = revise_project_artifact(project_id=project_id, artifact_id=artifact_id, actor=principal.user_id,
                                      adapter=adapter, expected_version=int(head["version"]),
                                      content_hash=stored.content_hash, storage_uri=stored.storage_uri, v2_patch=v2)
    return artifact_id, int(revised["artifact"].version), stored.content_hash


def readback_verify(artifact_id: str, *, intent: VisualIntent, adapter: StorageAdapter) -> MediaVerification:
    """Independent: reads the head row and the stored bytes, never the renderer's output."""
    from services.langgraph.persistence.agency_kernel import get_artifact

    head = get_artifact(artifact_id)
    if head is None:
        raise LookupError(f"artifact {artifact_id} is missing")
    mime = ((head.get("metadata") or {}).get("v2") or {}).get("mime_type") or "application/octet-stream"
    data = adapter.get_bytes(head["content_location"])
    expect = {"width": intent.width, "height": intent.height, "fps": intent.fps, "frames": intent.frames}
    if mime == "image/svg+xml":
        expect = {"palette": sorted(set(intent.palette.values())), "render_sizes": SVG_RENDER_SIZES}
    return verify_media(data, mime_type=mime, expect=expect, source_assets=intent.source_assets,
                        artifact_id=artifact_id, version=int(head["version"]), recorded_hash=head.get("content_hash"))


def produce(principal: Principal, project_id: str, intent: VisualIntent, *, work_dir: Path, artifact_key: str,
            export_root: Optional[Path] = None, adapter: Optional[StorageAdapter] = None, prompt: str = "",
            logical_tick: Optional[int] = None, capabilities: Optional[Mapping[Route, Capability]] = None) -> VisualJobResult:
    if not principal.can_access_project(project_id):
        raise PermissionError("principal cannot access this project")
    store = adapter or LocalStorageAdapter(export_root or work_dir)
    decision = route(intent, capabilities if capabilities is not None else probe_all())
    if decision.status == "BLOCKED" or decision.route is None:
        return VisualJobResult(status="BLOCKED", decision=decision, reasons=decision.reasons)

    work_dir = Path(work_dir) / intent_key(intent)[:16]
    receipts: list[RenderReceipt] = []
    if decision.route is Route.BLENDER_CYCLES:
        r = render_blender(intent, work_dir / "frames", logical_tick=logical_tick)
        receipts.append(r)
        if r.status != "SUCCEEDED":
            return VisualJobResult(status="FAILED", decision=decision, receipts=tuple(receipts), reasons=r.reasons)
        out_path, mime = Path(r.outputs[0]["path"]), "image/png"
    elif decision.route is Route.LOCAL_VIDEO:
        r = render_blender(intent, work_dir / "frames", logical_tick=logical_tick)
        receipts.append(r)
        if r.status != "SUCCEEDED":
            return VisualJobResult(status="FAILED", decision=decision, receipts=tuple(receipts), reasons=r.reasons)
        v = encode_video([Path(o["path"]) for o in r.outputs], work_dir / "master.mp4", fps=intent.fps, logical_tick=logical_tick)
        receipts.append(v)
        if v.status != "SUCCEEDED":
            return VisualJobResult(status="FAILED", decision=decision, receipts=tuple(receipts), reasons=v.reasons)
        out_path, mime = Path(v.outputs[0]["path"]), "video/mp4"
    elif decision.route is Route.OFFLINE_DIFFUSION:
        r = render_diffusion(intent, prompt, work_dir / "diffusion", logical_tick=logical_tick)
        receipts.append(r)
        if r.status != "SUCCEEDED":
            return VisualJobResult(status="FAILED", decision=decision, receipts=tuple(receipts), reasons=r.reasons)
        out_path, mime = Path(r.outputs[0]["path"]), "image/png"
    elif decision.route is Route.VECTOR:
        r = render_vector_mark(intent, work_dir / "vector", logical_tick=logical_tick)
        receipts.append(r)
        out_path, mime = Path(r.outputs[0]["path"]), "image/svg+xml"
    else:
        # Three.js scenes are captured by the browser harness (agency.visual.browser); the
        # engine does not fake a render it cannot produce.
        return VisualJobResult(status="BLOCKED", decision=decision, reasons=(f"ROUTE_NOT_HANDLED_BY_ENGINE:{decision.route.value}",))

    provenance_ref = "render:" + canonical_hash([rc.model_dump(mode="json") for rc in receipts])[:32]
    artifact_id, version, content_hash = _persist(principal=principal, project_id=project_id, artifact_key=artifact_key,
                                                  data=out_path.read_bytes(), mime=mime, intent=intent,
                                                  provenance_ref=provenance_ref, adapter=store)
    verification = readback_verify(artifact_id, intent=intent, adapter=store)
    status = "PRODUCED" if verification.status == "PASSED" else "FAILED"
    return VisualJobResult(status=status, decision=decision, receipts=tuple(receipts), artifact_id=artifact_id,
                           version=version, content_hash=content_hash, mime_type=mime, verification=verification,
                           reasons=verification.findings)


def request_approval(principal: Principal, project_id: str, result: VisualJobResult, *, mission_id: str) -> dict:
    if result.status != "PRODUCED" or result.verification is None or result.verification.status != "PASSED":
        raise ValueError("only produced, independently verified media can be put up for approval")
    return open_artifact_approval(
        principal, tenant_id=principal.tenant_id, project_id=project_id, mission_id=mission_id,
        contract_hash=canonical_hash(result.decision.model_dump(mode="json")), artifact_id=result.artifact_id,
        version=result.version, content_hash=result.content_hash, run_pipeline=RUN_PIPELINE,
        policy_version=APPROVAL_POLICY_VERSION, subject_type="VISUAL_ARTIFACT",
        reason="Locally rendered media requires human visual, brand and realism review before release",
        metadata={"route": result.decision.route.value if result.decision.route else None},
    )


def release_verdict(principal: Principal, project_id: str, result: VisualJobResult, *, approval_id: Optional[str],
                    simulated: bool = False) -> ReleaseVerdict:
    v = result.verification
    return artifact_release_verdict(simulated=simulated, verification_passed=v is not None and v.status == "PASSED",
                                    artifact_id=result.artifact_id, verified_version=result.version,
                                    verified_hash=result.content_hash, approval_id=approval_id,
                                    tenant_id=principal.tenant_id, project_id=project_id)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["VisualJobResult", "intent_key", "produce", "readback_verify", "release_verdict", "request_approval"]
