#!/usr/bin/env python3
"""Fail CI when mechanically verifiable repository invariants drift."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "packages/shared/openapi/agent-mission-control.openapi.yaml"

REQUIRED_ENV_VARS = {
    "NEXT_PUBLIC_API_BASE_URL",
    "AMC_DB_PATH",
    "AMC_EXPORT_ROOT",
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


_SCRIPT_REFERENCE = re.compile(r"\bpython3?\s+((?:scripts/)?[\w./-]+\.py)\b")
_PNPM_REFERENCE = re.compile(r"pnpm --filter (@amc/[\w-]+) (?:run )?([\w:-]+)")
_PACKAGE_DIRS = {"@amc/web": "apps/web", "@amc/shared": "packages/shared"}
_PNPM_BUILTINS = {"exec", "install", "add", "why", "list"}


def missing_validator_references(root: Path = ROOT) -> list[str]:
    """Every validator CI or `make` invokes must exist.

    An active gate that points at a missing script is repository drift, and it
    is critical: the gate would either crash or -- worse -- be quietly removed.
    It is reported, never auto-created.
    """
    problems: list[str] = []
    for source in (".github/workflows/ci.yml", "Makefile"):
        path = root / source
        if not path.is_file():
            problems.append(f"{source}: missing (gate definitions cannot be verified)")
            continue
        text = path.read_text(encoding="utf-8")
        for script in sorted(set(_SCRIPT_REFERENCE.findall(text))):
            if not (root / script).is_file():
                problems.append(f"{source}: references missing validator/script {script}")
        for package, script in sorted(set(_PNPM_REFERENCE.findall(text))):
            if script in _PNPM_BUILTINS:
                continue
            manifest = root / _PACKAGE_DIRS.get(package, "") / "package.json"
            scripts = json.loads(manifest.read_text()).get("scripts", {}) if manifest.is_file() else {}
            if script not in scripts:
                problems.append(f"{source}: `pnpm --filter {package} {script}` has no such package script")
    return problems


def main() -> None:
    missing = missing_validator_references()
    if missing:
        raise SystemExit("Active gates reference missing validators:\n" + "\n".join(missing))
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
    if "Browser E2E release gate" not in readme:
        raise SystemExit("README must document the browser E2E release gate")

    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if root_package.get("engines", {}).get("node") != ">=20.9.0":
        raise SystemExit("Root Node.js engine must match the Next.js 16 minimum: >=20.9.0")
    if "lint" in root_package.get("scripts", {}):
        raise SystemExit("Root package still advertises an unimplemented recursive lint command")

    web_package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    if web_package.get("dependencies", {}).get("next") != "16.3.3":
        raise SystemExit("Web package must remain pinned to audited Next.js 16.3.3")
    if web_package.get("devDependencies", {}).get("@playwright/test") != "1.61.0":
        raise SystemExit("Browser gate must pin @playwright/test to 1.61.0")
    if web_package.get("scripts", {}).get("test") != "vitest run tests":
        raise SystemExit("Web unit tests must be scoped to tests/ so Vitest cannot execute Playwright specs")
    if web_package.get("scripts", {}).get("test:e2e") != "playwright test":
        raise SystemExit("Web package must expose the deterministic test:e2e script")
    if web_package.get("scripts", {}).get("lint") == "next lint":
        raise SystemExit("Next.js 16 removed `next lint`; stale script detected")

    lockfile = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    for required in [
        "specifier: 16.3.3",
        "sharp@0.35.4",
        "postcss@8.5.28",
        "'@playwright/test@1.61.0'",
        "playwright-core@1.61.0",
    ]:
        if required not in lockfile:
            raise SystemExit(f"Audited frontend lockfile token missing: {required}")

    playwright_config = ROOT / "apps/web/playwright.config.ts"
    smoke_spec = ROOT / "apps/web/e2e/agency-smoke.spec.ts"
    if not playwright_config.is_file() or not smoke_spec.is_file():
        raise SystemExit("Browser E2E config/spec must remain committed")
    playwright_text = playwright_config.read_text(encoding="utf-8")
    if "retries: 0" not in playwright_text or "workers: 1" not in playwright_text:
        raise SystemExit("Stateful browser release gate must remain single-attempt and single-worker")

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in [
        "Browser E2E (local degraded HITL)",
        "playwright install --with-deps chromium",
        "pnpm --filter @amc/shared build",
        "pnpm --filter @amc/web test:e2e",
        "AMC_AUTH_MODE: local",
        "contents: read",
    ]:
        if required not in ci:
            raise SystemExit(f"CI browser release gate token missing: {required}")

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

    for temporary_workflow in [
        ".github/workflows/dependency-remediation.yml",
        ".github/workflows/e2e-bootstrap.yml",
    ]:
        if (ROOT / temporary_workflow).exists():
            raise SystemExit(f"Temporary write-enabled workflow must be removed: {temporary_workflow}")

    # N1-N4 ontology layer: the release guards are the reason the layer exists,
    # so their absence is a contract regression rather than a refactor.
    lifecycle = (ROOT / "services/langgraph/agency/kernel/lifecycle.py").read_text(encoding="utf-8")
    for required in ["FALLBACK_DEGRADED", "RELEASE_GUARDS", "CLIENT_VISIBLE_TRANSITIONS"]:
        if required not in lifecycle:
            raise SystemExit(f"Agency lifecycle contract missing release guard token: {required}")

    roles = (ROOT / "services/langgraph/agency/kernel/roles.py").read_text(encoding="utf-8")
    for required in ["requires_human_approval", "external_side_effect"]:
        if required not in roles:
            raise SystemExit(f"Role contract missing authority field: {required}")

    registry = (ROOT / "services/langgraph/agency/kernel/registry.py").read_text(encoding="utf-8")
    if "MERGE_MATRIX" not in registry:
        raise SystemExit("Artifact registry must resolve merges through a declared matrix")

    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required_gate in ["verify_auth_bindings.py", "verify_ontology_parity.py"]:
        if required_gate not in ci_workflow:
            raise SystemExit(f"CI must run the {required_gate} gate")

    print("Repository invariants verified")


if __name__ == "__main__":
    main()
