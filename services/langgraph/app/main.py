from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.langgraph.api.routes import agency, analytics, approvals, artifacts, events, operations
from services.langgraph.app.config import (
    artifact_backend,
    assert_runtime_configuration,
    execution_mode,
    production_config_errors,
    runtime_environment,
)
from services.langgraph.persistence.checkpoints import close_checkpointer
from services.langgraph.persistence.database import database_backend, pool_stats
from services.langgraph.app.observability import AMCTracingMiddleware, configure_logging


_worker_thread: threading.Thread | None = None


def _maybe_start_worker() -> None:
    """Optionally run the durable-execution poller inside the API process.

    Intended for single-node deployments and previews. Multi-node production
    deployments should run services.langgraph.runtime.worker as its own process
    instead (AMC_WORKER_INPROCESS defaults to disabled).
    """

    global _worker_thread
    enabled = (os.environ.get("AMC_WORKER_INPROCESS") or "0").strip().lower() in {
        "1", "true", "yes"
    }
    if not enabled or execution_mode() != "background":
        return

    def _loop() -> None:
        interval = float(os.environ.get("AMC_WORKER_POLL_INTERVAL", "2") or 2)
        from services.langgraph.runtime.worker import run_worker_loop

        run_worker_loop(poll_interval=interval)

    _worker_thread = threading.Thread(target=_loop, name="amc-runtime-worker", daemon=True)
    _worker_thread.start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    assert_runtime_configuration()
    _maybe_start_worker()
    yield
    close_checkpointer()


app = FastAPI(
    title="Agent Mission Control API",
    version="0.2.0",
    description="LangGraph execution and workflow manager with local and production persistence modes",
    lifespan=lifespan,
)

_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_allowed_origins = os.environ.get("AMC_CORS_ALLOWED_ORIGINS", _default_origins).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID", "X-AMC-Tenant"],
)

app.add_middleware(AMCTracingMiddleware)

app.include_router(events.router, prefix="/runs", tags=["Events"])
app.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
app.include_router(agency.router, prefix="/agency", tags=["Agency Pipeline"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(operations.router, prefix="/operations", tags=["Operations"])
app.include_router(artifacts.router, prefix="/agency/artifacts", tags=["Artifacts"])


@app.get("/health")
def health_check():
    errors = production_config_errors()
    environment = runtime_environment()
    return {
        "status": "ok",
        "langgraph": "active",
        "version": "0.2.0",
        "environment": environment,
        "auth_mode": os.environ.get("AMC_AUTH_MODE", "disabled").strip().lower() or "disabled",
        "database_backend": database_backend(),
        "execution_mode": execution_mode(),
        "artifact_backend": artifact_backend(),
        "deployed_revision": os.environ.get("AMC_DEPLOYED_REVISION", "").strip(),
        "pool": pool_stats(),
        "analytics_source": "amc_first_party",
        "publication_mode": os.environ.get("AMC_PUBLICATION_MODE", "disabled").strip().lower(),
        "paid_media_mode": os.environ.get("AMC_PAID_MEDIA_MODE", "disabled").strip().lower(),
        "production_ready": environment == "production" and not errors,
    }
