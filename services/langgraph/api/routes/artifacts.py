from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.langgraph.persistence.artifacts import (
    ArtifactIntegrityError,
    ArtifactSizeError,
    get_artifact,
    list_artifacts,
    soft_delete_artifact,
    store_artifact,
)
from services.langgraph.security.auth import Principal, authorize_project, authorize_resource, get_principal

router = APIRouter()

_ALLOWED_KINDS_MAX_LENGTH = 120


class ArtifactUploadRequest(BaseModel):
    project_id: str
    kind: str = Field(min_length=1, max_length=_ALLOWED_KINDS_MAX_LENGTH)
    content_base64: str = Field(min_length=1)
    content_type: str = Field(default="application/octet-stream", max_length=120)
    run_id: str | None = None


@router.post("", status_code=201)
def upload_artifact(
    req: ArtifactUploadRequest,
    principal: Principal = Depends(get_principal),
):
    authorize_project(principal, req.project_id)
    try:
        content = base64.b64decode(req.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64") from exc
    try:
        record = store_artifact(
            principal.tenant_id,
            req.project_id,
            req.kind.strip(),
            content,
            content_type=req.content_type.strip() or "application/octet-stream",
            run_id=req.run_id,
            created_by=principal.user_id,
        )
    except ArtifactSizeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return {
        "artifact_id": record["artifact_id"],
        "version": record["version"],
        "kind": record["kind"],
        "content_hash": record["content_hash"],
        "object_id": record["object_id"],
        "content_type": record.get("content_type"),
        "run_id": record.get("run_id"),
        "created_at": record["created_at"],
    }


@router.get("")
def list_project_artifacts(
    project_id: str = Query(...),
    run_id: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
):
    authorize_project(principal, project_id)
    artifacts = list_artifacts(principal.tenant_id, project_id=project_id, run_id=run_id)
    return {
        "project_id": project_id,
        "artifacts": [
            {
                "artifact_id": a["artifact_id"],
                "version": a["version"],
                "kind": a["kind"],
                "object_id": a["object_id"],
                "deleted": bool(a.get("deleted")),
                "created_at": a["created_at"],
            }
            for a in artifacts
        ],
    }


@router.get("/{artifact_id}")
def get_artifact_detail(
    artifact_id: str,
    download: bool = Query(default=False),
    principal: Principal = Depends(get_principal),
):
    try:
        record = get_artifact(artifact_id, principal.tenant_id, include_content=download)
    except ArtifactIntegrityError as exc:
        # Read-back verification failed: the stored bytes no longer match the
        # content hash. Surface as a storage integrity fault, not a 404.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    authorize_resource(principal, record["tenant_id"], record["project_id"])
    if record.get("deleted") and not download:
        # Tombstoned versions stay retrievable for audit by explicit download.
        pass
    response = {
        "artifact_id": record["artifact_id"],
        "version": record["version"],
        "kind": record["kind"],
        "object_id": record["object_id"],
        "content_hash": record["content_hash"],
        "run_id": record.get("run_id"),
        "deleted": bool(record.get("deleted")),
        "created_at": record["created_at"],
    }
    if download:
        import base64 as _b64

        response["content_base64"] = _b64.b64encode(record["content"]).decode("ascii")
    return response


@router.delete("/{artifact_id}")
def delete_artifact(
    artifact_id: str,
    principal: Principal = Depends(get_principal),
):
    record = get_artifact(artifact_id, principal.tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    authorize_resource(principal, record["tenant_id"], record["project_id"])
    deleted = soft_delete_artifact(artifact_id, principal.tenant_id)
    return {"artifact_id": artifact_id, "deleted": deleted}
