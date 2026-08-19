import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.langgraph.api.routes import runs, events, approvals, agency

app = FastAPI(
    title="Agent Mission Control API",
    version="0.1.0",
    description="Local LangGraph Executor and Workflow Manager"
)

# Without this, no browser-based frontend (the Next.js app included) can call
# this API at all — the browser blocks the cross-origin request at the
# preflight before it ever reaches a route. Configurable via env for
# non-local deployments; defaults cover the Next.js dev server.
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_allowed_origins = os.environ.get("AMC_CORS_ALLOWED_ORIGINS", _default_origins).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router, prefix="/runs", tags=["Runs"])
app.include_router(events.router, prefix="/runs", tags=["Events"])
app.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
app.include_router(agency.router, prefix="/agency", tags=["Agency Pipeline"])

@app.get("/health")
def health_check():
    return {"status": "ok", "langgraph": "scaffolded", "version": "0.1.0"}
