"""Execution-record cross-language parity fixture (Python is the reference).

`packages/execution/tests/fixtures/execution-models.json` records, for every
model in `agency/execution/models.py`:

- ``valid``: inputs with the exact ``model_dump(mode="json")`` Python produces
  (defaults included) and the AMC-CANON-1 ``canonical_hash`` of the model;
  ``dynamic`` names fields filled by ``utc_now`` (compared by format only);
- ``invalid``: one input per validation rule, each rejected by Python;
- ``datetimes``: the accepted datetime strings and their dumped form, plus
  rejected strings, exercised through ``ExecutionReceipt.started_at``;
- ``lax_divergences``: inputs Pydantic's lax mode coerces (numeric strings,
  bool-as-number, unix timestamps, ints beyond 2^53) that `@amc/execution`
  deliberately refuses rather than guessing;
- ``hash_divergences``: integral floats inside ``Any`` fields, which JSON
  cannot carry as floats; the TypeScript side must wrap them in
  ``CanonicalFloat`` to reproduce the hash;
- ``proof_coverage``: ``proof_coverage_from`` results.

`@amc/execution` must reproduce every entry. This test checks the stored
entries still match Python, so a change to the models fails here first.
Regenerate with AMC_REGENERATE_FIXTURES=1.
"""
from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from services.langgraph.agency.execution import models as m
from services.langgraph.agency.execution.canonical import canonical_hash

FIXTURE = Path(__file__).resolve().parents[3] / "packages/execution/tests/fixtures/execution-models.json"
H1, H2 = "a" * 64, "0123456789abcdef" * 4
T0, T1 = "2026-01-01T00:00:00Z", "2026-01-02T03:04:05.250000+02:00"

MODELS: dict[str, type[BaseModel]] = {cls.__name__: cls for cls in (
    m.ArtifactIdentity, m.ArtifactVersion, m.ArtifactDependency, m.VersionDependencyBinding, m.ApprovalBinding,
    m.ExecutionReceipt, m.ObservationReceipt, m.FailureFingerprint, m.ProjectExecutionProjection,
    m.DispatchPermit, m.CompletionCriterion, m.CompletionCriterionResult, m.CompletionEvaluation,
)}
ENUMS: tuple[type[Enum], ...] = (
    m.ArtifactLifecycle, m.DependencyImpact, m.DependencyPolicy, m.SemanticChange, m.ApprovalStatus,
    m.WorkOrderState, m.CriterionStatus,
)

# Smallest valid payload per model, with every datetime given explicitly.
MINIMAL: dict[str, dict[str, Any]] = {
    "ArtifactIdentity": {"artifact_id": "art-1", "project_id": "p-1", "engagement_id": "e-1",
                         "artifact_type": "brand_core", "owner_department": "strategy"},
    "ArtifactVersion": {"artifact_version_id": "av-1", "artifact_id": "art-1", "version": 1, "content_hash": H1,
                        "work_order_ref": "wo-1", "created_at": T0},
    "ArtifactDependency": {"upstream_artifact_id": "a", "downstream_artifact_id": "b", "policy": "HARD"},
    "VersionDependencyBinding": {"output_artifact_version_id": "av-2", "input_artifact_version_ids": []},
    "ApprovalBinding": {"approval_id": "ap-1", "subject_type": "ARTIFACT_VERSION", "subject_ref": "art-1",
                        "subject_version_ref": "av-1", "subject_hash": H1, "authority_ref": "role:cd",
                        "policy_version": "v1", "created_at": T0},
    "ExecutionReceipt": {"operation_id": "op-1", "work_order_id": "wo-1", "actor_role_id": "copywriter",
                         "tool": "llm", "tool_contract_ref": "tc-1", "args_hash": H1, "target": "t",
                         "idempotency_key": "k-1", "attempt": 1, "started_at": T0, "ended_at": T1,
                         "returned_state": "OK"},
    "ObservationReceipt": {"operation_id": "op-1", "target": "t", "expected_postcondition": {"state": "OK"},
                           "observed_postcondition": None, "observation_method": "read_back",
                           "observed_at": T0, "matches": False},
    "FailureFingerprint": {"fingerprint": H1, "failure_class": "TOOL", "causal_node": "copywriting",
                           "work_order_input_hash": "x", "dependency_snapshot_hash": "y",
                           "tool_contract_hash": "z", "environment_signature": "env", "error_class": "E"},
    "ProjectExecutionProjection": {"project_id": "p-1", "engagement_id": "e-1", "mission_id": "m-1",
                                   "current_phase": "BUILD", "causal_epoch": 0, "proof_coverage": 0.5,
                                   "updated_at": T0, "snapshot_hash": H1},
    "DispatchPermit": {"permit_id": "pm-1", "work_order_id": "wo-1", "project_snapshot_hash": H1,
                       "causal_epoch": 3, "eligibility_policy_version": "v1", "issued_at": T0},
    "CompletionCriterion": {"criterion_ref": "c-1"},
    "CompletionCriterionResult": {"criterion_ref": "c-1", "status": "SATISFIED"},
    "CompletionEvaluation": {"terminal_candidate": "BLOCKED", "criteria": [], "proof_coverage": 0.0,
                             "confidence": 0.25},
}

