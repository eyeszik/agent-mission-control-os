"""Compiled Agency API (``/compiled-agency/v1``): planning only, fail-closed.

Every endpoint requires an authenticated principal and ``/plan`` also requires
project authorization. Planning is a pure function — no database write, no
model call, no provider call.

Authority inputs are never taken from the client. Approvals, authority grants
and provider status in a request body are discarded and replaced with the
server's view: there is no persisted approval bound to compiled node ids yet
and no live publication/paid-media adapter, so external actions always plan
as ``PROVIDER_UNAVAILABLE`` + ``AUTHORITY_UNRESOLVED`` here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from services.langgraph.agency.compiled.backchain import BackchainCycleError
from services.langgraph.agency.compiled.evidence import rule_ledger
from services.langgraph.agency.compiled.ontology import EXCEPTION_CATALOG, LIFECYCLE_STAGES, MASTER_BUILDER_OVERLAYS
from services.langgraph.agency.compiled.planner import COMPILED_AGENCY_VERSION, CompiledAgencyRequest, compile_agency_plan
from services.langgraph.agency.compiled.role_sources import LedgerIntegrityError, RoleSourceIndex, load_disposition_ledger
from services.langgraph.agency.compiled.twin import run_digital_twin
from services.langgraph.agency.compiled.validation import VALIDATION_PROFILES
from services.langgraph.app.config import load_runtime_config
from services.langgraph.app.runtime_support import role_os_registry
from services.langgraph.security.auth import Principal, authorize_project, get_principal

router = APIRouter()


def _ledger() -> dict[str, Any]:
    try:
        return load_disposition_ledger()
    except (LedgerIntegrityError, OSError) as exc:
        raise HTTPException(status_code=503, detail="HALT_SOURCE_INTEGRITY: source disposition ledger failed verification") from exc


def _server_provider_status() -> dict[str, str]:
    """No live adapter exists for any external action; report why, never VERIFIED."""
    config = load_runtime_config()
    return {
        "publish": f"UNAVAILABLE:publication_mode={config.publication.mode}",
        "media_spend": f"UNAVAILABLE:paid_media_mode={config.paid_media.mode}",
    }


@router.get("/v1/profile")
def profile(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    ledger = _ledger()
    registry = role_os_registry()
    return {
        "version": COMPILED_AGENCY_VERSION,
        "registry_hash": registry.registry_hash,
        "roles": len(registry.roles),
        "source_disposition": {
            "source_archive_sha256": ledger["source_archive_sha256"],
            "source_roles_sha256": ledger["source_roles_sha256"],
            "verified_source_file_count": ledger["verified_source_file_count"],
            "disposition_count": ledger["disposition_count"],
            "counts": ledger["counts"],
            "ledger_hash": ledger["ledger_hash"],
            "jit_indexed_roles": len(RoleSourceIndex.from_ledger(ledger)),
        },
        "lifecycle_stages": [s.stage_id + "_" + s.name for s in LIFECYCLE_STAGES],
        "overlays": [o.overlay_id + "_" + o.name for o in MASTER_BUILDER_OVERLAYS],
        "validation_profiles": [p.profile_id for p in VALIDATION_PROFILES],
        "exception_kinds": len(EXCEPTION_CATALOG),
        "provider_status": _server_provider_status(),
    }


@router.get("/v1/rules")
def rules(as_of: str, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    if len(as_of) < 10:
        raise HTTPException(status_code=422, detail="as_of must be an ISO-8601 date")
    return rule_ledger(as_of)


@router.post("/v1/plan")
def plan(req: CompiledAgencyRequest, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    authorize_project(principal, req.project_id)
    discarded = [k for k in ("approvals", "grants", "provider_status") if getattr(req, k)]
    sanitized = req.model_copy(update={"approvals": (), "grants": (), "provider_status": {}})
    try:
        compiled = compile_agency_plan(sanitized, registry=role_os_registry())
    except (BackchainCycleError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "summary": compiled.summary(),
        "authority_inputs": {
            "source": "SERVER_ONLY",
            "discarded_client_fields": discarded,
            "provider_status": _server_provider_status(),
        },
        "plan": compiled.model_dump(mode="json"),
    }


@router.get("/v1/twin")
def twin(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    results = run_digital_twin(role_os_registry())
    return {
        "status": "PASS" if all(r.status == "PASS" for r in results) else "FAIL",
        "scenarios": [r.model_dump(mode="json") for r in results],
    }
