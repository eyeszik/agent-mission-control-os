#!/usr/bin/env python3
"""Verify the deterministic critical-file integrity manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest.json"


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def main() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "amc-integrity/v2":
        raise SystemExit("manifest.json must use amc-integrity/v2")
    if payload.get("scope") != "critical_runtime_release_and_production_contracts":
        raise SystemExit("manifest.json has unexpected integrity scope")

    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise SystemExit("manifest.json must contain a non-empty files list")

    seen: set[str] = set()
    for entry in files:
        path_value = entry.get("path") if isinstance(entry, dict) else None
        expected = entry.get("git_blob_sha") if isinstance(entry, dict) else None
        if not isinstance(path_value, str) or not isinstance(expected, str):
            raise SystemExit("manifest entry must contain path and git_blob_sha strings")
        if path_value in seen:
            raise SystemExit(f"duplicate manifest path: {path_value}")
        seen.add(path_value)
        path = ROOT / path_value
        if not path.is_file():
            raise SystemExit(f"manifest path missing: {path_value}")
        actual = git_blob_sha(path.read_bytes())
        if actual != expected:
            raise SystemExit(
                f"manifest drift for {path_value}: expected={expected} actual={actual}"
            )

    required = {
        ".github/workflows/ci.yml",
        ".env.example",
        "README.md",
        "docs/production-activation.md",
        "package.json",
        "pnpm-lock.yaml",
        "apps/web/package.json",
        "apps/web/playwright.config.ts",
        "apps/web/e2e/agency-smoke.spec.ts",
        "services/langgraph/agency/exporter.py",
        "services/langgraph/agency/prompt_compiler.py",
        "services/langgraph/agency/guidance/__init__.py",
        "services/langgraph/agency/guidance/models.py",
        "services/langgraph/agency/guidance/registry.py",
        "services/langgraph/agency/guidance/router.py",
        "services/langgraph/agency/guidance/packs/branding.yaml",
        "services/langgraph/agency/guidance/packs/studio_identity_v4.yaml",
        "scripts/verify_guidance_registry.py",
        "apps/web/lib/api/client.ts",
        "apps/web/lib/auth/session.ts",
        "apps/web/lib/auth/supabase.ts",
        "apps/web/app/login/page.tsx",
        "apps/web/app/mission-control/page.tsx",
        "apps/web/vercel.json",
        "packages/shared/openapi/agent-mission-control.openapi.yaml",
        "packages/shared/src/schemas/agency.ts",
        "packages/shared/src/schemas/approvals.ts",
        "packages/shared/src/schemas/events.ts",
        "services/langgraph/api/routes/agency.py",
        "services/langgraph/api/routes/analytics.py",
        "services/langgraph/api/routes/approvals.py",
        "services/langgraph/api/routes/events.py",
        "services/langgraph/api/routes/operations.py",
        "services/langgraph/app/config.py",
        "services/langgraph/app/main.py",
        "services/langgraph/integrations/publication.py",
        "services/langgraph/integrations/paid_media.py",
        "services/langgraph/persistence/analytics.py",
        "services/langgraph/persistence/checkpoints.py",
        "services/langgraph/persistence/database.py",
        "services/langgraph/persistence/idempotency.py",
        "services/langgraph/persistence/memberships.py",
        "services/langgraph/persistence/operations.py",
        "services/langgraph/persistence/sqlite_db.py",
        "services/langgraph/security/auth.py",
        "services/langgraph/pyproject.toml",
        "services/langgraph/vercel.json",
        "services/langgraph/tests/test_lifecycle_analytics.py",
        "services/langgraph/tests/test_production_foundation.py",
        "supabase/migrations/20260820_amc_production_foundation_v1.sql",
        "supabase/migrations/20260820_amc_production_foundation_v2_fk_indexes.sql",
        "scripts/verify_repository_invariants.py",
        "scripts/verify_production_readiness.py",
        "scripts/verify_manifest.py",
    }
    missing = sorted(required - seen)
    if missing:
        raise SystemExit(f"manifest missing critical files: {missing}")

    print(f"Integrity manifest verified ({len(files)} critical files)")


if __name__ == "__main__":
    main()