REFS = ["r-2", "r-1", "r-1"]
FULL_EXTRA: dict[str, dict[str, Any]] = {
    "ArtifactVersion": {"version": 7, "parent_version_ref": "av-0", "branch": "feature/é", "semantic_fingerprint": "sf",
                        "generation_mode": "LIVE", "dependency_version_refs": REFS, "validation_refs": ["v"],
                        "lifecycle": "RELEASED", "created_at": T1},
    "VersionDependencyBinding": {"input_artifact_version_ids": REFS},
    "ApprovalBinding": {"subject_type": "RELEASE_SUBJECT", "status": "STALE", "reviewer_ref": "u-1",
                        "decision": "approve", "decided_at": "2026-01-03T00:00:00.000001Z",
                        "staled_at": "2026-01-04T00:00:00-05:30", "stale_reason": "upstream changed"},
    "ExecutionReceipt": {"attempt": 2, "result_ref": "res-1"},
    "ObservationReceipt": {"expected_postcondition": [1, "two", {"three": [None, True]}, 0.5],
                           "observed_postcondition": "🎨 done", "evidence_refs": REFS, "matches": True},
    "FailureFingerprint": {"error_code": "E42", "observed_postcondition": {"n": -3, "x": 2.5}},
    "ProjectExecutionProjection": {"causal_epoch": 12, "active_work_order_ids": REFS, "ready_work_order_ids": ["a"],
                                   "blocked_work_order_ids": ["b"], "awaiting_approval_ids": ["c"],
                                   "artifact_head_refs": ["d"], "stale_artifact_ids": ["e"], "blockers": ["f"],
                                   "proof_coverage": 1},
    "DispatchPermit": {"dependency_version_refs": REFS, "authority_refs": ["a"], "approval_refs": ["b"],
                       "tool_contract_refs": ["c"]},
    "CompletionCriterion": {"mandatory": False, "required_artifact_version_refs": REFS, "required_test_refs": ["t"],
                            "required_execution_receipt_refs": ["e"], "required_observation_refs": ["o"],
                            "required_evidence_refs": ["v"], "required_approval_refs": ["a"],
                            "required_metric_refs": ["m"]},
    "CompletionCriterionResult": {"status": "STALE", "missing_refs": ["m"], "stale_refs": REFS},
    "CompletionEvaluation": {"terminal_candidate": "COMPLETE", "proof_coverage": 1,
                             "criteria": [{"criterion_ref": "c-1", "status": "SATISFIED"},
                                          {"criterion_ref": "c-2", "status": "NOT_APPLICABLE", "missing_refs": ["x"]}],
                             "evidence_score": 1, "quality_score": 0.875, "confidence": 0},
}

EXTRA_VALID: list[tuple[str, str, dict[str, Any]]] = [
    ("ArtifactVersion", "every lifecycle value", {"lifecycle": "INVALIDATED"}),
    ("ArtifactVersion", "version int given as integral float", {"version": 2.0}),
    ("ArtifactDependency", "soft policy", {"policy": "SOFT"}),
    ("ExecutionReceipt", "attempt upper bound", {"attempt": 3}),
    ("ObservationReceipt", "null expected postcondition", {"expected_postcondition": None}),
    ("FailureFingerprint", "explicit null observed postcondition", {"observed_postcondition": None}),
    ("ProjectExecutionProjection", "proof coverage zero", {"proof_coverage": 0}),
    ("CompletionEvaluation", "scores at bounds", {"evidence_score": 0, "quality_score": 1.0, "confidence": 1}),
    ("CompletionEvaluation", "awkward float", {"confidence": 0.1 + 0.2, "proof_coverage": 1 / 3}),
    ("CompletionCriterionResult", "blocked", {"status": "BLOCKED"}),
    ("ApprovalBinding", "every status", {"status": "REJECTED"}),
]

DYNAMIC: dict[str, str] = {"ArtifactVersion": "created_at", "ApprovalBinding": "created_at",
                           "ObservationReceipt": "observed_at", "ProjectExecutionProjection": "updated_at",
                           "DispatchPermit": "issued_at"}

