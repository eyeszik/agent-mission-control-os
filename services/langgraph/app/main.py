from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.langgraph.api.routes import agency, analytics, approvals, events, operations
from services.langgraph.app.config import assert_runtime_configuration, production_config_errors, runtime_environment
from services.langgraph.persistence.checkpoints import close_checkpointer
from services.langgraph.persistence.database import database_backend


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_runtime_configuration()
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

app.include_router(events.router, prefix="/runs", tags=["Events"])
app.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
app.include_router(agency.router, prefix="/agency", tags=["Agency Pipeline"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(operations.router, prefix="/operations", tags=["Operations"])


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
        "analytics_source": "amc_first_party",
        "publication_mode": os.environ.get("AMC_PUBLICATION_MODE", "disabled").strip().lower(),
        "paid_media_mode": os.environ.get("AMC_PAID_MEDIA_MODE", "disabled").strip().lower(),
        "production_ready": environment == "production" and not errors,
    }
