from __future__ import annotations

import os

from services.langgraph.persistence.operations import request_spend_authorization as persist_spend_authorization


def request_spend_authorization(run_id: str | None, tenant_id: str, project_id: str, provider: str, amount_minor: int, currency: str, requested_by: str, reason: str) -> dict:
    if amount_minor < 0:
        raise ValueError("amount_minor must be non-negative")
    return persist_spend_authorization(run_id, tenant_id, project_id, provider, amount_minor, currency, requested_by, reason)


def spend_execution_available() -> bool:
    return (os.environ.get("AMC_PAID_MEDIA_MODE") or "disabled").strip().lower() == "live" and False
