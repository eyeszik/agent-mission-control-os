"""Strict engineering handoff contracts and checked JSON Schema parity."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from services.langgraph.agency.engineering.context import (
    build_context_record,
    verify_context_bytes,
)
from services.langgraph.agency.engineering.contracts import (
    ENGINEERING_RECORD_SCHEMA,
    AcceptanceCriterion,
    BudgetCeiling,
    ContextRecord,
    DeliverableKind,
    DeliverableSpec,
    EngineeringRecord,
    HandoffRequest,
    OutputDestination,
    RequestedAction,
    SourceRef,
    safe_repo_path,
)

ROOT = Path(__file__).resolve().parents[1]


def sample_handoff(**changes) -> HandoffRequest:
    data = HandoffRequest(
        campaign_id="fixture-campaign",
        source_refs=(SourceRef(artifact_id="brief-001", version=1, content_hash="a" * 64,
                               source_kind="approved_brief"),),
        repository_id="example-repo",
        objective="Apply one bounded fixture change and report evidence.",
        deliverable=DeliverableSpec(
            kind=DeliverableKind.REPOSITORY_PATCH,
            title="Fixture patch",
            audience="Engineering reviewer",
            approved_brief="Synthetic local fixture only; no provider or external action.",
            acceptance=(AcceptanceCriterion(criterion_id="PATCH_TEST", description="A declared test passes.",
                                            evidence_required=("test_record",)),),
        ),
        requested_actions=(RequestedAction.LOCAL_PATCH, RequestedAction.RUN_CHECKS),
        output_destinations=(OutputDestination.LOCAL_REVIEW,),
        budget_ceiling=BudgetCeiling(max_provider_cost_microusd=0, max_compute_seconds=30,
                                     max_storage_bytes=1_000_000),
    )
    return data.model_copy(update=changes) if changes else data


def test_generated_schema_is_real_draft_2020_12_and_exactly_in_sync():
    schema_path = ROOT / "agency" / "engineering" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema == ENGINEERING_RECORD_SCHEMA
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_handoff_roundtrips_through_pydantic_union_and_json_schema():
    handoff = sample_handoff()
    payload = handoff.model_dump(mode="json")
    validated = TypeAdapter(list[EngineeringRecord]).validate_python([payload])
    assert validated == [handoff]
    Draft202012Validator(ENGINEERING_RECORD_SCHEMA).validate([payload])

    example = json.loads((ROOT / "agency" / "engineering" / "handoff.example.json").read_text())
    parsed = HandoffRequest.model_validate(example)
    Draft202012Validator(ENGINEERING_RECORD_SCHEMA).validate([parsed.model_dump(mode="json")])
    assert parsed.requested_actions == (RequestedAction.LOCAL_PATCH, RequestedAction.RUN_CHECKS)
    assert parsed.output_destinations == (OutputDestination.LOCAL_REVIEW,)


def test_reference_execution_policy_cannot_enable_workers_or_external_writes():
    policy = json.loads((ROOT / "agency" / "engineering" / "execution-policy.example.json").read_text())
    assert policy["active"] is False
    assert policy["model_generated_code"] == "BLOCKED"
    assert policy["worker_registration"] == "DISABLED"
    assert policy["live_github_writes"] is False
    assert policy["automatic_draft_pr"] is False
    assert "seccomp-filter" in policy["unavailable_controls"]
    assert policy["failure_policy"] == "BLOCK; NEVER EXECUTE ON HOST"


def test_contracts_are_strict_frozen_and_reject_unknown_authority_fields():
    payload = sample_handoff().model_dump(mode="json")
    payload["tenant_id"] = "attacker-supplied-tenant"
    with pytest.raises(ValidationError):
        HandoffRequest.model_validate(payload)
    handoff = sample_handoff()
    with pytest.raises(ValidationError):
        handoff.objective = "mutated"


@pytest.mark.parametrize("path", [
    "../outside.py", "/absolute.py", "src\\windows.py", ".git/config", ".env.production",
    "node_modules/pkg/index.js", "src//empty.py", "src/./dot.py",
])
def test_repository_paths_reject_traversal_and_sensitive_runtime_files(path):
    with pytest.raises(ValueError):
        safe_repo_path(path)


def test_context_manifest_hash_binds_revision_paths_sizes_spans_and_blob_bytes():
    context = build_context_record(revision="a" * 40, files={"src/app.py": "value = 1\\n"},
                                   method="EXPLICIT_FILE")
    verify_context_bytes(context, {"src/app.py": "value = 1\\n"})
    with pytest.raises(ValueError, match="CONTEXT_BLOB_MISMATCH"):
        verify_context_bytes(context, {"src/app.py": "value = 2\\n"})
    tampered = context.model_dump(mode="json")
    tampered["files"][0]["blob_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="context hash does not match"):
        ContextRecord.model_validate(tampered)


def test_no_external_approval_is_implied_by_requesting_local_review():
    handoff = sample_handoff()
    assert handoff.requested_actions == (RequestedAction.LOCAL_PATCH, RequestedAction.RUN_CHECKS)
    assert handoff.output_destinations == (OutputDestination.LOCAL_REVIEW,)
    assert not hasattr(handoff, "approved_by")
