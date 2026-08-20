from __future__ import annotations

import os
from dataclasses import dataclass
from typing import FrozenSet

import httpx
from fastapi import HTTPException, Request, status

from services.langgraph.persistence.memberships import list_active_memberships


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str
    allowed_project_ids: FrozenSet[str]

    def can_access_project(self, project_id: str) -> bool:
        return "*" in self.allowed_project_ids or project_id in self.allowed_project_ids


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Authentication is not fully configured: missing {name}")
    return value


def _local_principal(request: Request) -> Principal:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Local authentication mode accepts loopback clients only")
    projects = frozenset(p.strip() for p in _required_env("AMC_LOCAL_PROJECT_IDS").split(",") if p.strip())
    if not projects:
        raise HTTPException(status_code=503, detail="Authentication is not fully configured: AMC_LOCAL_PROJECT_IDS is empty")
    return Principal(
        user_id=_required_env("AMC_LOCAL_USER_ID"),
        tenant_id=_required_env("AMC_LOCAL_TENANT_ID"),
        role=os.environ.get("AMC_LOCAL_ROLE", "operator").strip() or "operator",
        allowed_project_ids=projects,
    )


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer access token required")
    return token.strip()


def _verify_supabase_user(token: str) -> str:
    base_url = _required_env("SUPABASE_URL").rstrip("/")
    publishable_key = _required_env("SUPABASE_PUBLISHABLE_KEY")
    timeout = float(os.environ.get("AMC_AUTH_TIMEOUT_SECONDS", "5"))
    try:
        response = httpx.get(
            f"{base_url}/auth/v1/user",
            headers={"apikey": publishable_key, "Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Authentication provider unavailable") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")
    payload = response.json()
    user_id = str(payload.get("id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user identity is missing")
    return user_id


def _supabase_principal(request: Request) -> Principal:
    user_id = _verify_supabase_user(_bearer_token(request))
    memberships = list_active_memberships(user_id)
    if not memberships:
        raise HTTPException(status_code=403, detail="Authenticated user has no active Agent Mission Control membership")

    requested_tenant = (request.headers.get("X-AMC-Tenant") or "").strip()
    if requested_tenant:
        membership = next((item for item in memberships if item["tenant_id"] == requested_tenant), None)
        if membership is None:
            raise HTTPException(status_code=403, detail="Requested tenant is outside authenticated membership scope")
    elif len(memberships) == 1:
        membership = memberships[0]
    else:
        raise HTTPException(status_code=400, detail="X-AMC-Tenant is required when the user belongs to multiple tenants")

    return Principal(
        user_id=user_id,
        tenant_id=membership["tenant_id"],
        role=membership["role"],
        allowed_project_ids=frozenset(membership.get("allowed_project_ids") or []),
    )


def get_principal(request: Request) -> Principal:
    mode = os.environ.get("AMC_AUTH_MODE", "disabled").strip().lower()
    if mode == "local":
        return _local_principal(request)
    if mode == "supabase":
        return _supabase_principal(request)
    raise HTTPException(status_code=503, detail="Authentication provider is not configured")


def authorize_project(principal: Principal, project_id: str) -> None:
    if not principal.can_access_project(project_id):
        raise HTTPException(status_code=403, detail="Project is outside the authenticated principal scope")


def authorize_resource(principal: Principal, tenant_id: str, project_id: str) -> None:
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Resource belongs to a different tenant")
    authorize_project(principal, project_id)
