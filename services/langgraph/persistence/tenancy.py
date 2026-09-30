"""Tenant/project registry rows that tenant-scoped tables reference.

On PostgreSQL every tenant-scoped table has a foreign key to ``amc.tenants`` and
``amc.projects``. Authorization already happened (the caller's membership
allows the project), so the first write for a project records it here, bound to
the authenticated tenant. A project id that already belongs to another tenant is
refused: a project can never be re-bound or shared across tenants by writing
into it.
"""

from __future__ import annotations

from typing import Any

from services.langgraph.persistence.database import table


class ProjectOwnershipError(PermissionError):
    """The project id is already registered to a different tenant."""


def ensure_tenant_project(db: Any, tenant_id: str, project_id: str) -> None:
    """Register (tenant, project) if new; refuse a project owned by another tenant.

    Runs inside the caller's write transaction so the registry row and the
    tenant-scoped row it guards commit together.
    """
    if not tenant_id or not project_id:
        raise ValueError("tenant_id and project_id are required")
    db.execute(
        f"INSERT INTO {table('tenants')} (tenant_id, name) VALUES (?, ?) ON CONFLICT (tenant_id) DO NOTHING",
        (tenant_id, tenant_id),
    )
    db.execute(
        f"INSERT INTO {table('projects')} (project_id, tenant_id, name) VALUES (?, ?, ?) ON CONFLICT (project_id) DO NOTHING",
        (project_id, tenant_id, project_id),
    )
    row = db.execute(f"SELECT tenant_id FROM {table('projects')} WHERE project_id = ?", (project_id,)).fetchone()
    if row is None or row["tenant_id"] != tenant_id:
        raise ProjectOwnershipError("Project is registered to a different tenant")


__all__ = ["ProjectOwnershipError", "ensure_tenant_project"]
