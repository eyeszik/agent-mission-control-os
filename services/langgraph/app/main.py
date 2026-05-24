from fastapi import FastAPI
from services.langgraph.api.routes import runs, events, approvals

app = FastAPI(
    title="Agent Mission Control API",
    version="0.1.0",
    description="Local LangGraph Executor and Workflow Manager"
)

app.include_router(runs.router, prefix="/runs", tags=["Runs"])
app.include_router(events.router, prefix="/runs", tags=["Events"])
app.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])

@app.get("/health")
def health_check():
    return {"status": "ok", "langgraph": "scaffolded", "version": "0.1.0"}
