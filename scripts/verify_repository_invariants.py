#!/usr/bin/env python3
"""Fail CI when mechanically verifiable repository invariants drift."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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
    if backend != shared:
        raise SystemExit(f"Pipeline contract drift: backend={backend!r} shared={shared!r}")

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

    print("Repository invariants verified")


if __name__ == "__main__":
    main()
