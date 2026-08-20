#!/usr/bin/env python3
"""Fail CI when mechanically verifiable repository invariants drift."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "packages/shared/openapi/agent-mission-control.openapi.yaml"

REQUIRED_ENV_VARS = {
    "NEXT_PUBLIC_API_BASE_URL",
    "AMC_DB_PATH",
    "AMC_CORS_ALLOWED_ORIGINS",
    "AMC_AUTH_MODE",
    "AMC_LOCAL_USER_ID",
    "AMC_LOCAL_TENANT_ID",
    "AMC_LOCAL_PROJECT_IDS",
    "AMC_LOCAL_ROLE",
    "OPENAI_API_KEY",
    "AMC_OPENAI_MODEL",
}


def backend_stages() -> list[str]:
    path = ROOT / "services/langgraph/graph/agency/nodes.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "AGENCY_PIPELINE_STAGES":
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        raise SystemExit("AGENCY_PIPELINE_STAGES must be a literal list[str]")
                    return value
    raise SystemExit("Backend AGENCY_PIPELINE_STAGES not found")


def shared_stages() -> list[str]:
    text = (ROOT / "packages/shared/src/schemas/agency.ts").read_text(encoding="utf-8")
    match = re.search(r"export const AGENCY_PIPELINE_STAGES\s*=\s*\[(.*?)\]\s*as const", text, re.S)
    if not match:
        raise SystemExit("Shared AGENCY_PIPELINE_STAGES not found")
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def openapi_stages() -> list[str]:
    text = OPENAPI.read_text(encoding="utf-8")
    match = re.search(r"enum:\s*\[(brief_intake[^\]]*)\]", text)
    if not match:
        raise SystemExit("OpenAPI agency pipeline-stage enum not found")
    return [item.strip() for item in match.group(1).split(",")]


def env_keys() -> set[str]:
    keys: set[str] = set()
    for raw in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def main() -> None:
    backend = backend_stages()
    shared = shared_stages()
    documented = openapi_stages()
    if backend != shared or backend != documented:
        raise SystemExit(
            f"Pipeline contract drift: backend={backend!r} shared={shared!r} openapi={documented!r}"
        )

    missing_env = sorted(REQUIRED_ENV_VARS - env_keys())
    if missing_env:
        raise SystemExit(f".env.example missing runtime variables: {missing_env}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    stale_claims = ["Implementation code: **not included**", "no repository was provided"]
    for stale in stale_claims:
        if stale.lower() in readme.lower():
            raise SystemExit(f"README contains stale implementation claim: {stale}")

    command_panel = (ROOT / "apps/web/components/mission-control/CommandInputPanel.tsx").read_text(encoding="utf-8")
    if "GENERAL" in command_panel or "createRun(" in command_panel:
        raise SystemExit("Mock GENERAL execution surface must not be exposed")

    client = (ROOT / "apps/web/lib/api/client.ts").read_text(encoding="utf-8")
    if "schema.parse(data)" not in client:
        raise SystemExit("Core frontend API boundary no longer performs runtime schema parsing")

    event_schema = (ROOT / "packages/shared/src/schemas/events.ts").read_text(encoding="utf-8")
    for required in ["sequence", "schema_version", "tenant_id", "project_id", "persisted_at"]:
        if required not in event_schema:
            raise SystemExit(f"Run-event contract missing required field: {required}")

    main_py = (ROOT / "services/langgraph/app/main.py").read_text(encoding="utf-8")
    if "include_router(runs.router" in main_py or "from services.langgraph.api.routes import runs" in main_py:
        raise SystemExit("Legacy mock generic /runs router must not be mounted")
    if '"langgraph": "scaffolded"' in main_py:
        raise SystemExit("Health endpoint still claims LangGraph is scaffolded")

    openapi = OPENAPI.read_text(encoding="utf-8")
    if re.search(r"^  /runs:\s*$", openapi, re.M):
        raise SystemExit("OpenAPI must not advertise the removed generic /runs scaffold")
    for required in [
        "/agency/runs:",
        "/agency/runs/{run_id}/resume:",
        "/approvals/{approval_id}/decide:",
        "/runs/{run_id}/events:",
        "FALLBACK_DEGRADED",
        "NOT_MEASURED",
        "delivering",
        "rejected",
        "Last-Event-ID",
    ]:
        if required not in openapi:
            raise SystemExit(f"OpenAPI missing material runtime contract token: {required}")

    agency_route = (ROOT / "services/langgraph/api/routes/agency.py").read_text(encoding="utf-8")
    approvals_route = (ROOT / "services/langgraph/api/routes/approvals.py").read_text(encoding="utf-8")
    for route_path, text in [("agency.py", agency_route), ("approvals.py", approvals_route)]:
        if "Depends(get_principal)" not in text:
            raise SystemExit(f"{route_path} lost server-derived authentication dependency")

    idempotency = (ROOT / "services/langgraph/persistence/idempotency.py").read_text(encoding="utf-8")
    if "SELECT 1 FROM idempotency_keys" in idempotency or "INSERT OR REPLACE INTO idempotency_keys" in idempotency:
        raise SystemExit("Legacy check-then-record idempotency path remains executable")

    print("Repository invariants verified")


if __name__ == "__main__":
    main()