DATETIMES_VALID = [
    "2026-01-01T00:00:00Z", "2026-01-01t00:00:00z", "2026-01-01 00:00:00Z", "2026-01-01T00:00Z",
    "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00-00:00", "2026-01-01T00:00:00+0000", "2026-01-01T00:00:00+0530",
    "2026-01-01T00:00:00-03:30", "2026-01-01T00:00:00+23:59", "2026-01-01T00:00:00.5Z", "2026-01-01T00:00:00,5Z",
    "2026-01-01T00:00:00.120Z", "2026-01-01T00:00:00.000Z", "2026-01-01T00:00:00.123456789Z",
    "2026-01-01T00:00:00.0000005Z", "2026-01-01T00:00:00.9999999Z", "2026-01-01T00:00:00", "2026-01-01T00:00",
    "2026-01-01T12:34:56.789", "2026-01-01", "2024-02-29T00:00:00Z", "2000-02-29", "0001-01-01T00:00:00Z",
    "9999-12-31T23:59:59.999999Z", "2026-06-30T23:59:59+14:00",
]
DATETIMES_INVALID = [
    "", "now", "2026-01-01T00:00:60Z", "2026-01-01T24:00:00Z", "2026-01-01T00:60:00Z", "2025-02-29T00:00:00Z",
    "1900-02-29", "2026-04-31", "2026-13-01", "2026-00-10", "2026-01-00", "0000-01-01T00:00:00Z",
    "2026-01-01T00:00:00+24:00", "2026-01-01T00:00:00+05:60", "2026-01-01T00:00:00+05:30:15", "2026-01-01T00:00:00+05",
    "2026-01-01T00:00:00+00", "2026-01-01T00:00:00.Z", " 2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z ",
    "2026-1-01T00:00:00Z", "2026-01-01T00Z", "2026-01-01T00:00:00UTC", "2026-01-01x", "20260101T000000Z",
    "2026-01-01Z", "1e3", "2026-01-01T1:00:00Z",
]

LAX: list[tuple[str, str, dict[str, Any]]] = [
    ("ExecutionReceipt", "numeric string for int", {"attempt": "2"}),
    ("ExecutionReceipt", "bool for int", {"attempt": True}),
    ("ExecutionReceipt", "unix seconds for datetime", {"started_at": 0}),
    ("ExecutionReceipt", "unix seconds string for datetime", {"started_at": "1700000000"}),
    ("ExecutionReceipt", "negative unix string for datetime", {"started_at": "-1"}),
    ("CompletionCriterion", "yes string for bool", {"mandatory": "yes"}),
    ("CompletionCriterion", "int for bool", {"mandatory": 0}),
    ("CompletionEvaluation", "numeric string for float", {"confidence": "0.5"}),
    ("CompletionEvaluation", "bool for float union", {"evidence_score": True}),
    ("ArtifactVersion", "int beyond 2^53", {"version": 2**60}),
]


def _payload(model: str, **changes: Any) -> dict[str, Any]:
    payload = json.loads(json.dumps(MINIMAL[model]))
    payload.update(json.loads(json.dumps(changes)))
    return payload


def _without(model: str, field: str) -> dict[str, Any]:
    payload = _payload(model)
    payload.pop(field, None)
    return payload


def _valid(model: str, name: str, payload: dict[str, Any], dynamic: tuple[str, ...] = ()) -> dict[str, Any]:
    record = MODELS[model].model_validate(payload)
    dump = record.model_dump(mode="json")
    for field in dynamic:
        dump.pop(field)
    case = {"name": f"{model}: {name}", "model": model, "input": payload, "dump": dump, "dynamic": list(dynamic)}
    if not dynamic:
        case["hash"] = canonical_hash(record)
    return case


def _valid_cases() -> list[dict[str, Any]]:
    cases = [_valid(n, "minimal", _payload(n)) for n in MODELS]
    cases += [_valid(n, "every field", _payload(n, **extra)) for n, extra in FULL_EXTRA.items()]
    cases += [_valid(n, label, _payload(n, **extra)) for n, label, extra in EXTRA_VALID]
    cases += [_valid(n, "default timestamp", _without(n, f), (f,)) for n, f in DYNAMIC.items()]
    return cases


def _required_fields(model: str) -> list[str]:
    return [name for name, field in MODELS[model].model_fields.items() if field.is_required()]


def _field_rules(model: str) -> list[tuple[str, dict[str, Any]]]:
    rules: list[tuple[str, dict[str, Any]]] = [(f"missing {f}", _without(model, f)) for f in _required_fields(model)]
    rules.append(("extra key", _payload(model, unexpected=1)))
    for name in MINIMAL[model]:
        rules.append((f"null {name}", _payload(model, **{name: None})))
    return [(label, p) for label, p in rules if not _accepts(model, p)]


