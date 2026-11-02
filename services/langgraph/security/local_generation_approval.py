"""Explicit owner-only exception for exact, zero-paid-cost local generation plans.

This is not release authority. It never creates an identity or an approval.
"""
from __future__ import annotations

import os

from services.langgraph.security.auth import Principal

SOLO_POLICY = "unbound-local-owner/v1"
PURPOSE = "INNOVATION_GENERATION"


def enabled() -> bool:
    return ((os.environ.get("AMC_ENV") or "local").strip().lower() == "local"
            and (os.environ.get("AMC_AUTH_MODE") or "local").strip().lower() == "local"
            and os.environ.get("AMC_INNOVATION_SOLO_OWNER_APPROVAL") == "1"
            and os.environ.get("OLLAMA_NO_CLOUD") == "1")


def permits_owner(principal: Principal, run: dict, approval: dict) -> bool:
    """Check authoritative records and actual plan bytes before granting the exception."""
    if not enabled() or principal.role.strip().lower() != "owner":
        return False
    if run.get("pipeline") != "innovation_generation" or approval.get("authority_ref") != "human-review":
        return False
    scope = (principal.tenant_id, approval.get("project_id"))
    if (run.get("tenant_id"), run.get("project_id")) != scope or approval.get("tenant_id") != scope[0]:
        return False
    if not principal.can_access_project(scope[1]) or run.get("run_id") != approval.get("run_id"):
        return False
    if (run.get("metadata") or {}).get("initiated_by") != principal.user_id:
        return False
    if approval.get("policy_version") != SOLO_POLICY or approval.get("subject_type") != PURPOSE:
        return False
    if approval.get("status") not in {"pending", "resolved"}:
        return False
    if approval.get("status") == "resolved" and (approval.get("decision") != "approve" or approval.get("reviewer") != principal.user_id):
        return False
    return _valid_plan(principal, run, approval)


def _valid_plan(principal, run, approval) -> bool:
    from services.langgraph.agency.innovation.generation_service import GenerationPlan, _read_bytes
    from services.langgraph.agency.innovation.service import _read
    from services.langgraph.agency.innovation.generation import provider_blocker
    from services.langgraph.agency.execution.canonical import canonical_hash
    from fastapi import HTTPException
    from services.langgraph.agency.project_os.storage import StorageIntegrityError, resolve_storage_adapter
    from services.langgraph.agency.exporter import resolve_export_root
    from services.langgraph.persistence.agency_kernel import get_artifact

    head = get_artifact(approval.get("subject_ref") or "")
    if not head or (head["tenant_id"], head["project_id"], head.get("subtype")) != (
        principal.tenant_id, run["project_id"], "innovation_generation_plan"
    ):
        return False
    if str(head["version"]) != approval.get("subject_version_ref") or head["content_hash"] != approval.get("subject_hash"):
        return False
    metadata = run.get("metadata") or {}
    if (metadata.get("artifact_id"), metadata.get("artifact_version"), metadata.get("artifact_hash"), metadata.get("contract_hash")) != (
        head["artifact_id"], int(head["version"]), head["content_hash"], head["content_hash"]
    ):
        return False
    try:
        adapter = resolve_storage_adapter(resolve_export_root())
        plan = GenerationPlan.model_validate_json(_read_bytes(head, adapter))
        document, source = _read(principal, run["project_id"], plan.run_id, adapter)
    except (ValueError, OSError, StorageIntegrityError, HTTPException):
        return False
    spec = plan.spec
    if (source["artifact_id"], int(source["version"]), source["content_hash"]) != (spec.source_artifact_id, spec.source_version, spec.source_hash):
        return False
    if canonical_hash(document.brief) != spec.brief_hash or document.run.status in {"PAUSED", "CANCELLED"} or provider_blocker(spec):
        return False
    if spec.provider_profile.primary.model != os.environ.get("AMC_INNOVATION_SOLO_OWNER_MODEL"):
        return False
    return (plan.approval_mode == "solo_owner_local" and spec.provider_profile.primary.provider == "ollama"
            and not spec.provider_profile.fallbacks and spec.max_cost_usd == 0 and spec.max_calls == 1
            and spec.max_output_tokens == 8192 and spec.timeout_seconds == 30 and spec.max_prompt_bytes == 60000)
