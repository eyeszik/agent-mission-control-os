#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require(path: str, token: str | None = None) -> None:
    target = ROOT / path
    if not target.is_file():
        raise SystemExit(f"missing production artifact: {path}")
    if token is not None and token not in target.read_text(encoding="utf-8"):
        raise SystemExit(f"production artifact {path} missing required token: {token}")


def main() -> None:
    require("supabase/migrations/20260820_amc_production_foundation_v1.sql", "amc.tenant_memberships")
    require("supabase/migrations/20260820_amc_production_foundation_v2_fk_indexes.sql", "idx_amc_runs_project_id")
    require("services/langgraph/vercel.json", "app/main.py")
    require("apps/web/vercel.json", "nextjs")
    require("services/langgraph/app/config.py", "AMC_AUTH_MODE must be supabase")
    require("services/langgraph/security/auth.py", "X-AMC-Tenant")
    require("services/langgraph/integrations/publication.py", "publication_disabled")
    require("services/langgraph/integrations/paid_media.py", "and False")
    require("services/langgraph/persistence/analytics.py", "emit_lifecycle_event")
    require("services/langgraph/api/routes/agency.py", "agency_run_created")
    require("services/langgraph/api/routes/agency.py", "agency_run_completed")
    require("services/langgraph/api/routes/approvals.py", "agency_approval_decided")
    require("services/langgraph/api/routes/operations.py", "publication_previewed")
    require("services/langgraph/api/routes/operations.py", "spend_authorization_requested")
    require("services/langgraph/tests/test_lifecycle_analytics.py", "agency_run_needs_approval")

    openapi = (ROOT / "packages/shared/openapi/agent-mission-control.openapi.yaml").read_text(encoding="utf-8")
    for token in [
        "/analytics/events:",
        "/operations/capabilities:",
        "/operations/publications/preview:",
        "/operations/spend/authorizations:",
        "BearerAuth:",
        "AnalyticsEventRequest:",
        "PublicationJob:",
        "SpendAuthorization:",
    ]:
        if token not in openapi:
            raise SystemExit(f"OpenAPI production contract missing token: {token}")

    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in [
        "AMC_ENV",
        "AMC_DATABASE_BACKEND",
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "AMC_PUBLICATION_MODE",
        "AMC_PAID_MEDIA_MODE",
    ]:
        if f"{key}=" not in env_text:
            raise SystemExit(f".env.example missing {key}")

    os.environ["AMC_ENV"] = "production"
    os.environ["AMC_AUTH_MODE"] = "supabase"
    os.environ["AMC_DATABASE_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"] = "postgresql://example.invalid/postgres"
    os.environ["SUPABASE_URL"] = "https://example.supabase.co"
    os.environ["SUPABASE_PUBLISHABLE_KEY"] = "test-publishable"
    os.environ["AMC_CORS_ALLOWED_ORIGINS"] = "https://mission.example.com"
    os.environ["AMC_PUBLICATION_MODE"] = "disabled"
    os.environ["AMC_PAID_MEDIA_MODE"] = "disabled"
    from services.langgraph.app.config import production_config_errors

    errors = production_config_errors()
    if errors:
        raise SystemExit(f"valid production fixture rejected: {errors}")

    os.environ["AMC_PAID_MEDIA_MODE"] = "live"
    if not production_config_errors():
        raise SystemExit("live paid media must fail production readiness until an adapter exists")
    os.environ["AMC_PAID_MEDIA_MODE"] = "disabled"
    os.environ["AMC_PUBLICATION_MODE"] = "live"
    if not production_config_errors():
        raise SystemExit("live publication must fail production readiness until an adapter exists")

    print("Production readiness invariants verified")


if __name__ == "__main__":
    main()