def _accepts(model: str, payload: dict[str, Any]) -> bool:
    try:
        MODELS[model].model_validate(payload)
    except ValidationError:
        return False
    return True


BAD_HASHES = ["A" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n", "g" * 64, ""]
TARGETED: list[tuple[str, str, dict[str, Any]]] = [
    *[(model, f"bad {field} {bad!r}", {field: bad}) for model, field in (
        ("ArtifactVersion", "content_hash"), ("ApprovalBinding", "subject_hash"), ("ExecutionReceipt", "args_hash"),
        ("FailureFingerprint", "fingerprint"), ("ProjectExecutionProjection", "snapshot_hash"),
        ("DispatchPermit", "project_snapshot_hash")) for bad in BAD_HASHES],
    ("ArtifactVersion", "version below 1", {"version": 0}),
    ("ArtifactVersion", "fractional version", {"version": 1.5}),
    ("ArtifactVersion", "list for int", {"version": [1]}),
    ("ArtifactVersion", "lowercase lifecycle", {"lifecycle": "draft"}),
    ("ArtifactVersion", "unknown lifecycle", {"lifecycle": "SHIPPED"}),
    ("ArtifactVersion", "int for str field", {"branch": 5}),
    ("ArtifactVersion", "string for tuple", {"validation_refs": "ab"}),
    ("ArtifactVersion", "int inside tuple", {"validation_refs": ["a", 1]}),
    ("ArtifactVersion", "object for tuple", {"validation_refs": {"a": 1}}),
    ("ArtifactDependency", "unknown policy", {"policy": "MEDIUM"}),
    ("ApprovalBinding", "unknown subject type", {"subject_type": "PROJECT"}),
    ("ApprovalBinding", "unknown status", {"status": "WITHDRAWN"}),
    ("ApprovalBinding", "invalid decided_at", {"decided_at": "yesterday"}),
    ("ExecutionReceipt", "attempt below 1", {"attempt": 0}),
    ("ExecutionReceipt", "attempt above 3", {"attempt": 4}),
    ("ExecutionReceipt", "invalid ended_at", {"ended_at": "2026-02-30T00:00:00Z"}),
    ("ObservationReceipt", "string for bool", {"matches": "maybe"}),
    ("ObservationReceipt", "number 2 for bool", {"matches": 2}),
    ("ProjectExecutionProjection", "negative causal epoch", {"causal_epoch": -1}),
    ("ProjectExecutionProjection", "proof coverage above 1", {"proof_coverage": 1.0000001}),
    ("ProjectExecutionProjection", "proof coverage below 0", {"proof_coverage": -0.1}),
    ("ProjectExecutionProjection", "string for float", {"proof_coverage": "half"}),
    ("DispatchPermit", "negative causal epoch", {"causal_epoch": -5}),
    ("CompletionCriterion", "string for bool", {"mandatory": "maybe"}),
    ("CompletionCriterionResult", "lowercase status", {"status": "satisfied"}),
    ("CompletionCriterionResult", "unknown status", {"status": "DONE"}),
    ("CompletionEvaluation", "unknown terminal candidate", {"terminal_candidate": "RUNNING"}),
    ("CompletionEvaluation", "confidence above 1", {"confidence": 1.5}),
    ("CompletionEvaluation", "evidence score above 1", {"evidence_score": 2}),
    ("CompletionEvaluation", "quality score below 0", {"quality_score": -1}),
    ("CompletionEvaluation", "lowercase not measured", {"evidence_score": "not_measured"}),
    ("CompletionEvaluation", "null score", {"quality_score": None}),
    ("CompletionEvaluation", "invalid nested criterion", {"criteria": [{"criterion_ref": "c", "status": "NOPE"}]}),
    ("CompletionEvaluation", "extra key in nested criterion",
     {"criteria": [{"criterion_ref": "c", "status": "SATISFIED", "note": "x"}]}),
]


def _invalid_cases() -> list[dict[str, Any]]:
    cases = [{"name": f"{n}: {label}", "model": n, "input": p} for n in MODELS for label, p in _field_rules(n)]
    cases += [{"name": f"{n}: {label}", "model": n, "input": _payload(n, **ch)} for n, label, ch in TARGETED]
    return cases


def _datetimes() -> dict[str, Any]:
    def dump(text: str) -> str:
        return m.ExecutionReceipt.model_validate(_payload("ExecutionReceipt", started_at=text)).model_dump(
            mode="json")["started_at"]
    return {"valid": [{"input": t, "dump": dump(t)} for t in DATETIMES_VALID], "invalid": DATETIMES_INVALID}


def _lax_cases() -> list[dict[str, Any]]:
    out = []
    for model, label, changes in LAX:
        payload = _payload(model, **changes)
        dump = MODELS[model].model_validate(payload).model_dump(mode="json")
        out.append({"name": f"{model}: {label}", "model": model, "input": payload, "python_dump": dump})
    return out


def _hash_divergences() -> list[dict[str, Any]]:
    payload = _payload("ObservationReceipt", expected_postcondition={"ratio": 1.0, "n": 1},
                       observed_postcondition=[2.0])
    record = m.ObservationReceipt.model_validate(payload)
    return [{"name": "ObservationReceipt: integral floats inside Any fields", "model": "ObservationReceipt",
             "input": payload, "float_paths": [["expected_postcondition", "ratio"], ["observed_postcondition", 0]],
             "hash": canonical_hash(record)}]


COVERAGE_SETS: list[list[str]] = [
    [], ["SATISFIED"], ["UNSATISFIED"], ["BLOCKED", "BLOCKED"], ["SATISFIED", "STALE", "NOT_APPLICABLE"],
    ["SATISFIED", "SATISFIED", "UNSATISFIED"], ["SATISFIED"] * 7 + ["STALE"] * 3,
]


def _coverage(statuses: list[str]) -> dict[str, Any]:
    criteria = [{"criterion_ref": f"c-{i}", "status": s} for i, s in enumerate(statuses)]
    parsed = tuple(m.CompletionCriterionResult.model_validate(c) for c in criteria)
    return {"criteria": criteria, "value": m.proof_coverage_from(parsed)}


def build_fixture() -> dict[str, Any]:
    return {
        "source": "services/langgraph/agency/execution/models.py",
        "not_measured": m.NOT_MEASURED,
        "enums": {e.__name__: [member.value for member in e] for e in ENUMS},
        "models": {name: list(cls.model_fields) for name, cls in MODELS.items()},
        "valid": _valid_cases(),
        "invalid": _invalid_cases(),
        "datetimes": _datetimes(),
        "lax_divergences": _lax_cases(),
        "hash_divergences": _hash_divergences(),
        "proof_coverage": [_coverage(s) for s in COVERAGE_SETS],
    }


def _load() -> dict[str, Any]:
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(build_fixture(), indent=1, ensure_ascii=True) + "\n")
    return json.loads(FIXTURE.read_text())


