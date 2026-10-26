from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.langgraph.core.errors import register_error_handlers
from services.langgraph.api.routes import (
    actions,
    agency_framework,
    agency_os,
    agency,
    analytics,
    approvals,
    compiled_agency,
    design,
    events,
    foundry,
    rendering,
    missions,
    operations,
    portfolio,
    project_ops,
    projects,
    runtime,
    ucpo,
    vnexus,
)
from services.langgraph.app.config import (
    assert_runtime_configuration,
    hmac_ingress_enabled,
    hmac_ingress_header_name,
    load_runtime_config,
    readiness_errors,
    runtime_environment,
)
from services.langgraph.security.hmac_ingress import HMACIngressConfig, HMACIngressMiddleware
from services.langgraph.persistence.checkpoints import close_checkpointer
from services.langgraph.persistence.database import database_backend, ping_database
from services.langgraph.persistence.tenancy import ProjectOwnershipError

API_VERSION = "0.2.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_runtime_configuration()
    if (os.environ.get("COUNCIL_RECOVER_ON_STARTUP") or "").strip().lower() in {"1", "true", "yes", "on"}:
        # Resubmit council missions whose worker stopped (expired lease); paused missions need nothing.
        from services.langgraph.agency.council.service import recover_stale

        recover_stale()
    yield
    close_checkpointer()


app = FastAPI(
    title="Agent Mission Control API",
    version=API_VERSION,
    description="LangGraph execution and workflow manager with local and production persistence modes",
    lifespan=lifespan,
)
register_error_handlers(app)

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # Echo a well-formed inbound X-Request-ID, otherwise mint one; every response carries it.
    inbound = request.headers.get("X-Request-ID") or ""
    request_id = inbound if _REQUEST_ID.match(inbound) else uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response



@app.exception_handler(ProjectOwnershipError)
async def _project_ownership_error(_request, _exc: ProjectOwnershipError):
    # A project id registered to another tenant must never be written into.
    return JSONResponse(status_code=403, content={"detail": "Project belongs to a different tenant"})


_startup_config = load_runtime_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_startup_config.cors.allowed_origins),
    allow_credentials=True,
    # Every method a route uses must be listed, or browsers fail the preflight
    # (test_ace12_ui_contract checks this against the route table).
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID", "X-AMC-Tenant", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

if hmac_ingress_enabled():
    app.add_middleware(
        HMACIngressMiddleware,
        config=HMACIngressConfig(
            header_name=hmac_ingress_header_name(),
            secret=os.environ["AMC_HMAC_SECRET"].encode("utf-8"),
            protected_paths=("/runtime/ingest",),
        ),
    )

app.include_router(events.router, prefix="/runs", tags=["Events"])
app.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
app.include_router(agency.router, prefix="/agency", tags=["Agency Pipeline"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(operations.router, prefix="/operations", tags=["Operations"])
app.include_router(runtime.router, prefix="/runtime", tags=["Runtime"])
app.include_router(design.router, prefix="/design", tags=["Design Mode"])
app.include_router(foundry.router, prefix="/foundry", tags=["Creative Foundry"])
app.include_router(rendering.router, prefix="/foundry", tags=["Governed Rendering"])
app.include_router(ucpo.router, prefix="/ucpo", tags=["Website Production Line"])
app.include_router(missions.router, prefix="/missions", tags=["Mission Council"])
app.include_router(vnexus.router, prefix="/vnexus", tags=["VNEXUS"])
app.include_router(actions.router, prefix="/actions", tags=["Governed Actions"])
app.include_router(agency_os.router, prefix="/agency-os", tags=["Agency OS"])
app.include_router(agency_framework.router, prefix="/agency-framework", tags=["Agency Operating Framework"])
app.include_router(compiled_agency.router, prefix="/compiled-agency", tags=["Compiled Agency"])
app.include_router(projects.router, prefix="/projects", tags=["Projects"])
app.include_router(project_ops.router, prefix="/projects", tags=["Project Operations"])
app.include_router(portfolio.router, tags=["Portfolio, Memory and Knowledge"])


@app.get("/health")
def health_check():
    """Pure liveness: the process is up and can answer HTTP requests.

    Deliberately does no configuration or dependency validation -- that is
    /ready's job. A load balancer should be able to trust this endpoint even
    while the service is misconfigured, so it doesn't kill an instance that
    could still be fixed by a config change without a restart.
    """
    return {"status": "ok", "service": "agent-mission-control-api"}


@app.get("/ready")
def readiness_check():
    """200 only when configuration and dependencies are actually usable.

    Errors are always human-readable, secret-free strings (see app/config.py)
    so this body is safe to return to any caller, including over a public
    load-balancer health check path.
    """
    config = load_runtime_config()
    errors = readiness_errors()

    try:
        backend = database_backend()
    except RuntimeError as exc:
        backend = None
        errors.append(str(exc))

    if backend is not None:
        try:
            if not ping_database():
                errors.append("database ping did not return the expected result")
        except Exception as exc:
            errors.append(f"database is unreachable ({exc.__class__.__name__})")

    body = {
        "ready": not errors,
        "environment": config.environment,
        "auth_mode": config.auth.mode,
        "database_backend": backend,
        "analytics_source": "amc_first_party",
        "publication_mode": config.publication.mode,
        "paid_media_mode": config.paid_media.mode,
        "hmac_ingress_enabled": hmac_ingress_enabled(),
        "errors": errors,
    }
    return JSONResponse(content=body, status_code=200 if not errors else 503)


@app.get("/version")
def version_info():
    return {
        "version": API_VERSION,
        "environment": runtime_environment(),
        "commit_sha": os.environ.get("AMC_BUILD_COMMIT_SHA") or os.environ.get("VERCEL_GIT_COMMIT_SHA") or None,
        "build_timestamp": os.environ.get("AMC_BUILD_TIMESTAMP") or None,
    }
