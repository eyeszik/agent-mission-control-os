"""Shared plumbing for the project OS routers: authorization and error mapping.

Every project route resolves the project first, then authorizes the
server-derived principal against the project's *recorded* tenant. Client input
never names the tenant.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from fastapi import HTTPException

from services.langgraph.agency.project_os.calendar import ContentTransitionError
from services.langgraph.agency.project_os.memory import MemoryPolicyError
from services.langgraph.agency.project_os.publishing import PublicationBlocked
from services.langgraph.agency.project_os.storage import (
    StorageAdapter,
    StorageIntegrityError,
    StorageUnavailable,
    resolve_storage_adapter,
)
from services.langgraph.agency.project_os.video import VideoBridgeError
from services.langgraph.agency.project_os.workspace import WorkspacePathError
from services.langgraph.agency.project_os.workstreams import UnknownWorkstream
from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError
from services.langgraph.persistence.project_media import UploadRejected
from services.langgraph.persistence.projects import (
    ProjectConflictError,
    ProjectNotFoundError,
    get_project_workspace,
)
from services.langgraph.persistence.tenancy import ProjectOwnershipError
from services.langgraph.security.approval_authority import approver_roles
from services.langgraph.security.auth import Principal, authorize_resource

# Most specific first: several of these subclass ValueError.
_ERROR_STATUS: tuple[tuple[type[BaseException], int], ...] = (
    (ProjectOwnershipError, 403),
    (ProjectNotFoundError, 404),
    (UnknownWorkstream, 404),
    (StaleArtifactVersionError, 409),
    (ProjectConflictError, 409),
    (ContentTransitionError, 409),
    (PublicationBlocked, 409),
    (WorkspacePathError, 400),
    (UploadRejected, 415),
    (StorageIntegrityError, 409),
    (StorageUnavailable, 503),
    (MemoryPolicyError, 422),
    (VideoBridgeError, 422),
    (PermissionError, 403),
    (ValueError, 422),
)


def _translate(exc: BaseException) -> HTTPException | None:
    for error_type, status in _ERROR_STATUS:
        if isinstance(exc, error_type):
            return HTTPException(status_code=status, detail=str(exc) or error_type.__name__)
    return None


def domain_errors(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Map project-OS domain exceptions to HTTP status codes."""

    @functools.wraps(handler)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return handler(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised unless it is a known domain error
            mapped = _translate(exc)
            if mapped is None:
                raise
            raise mapped from exc

    wrapper.__signature__ = inspect.signature(handler)  # type: ignore[attr-defined]
    return wrapper


def authorize_project_access(principal: Principal, project_id: str):
    workspace = get_project_workspace(project_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Project not found")
    authorize_resource(principal, workspace.tenant_id, project_id)
    return workspace


def require_approver(principal: Principal, action: str) -> None:
    if principal.role.strip().lower() not in approver_roles():
        raise HTTPException(status_code=403, detail=f"{action} requires an approver role")


def storage_adapter() -> StorageAdapter:
    from services.langgraph.agency.exporter import resolve_export_root

    return resolve_storage_adapter(resolve_export_root())