def test_fixture_matches_a_fresh_build() -> None:
    assert _load() == json.loads(json.dumps(build_fixture()))


def test_valid_cases_match_python_reference() -> None:
    fixture = _load()
    assert len(fixture["valid"]) >= 40
    for case in fixture["valid"]:
        record = MODELS[case["model"]].model_validate(case["input"])
        dump = record.model_dump(mode="json")
        for field in case["dynamic"]:
            assert isinstance(dump.pop(field), str), case["name"]
        assert dump == case["dump"], case["name"]
        if not case["dynamic"]:
            assert canonical_hash(record) == case["hash"], case["name"]


def test_invalid_cases_are_rejected_by_python() -> None:
    fixture = _load()
    assert len(fixture["invalid"]) >= 100
    for case in fixture["invalid"]:
        with pytest.raises(ValidationError):
            MODELS[case["model"]].model_validate(case["input"])


def test_datetime_cases_match_python_reference() -> None:
    dates = _load()["datetimes"]
    for case in dates["valid"]:
        record = m.ExecutionReceipt.model_validate(_payload("ExecutionReceipt", started_at=case["input"]))
        assert record.model_dump(mode="json")["started_at"] == case["dump"], case["input"]
    for text in dates["invalid"]:
        with pytest.raises(ValidationError):
            m.ExecutionReceipt.model_validate(_payload("ExecutionReceipt", started_at=text))


def test_divergences_are_still_python_behaviour() -> None:
    fixture = _load()
    for case in fixture["lax_divergences"]:
        record = MODELS[case["model"]].model_validate(case["input"])
        assert record.model_dump(mode="json") == case["python_dump"], case["name"]
    for case in fixture["hash_divergences"]:
        assert canonical_hash(MODELS[case["model"]].model_validate(case["input"])) == case["hash"], case["name"]


def test_proof_coverage_matches_python_reference() -> None:
    for case in _load()["proof_coverage"]:
        parsed = tuple(m.CompletionCriterionResult.model_validate(c) for c in case["criteria"])
        assert m.proof_coverage_from(parsed) == case["value"]
