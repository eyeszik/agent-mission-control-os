"""Digital asset management: uploads, rendered-media ingest, rights radar.

DAM is a view over the N4 registry, not a second store: every asset is an
``agency_artifacts`` row (``media_asset`` for rendered/uploaded media) whose
bytes live in content-addressed object storage and whose v2 metadata carries
format, dimensions, duration, master/derivative links, prompt and rights refs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from services.langgraph.agency.project_os.models import ArtifactMetadataV2
from services.langgraph.agency.project_os.storage import StorageAdapter
from services.langgraph.agency.project_os.video import read_freevideoforge_output
from services.langgraph.persistence.database import normalize_record, table, transaction
from services.langgraph.persistence.projects import (
    _append_event,
    create_project_artifact,
    list_asset_rights,
    register_storage_object,
    require_project_workspace,
)
from services.langgraph.agency.project_os.vocabulary import ActivityType

MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# Allowlist by sniffed magic bytes, never by the client's declared type. SVG is
# deliberately absent: it can carry script and needs a sanitizer we do not ship.
_SIGNATURES: tuple[tuple[bytes, int, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", 0, "image/png", "image"),
    (b"\xff\xd8\xff", 0, "image/jpeg", "image"),
    (b"GIF87a", 0, "image/gif", "image"),
    (b"GIF89a", 0, "image/gif", "image"),
    (b"RIFF", 0, "", ""),  # disambiguated below (WEBP / WAVE)
    (b"ftyp", 4, "video/mp4", "video"),
    (b"ID3", 0, "audio/mpeg", "audio"),
    (b"%PDF-", 0, "application/pdf", "data"),
)


class UploadRejected(ValueError):
    pass


def sniff_media(data: bytes) -> tuple[str, str]:
    for signature, offset, mime, media in _SIGNATURES:
        if data[offset:offset + len(signature)] != signature:
            continue
        if signature == b"RIFF":
            kind = data[8:12]
            if kind == b"WEBP":
                return "image/webp", "image"
            if kind == b"WAVE":
                return "audio/wav", "audio"
            continue
        return mime, media
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadRejected("unsupported binary format") from exc
    if data.lstrip()[:1] in (b"<",):
        raise UploadRejected("markup uploads (HTML/SVG/XML) are not accepted")
    return "text/plain", "text"


def upload_media(
    *,
    tenant_id: str,
    project_id: str,
    actor: str,
    artifact_key: str,
    data: bytes,
    adapter: StorageAdapter,
    v2: Optional[Mapping[str, Any]] = None,
) -> ArtifactMetadataV2:
    require_project_workspace(project_id)
    if not data:
        raise UploadRejected("empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
    mime, media = sniff_media(data)
    stored = adapter.put_bytes(tenant_id=tenant_id, project_id=project_id, data=data)
    register_storage_object(tenant_id=tenant_id, project_id=project_id, stored=stored, mime_type=mime)
    artifact_type = "media_asset" if media in {"image", "video", "audio"} else "knowledge_capsule"
    meta = {**dict(v2 or {}), "mime_type": mime, "media_type": media, "provenance_ref": f"upload:{actor}"}
    return create_project_artifact(
        tenant_id=tenant_id, project_id=project_id, actor=actor, artifact_key=artifact_key, artifact_type=artifact_type,
        adapter=adapter, content_hash=stored.content_hash, storage_uri=stored.storage_uri, subtype="upload", v2=meta,
    )


def ingest_video_run(*, tenant_id: str, project_id: str, actor: str, output_dir: Path, adapter: StorageAdapter, campaign_id: Optional[str] = None) -> dict[str, Any]:
    """Register a finished FreeVideoForge run as project artifacts.

    The master video is the root; thumbnail, captions and QC depend on it, and
    the script/storyboard are its upstream sources. Every file is copied into
    content-addressed storage and its hash re-verified on read.
    """
    require_project_workspace(project_id)
    run = read_freevideoforge_output(Path(output_dir))
    stored: dict[str, Any] = {}
    for name, info in run["files"].items():
        data = Path(info["path"]).read_bytes()
        obj = adapter.put_bytes(tenant_id=tenant_id, project_id=project_id, data=data)
        if obj.content_hash != info["sha256"]:
            raise RuntimeError(f"{name} changed while being ingested")
        register_storage_object(tenant_id=tenant_id, project_id=project_id, stored=obj, mime_type=info["mime_type"])
        stored[name] = obj
    prefix = f"video-{run['run_id']}"
    base = {"campaign_id": campaign_id, "provenance_ref": f"freevideoforge:{run['run_id']}"}

    def make(name: str, key: str, artifact_type: str, subtype: str, extra: Mapping[str, Any], depends: tuple[str, ...] = ()) -> ArtifactMetadataV2:
        obj = stored[name]
        return create_project_artifact(
            tenant_id=tenant_id, project_id=project_id, actor=actor, artifact_key=f"{prefix}-{key}", artifact_type=artifact_type,
            adapter=adapter, content_hash=obj.content_hash, storage_uri=obj.storage_uri, subtype=subtype,
            v2={**base, "mime_type": run["files"][name]["mime_type"], **extra}, depends_on=depends,
        )

    script = make("script.json", "script", "copy_variant", "video_script", {"media_type": "data"})
    storyboard = make("storyboard.json", "storyboard", "asset_prompt_set", "storyboard", {"media_type": "data"}, (script.artifact_id,))
    master = make(
        "final.mp4", "master", "media_asset", "video_master",
        {"media_type": "video", "duration_seconds": run["duration_seconds"], "dimensions": run["aspect"]},
        (script.artifact_id, storyboard.artifact_id),
    )
    thumb = make("thumbnail.jpg", "thumbnail", "media_asset", "thumbnail",
                 {"media_type": "image", "master_artifact_id": master.artifact_id, "variant_of": master.artifact_id}, (master.artifact_id,))
    captions = make("captions.srt", "captions", "copy_variant", "captions", {"media_type": "text", "master_artifact_id": master.artifact_id}, (master.artifact_id,))
    qc = make("quality-report.json", "qc", "qa_report", "video_qc", {"media_type": "data"}, (master.artifact_id,))
    with transaction(write=True) as db:
        _append_event(db, tenant_id=tenant_id, project_id=project_id, event_type=ActivityType.PREVIEW_READY, actor=actor,
                      subject_ref=master.version_ref, payload={"freevideoforge_run": run["run_id"], "qc": run["qc"]})
        if run["qc"]["status"] == "FAIL":
            _append_event(db, tenant_id=tenant_id, project_id=project_id, event_type=ActivityType.QA_BLOCKED, actor=actor,
                          subject_ref=master.version_ref, payload={"failed_checks": run["qc"]["failed_checks"]})
    return {
        "run_id": run["run_id"],
        "artifacts": {item.artifact_key: item.artifact_id for item in (script, storyboard, master, thumb, captions, qc)},
        "qc": run["qc"],
        "reproducibility": run["reproducibility"].model_dump(mode="json"),
    }


def rights_expiration_radar(project_id: str, *, within_days: int = 30, now: Optional[datetime] = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    horizon = moment + timedelta(days=within_days)
    expiring, expired = [], []
    for record in list_asset_rights(project_id):
        if record.status != "active" or not record.expires_at:
            continue
        expires = datetime.fromisoformat(record.expires_at)
        expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        row = {"rights_id": record.rights_id, "artifact_id": record.artifact_id, "expires_at": record.expires_at, "license": record.license}
        if expires <= moment:
            expired.append(row)
        elif expires <= horizon:
            expiring.append(row)
    with transaction() as db:
        media = db.execute(
            f"SELECT artifact_id, metadata FROM {table('agency_artifacts')} WHERE project_id = ? AND artifact_type = 'media_asset'",
            (project_id,),
        ).fetchall()
    covered = {record.artifact_id for record in list_asset_rights(project_id)}
    unlicensed = sorted(normalize_record(row)["artifact_id"] for row in media if normalize_record(row)["artifact_id"] not in covered)
    return {"project_id": project_id, "within_days": within_days, "expired": expired, "expiring": expiring, "media_without_rights": unlicensed}


def collect_drift_subjects(project_id: str, adapter: StorageAdapter, *, max_text_bytes: int = 200_000) -> list:
    """Assemble brand-drift inputs from the project's canonical records."""
    from services.langgraph.agency.project_os.brand_drift import DriftSubject
    from services.langgraph.persistence.agency_kernel import _row_to_record
    from services.langgraph.persistence.project_ops import get_content_atom, list_content_items
    from services.langgraph.persistence.projects import rights_status

    unverified_by_artifact: dict[str, tuple[str, ...]] = {}
    for item in list_content_items(project_id):
        if not item.artifact_id or not item.atom_id:
            continue
        atom = get_content_atom(item.atom_id)
        if atom is None:
            continue
        bad = tuple(claim.claim_id for claim in atom.claims if claim.claim_id in item.claim_refs and claim.verification != "VERIFIED")
        if bad:
            unverified_by_artifact[item.artifact_id] = bad
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('agency_artifacts')} WHERE project_id = ? ORDER BY artifact_id", (project_id,)).fetchall()
    subjects = []
    for row in rows:
        record = _row_to_record(row, "agency_artifacts")
        v2 = (record.get("metadata") or {}).get("v2") or {}
        text = None
        uri = v2.get("storage_uri")
        if uri and v2.get("media_type") in {None, "text", "data"}:
            try:
                data = adapter.get_bytes(uri)
                if len(data) <= max_text_bytes:
                    text = data.decode("utf-8")
            except Exception:
                text = None
        rights = rights_status(record["artifact_id"]) if v2.get("media_type") in {"image", "video", "audio"} or v2.get("rights_ref") else None
        subjects.append(DriftSubject(
            artifact_id=record["artifact_id"], status=record["status"], text=text, content_hash=record.get("content_hash"),
            variant_of=v2.get("variant_of"), prompt_refs=tuple(v2.get("prompt_refs") or ()), rights=rights,
            unverified_claims=unverified_by_artifact.get(record["artifact_id"], ()),
        ))
    return subjects
