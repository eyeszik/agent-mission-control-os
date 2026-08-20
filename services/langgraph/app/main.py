import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.langgraph.api.routes import agency, approvals, events


app = FastAPI(
    title="Agent Mission Control API",
    version="0.1.0",
    description="Local-first LangGraph executor and workflow manager",
)

_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_allowed_origins = os.environ.get("AMC_CORS_ALLOWED_ORIGINS", _default_origins).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only implemented product routes are exposed. The legacy generic /runs scaffold
# is intentionally not mounted because it never executed the real workflow.
app.include_router(events.router, prefix="/runs", tags=["Events"])
app.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
app.include_router(agency.router, prefix="/agency", tags=["Agency Pipeline"])


@app.get("/health")
def health_check():
    auth_mode = os.environ.get("AMC_AUTH_MODE", "disabled").strip().lower() or "disabled"
    return {
        "status": "ok",
        "langgraph": "active",
        "version": "0.1.0",
        "auth_mode": auth_mode,
        "production_ready": False,
    }
