from __future__ import annotations

import os

from services.langgraph.persistence.operations import create_publication_job


def prepare_publication(run_id: str, tenant_id: str, project_id: str, provider: str, payload: dict, idempotency_key: str) -> dict:
    mode = (os.environ.get("AMC_PUBLICATION_MODE") or "disabled").strip().lower()
    if mode == "disabled":
        return create_publication_job(
            run_id,
            tenant_id,
            project_id,
            provider,
            "dry_run",
            "blocked",
            idempotency_key,
            payload,
            "publication_disabled",
        )
    if mode == "dry_run":
        return create_publication_job(
            run_id,
            tenant_id,
            project_id,
            provider,
            "dry_run",
            "validated",
            idempotency_key,
            payload,
        )
    raise RuntimeError("Live publication is intentionally unavailable until a concrete provider adapter is installed and reviewed")
