"""Canonical AMC vocabularies for the Python backend.

Mirrors ``packages/constants`` in the TypeScript workspace. The stacks never
import each other; ``tests/test_core.py`` checks that both declare the same
values. Dependency-free on purpose, so any module (including ``app.config``)
can import it.
"""

from __future__ import annotations

# Environments with defined behaviour. Any other AMC_ENV value is treated as
# non-production, exactly as before.
ENV_LOCAL = "local"
ENV_PRODUCTION = "production"
AMC_ENVIRONMENTS: tuple[str, ...] = (ENV_LOCAL, ENV_PRODUCTION)

# AMC_AUTH_MODE. "disabled" refuses every authenticated request.
AUTH_MODE_DISABLED = "disabled"
AUTH_MODE_LOCAL = "local"
AUTH_MODE_SUPABASE = "supabase"
AMC_AUTH_MODES: tuple[str, ...] = (AUTH_MODE_DISABLED, AUTH_MODE_LOCAL, AUTH_MODE_SUPABASE)

# AMC_DATABASE_BACKEND.
DB_BACKEND_SQLITE = "sqlite"
DB_BACKEND_POSTGRES = "postgres"
AMC_DATABASE_BACKENDS: tuple[str, ...] = (DB_BACKEND_SQLITE, DB_BACKEND_POSTGRES)

# AMC_LOG_LEVEL, lowest to highest severity ("warning" is accepted as "warn").
AMC_LOG_LEVELS: tuple[str, ...] = ("debug", "info", "warn", "error")

# Default roles that may decide an approval (AMC_APPROVER_ROLES overrides).
AMC_APPROVER_ROLES: tuple[str, ...] = ("reviewer", "approver", "admin", "owner")

# Agency run lifecycle states (AgencyRunStatusSchema in @amc/shared).
AMC_AGENCY_RUN_STATES: tuple[str, ...] = ("running", "needs_approval", "delivering", "completed", "rejected", "failed")
TERMINAL_AGENCY_RUN_STATES: tuple[str, ...] = ("completed", "rejected", "failed")

__all__ = [
    "AMC_AGENCY_RUN_STATES",
    "AMC_APPROVER_ROLES",
    "AMC_AUTH_MODES",
    "AMC_DATABASE_BACKENDS",
    "AMC_ENVIRONMENTS",
    "AMC_LOG_LEVELS",
    "AUTH_MODE_DISABLED",
    "AUTH_MODE_LOCAL",
    "AUTH_MODE_SUPABASE",
    "DB_BACKEND_POSTGRES",
    "DB_BACKEND_SQLITE",
    "ENV_LOCAL",
    "ENV_PRODUCTION",
    "TERMINAL_AGENCY_RUN_STATES",
]
