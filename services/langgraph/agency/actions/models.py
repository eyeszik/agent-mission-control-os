"""ActionRequest and its approval binding. Pure.

Every hash is AMC-CANON-1 (``canonical_hash``) over canonical JSON. Timestamps
are UTC ISO-8601. Money is ISO-4217 + integer minor units.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.execution.canonical import canonical_hash

from .vocabulary import Environment

_HASH = r"^[a-f0-9]{64}$"
BINDING_VERSION = "amc-action-binding/v1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionRequest(_Strict):
    action_id: str
    tenant_id: str
    project_id: str
    client_id: Optional[str] = None
    actor_ref: str
    capability_ref: str
    target_ref: str
    environment: Environment
    args: dict[str, Any]
    payload_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    dependency_hashes: tuple[tuple[str, str], ...] = ()
    policy_version: str
    risk_ref: str = Field(pattern=_HASH)
    approval_ref: Optional[str] = None
    budget_reservation_ref: Optional[str] = None
    idempotency_key: str = Field(min_length=8, max_length=200)
    correlation_id: str
    created_at: datetime
    expires_at: datetime


class ApprovalBinding(_Strict):
    """Everything an approval is bound to. Any change gives a different hash, so
    an approval can never carry over to a changed request (I05/I06/I07)."""

    binding_version: str = BINDING_VERSION
    capability_ref: str
    descriptor_hash: str = Field(pattern=_HASH)
    tenant_id: str
    project_id: str
    environment: Environment
    target_ref: str
    payload_hash: str = Field(pattern=_HASH)
    dependency_hashes: tuple[tuple[str, str], ...]
    policy_version: str
    effective_class: str
    cost_minor: int = Field(ge=0)
    currency: Optional[str] = None
    expires_at: str

    @property
    def binding_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def effect_key(*, tenant_id: str, capability_ref: str, target_ref: str, payload_hash: str, idempotency_key: str) -> str:
    """The key the provider dedupes on. Tenant-scoped, so two tenants can never
    collide on, or replay, each other's effect."""
    return canonical_hash({"tenant": tenant_id, "capability": capability_ref, "target": target_ref, "payload": payload_hash,
                           "idempotency_key": idempotency_key})


def binding_diff(approved: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """Field-level diff between an approved binding snapshot and the current one."""
    keys = sorted(set(approved) | set(current))
    return [{"field": k, "approved": approved.get(k), "current": current.get(k)} for k in keys if approved.get(k) != current.get(k)]


__all__ = ["ActionRequest", "ApprovalBinding", "BINDING_VERSION", "binding_diff", "effect_key"]
