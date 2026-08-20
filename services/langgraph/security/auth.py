import os
from dataclasses import dataclass
from typing import FrozenSet

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class Principal:
    """Server-derived identity used for authorization decisions."""

    user_id: str
    tenant_id: str
    role: str
    allowed_project_ids: FrozenSet[str]

    def can_access_project(self, project_id: str) -> bool:
        return "*" in self.allowed_project_ids or project_id in self.allowed_project_ids


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Authentication is not fully configured: missing {name}",
        )
    return value


def get_principal(request: Request) -> Principal:
    """
    Resolve the authoritative principal from server configuration.

    Only a loopback-only local mode is implemented in this repository today.
    It deliberately ignores client-supplied tenant/user/reviewer values. Any
    non-local deployment must integrate a verified authentication provider
    before exposing these routes externally.
    """

    mode = os.environ.get("AMC_AUTH_MODE", "disabled").strip().lower()
    if mode != "local":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authentication provider is not configured. Set AMC_AUTH_MODE=local "
                "only for loopback development, or integrate a production auth provider."
            ),
        )

    host = request.client.host if request.client else ""
    allowed_hosts = {"127.0.0.1", "::1", "localhost", "testclient"}
    if host not in allowed_hosts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Local authentication mode accepts loopback clients only",
        )

    projects = frozenset(
        p.strip()
        for p in _required_env("AMC_LOCAL_PROJECT_IDS").split(",")
        if p.strip()
    )
    if not projects:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not fully configured: AMC_LOCAL_PROJECT_IDS is empty",
        )

    return Principal(
        user_id=_required_env("AMC_LOCAL_USER_ID"),
        tenant_id=_required_env("AMC_LOCAL_TENANT_ID"),
        role=os.environ.get("AMC_LOCAL_ROLE", "operator").strip() or "operator",
        allowed_project_ids=projects,
    )


def authorize_project(principal: Principal, project_id: str) -> None:
    if not principal.can_access_project(project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project is outside the authenticated principal scope",
        )


def authorize_resource(principal: Principal, tenant_id: str, project_id: str) -> None:
    if tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resource belongs to a different tenant",
        )
    authorize_project(principal, project_id)
