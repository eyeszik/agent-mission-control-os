"""Offline fixtures prove structural behavior, never production innovation quality."""
import json

import pytest
from pydantic import ValidationError

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.innovation import InnovationBrief, RunResult, compile_run, received_run


@pytest.fixture
def brief():
    return InnovationBrief(objective="Reduce friction in a creative team's local workflow", constraints=["No private user data"])


@pytest.fixture
def result(brief):
    return compile_run(brief, "ir-fixture")


def seal(item):
    item["content_hash"] = canonical_hash({k: v for k, v in item.items() if k != "content_hash"})


def test_complete_simulation_cohort_and_round_trip(brief, result):
    assert received_run(brief, "ir-fixture").status == "RECEIVED"
    assert result.simulation and result.status == "COMPLETED"
    assert len(result.ideas) == 35 and len(result.hybrids) == 4 and len(result.meta_hybrids) == 2
    assert len(result.wildcards) == len(result.shortlist) == len(result.experiments) == 5
    assert {tag for c in result.ideas for tag in c.lens_tags} == {f"L{i}" for i in range(1, 13)}
    assert RunResult.model_validate_json(result.model_dump_json()) == result
    assert compile_run(brief, "ir-fixture") == result
    assert len(result.model_dump_json()) < 512 * 1024


def test_no_fabricated_evidence_or_authority(result):
    assert result.evidence == [] and result.usage is None
    assert all(e.evidence_status == "SIMULATED" for e in result.evaluations)
    assert all(e.execution_state == "NOT_RUN" and e.approval_state == "NOT_REQUESTED" for e in result.experiments)
    assert all(e.decision is None and e.learning is None and e.evidence_refs == [] for e in result.experiments)
    assert all(e.resource_budget["max_external_calls"] == 0 for e in result.experiments)


def test_live_provider_refuses_without_generating(brief):
    result = compile_run(brief.model_copy(update={"provider": "live"}), "ir-live")
    assert result.status == "BLOCKED" and result.phase == "PROVIDER_GAP"
    assert result.simulation is False
    assert not result.ideas and not result.experiments and not result.evidence


@pytest.mark.parametrize("mode,expected,rubric", [("AUTO", "GENERAL", "GENERAL/v1"), ("GENERAL", "GENERAL", "GENERAL/v1"),
                                                 ("HYBRID", "HYBRID", "GENERAL/v1"), ("VENTURE", "VENTURE", "VENTURE/v1")])
def test_explicit_mode_and_rubric(brief, mode, expected, rubric):
    result = compile_run(brief.model_copy(update={"mode": mode}), "ir-mode")
    assert result.mode == expected
    assert {e.rubric_version for e in result.evaluations} == {rubric}
    assert all((c.commercial_fields is not None) == (mode == "VENTURE") for c in result.ideas)


@pytest.mark.parametrize("payload", [
    {"objective": "x"}, {"objective": " " * 20}, {"objective": "x" * 4001},
    {"objective": "A valid fixture objective", "tenant_id": "forged"},
    {"objective": "A valid fixture objective", "external_execution": True},
    {"objective": "A valid fixture objective", "provider": "invented"},
    {"objective": "A valid fixture objective", "constraints": ["x"] * 21},
    {"objective": "A valid fixture objective", "constraints": [" " ]},
])
def test_malformed_or_authority_bearing_input_refused(payload):
    with pytest.raises(ValidationError):
        InnovationBrief.model_validate(payload)


def test_complete_transitive_lineage(result):
    all_concepts = {c.concept_id: c for c in [*result.ideas, *result.hybrids, *result.meta_hybrids]}
    for meta in result.meta_hybrids:
        raw_ancestors = {raw for parent in meta.parent_ids for raw in all_concepts[parent].parent_ids}
        assert len(raw_ancestors) == 4
        assert all(all_concepts[raw].generation == "raw" for raw in raw_ancestors)
    assert len(result.lineage) == 12


@pytest.mark.parametrize("mutation", ["dangling", "cycle", "duplicate_parent", "duplicate_mechanism", "missing_edge", "duplicate_edge",
                                     "bad_hash", "changed_version", "wrong_lens", "wrong_generation", "fake_evidence", "fake_approval",
                                     "fake_execution", "score_tampering", "duplicate_evaluation", "missing_candidate", "wildcard_tampering"])
def test_adversarial_output_refused(result, mutation):
    data = json.loads(result.model_dump_json())
    if mutation == "dangling":
        data["hybrids"][0]["parent_ids"][0] = "missing"
        seal(data["hybrids"][0])
    elif mutation == "cycle":
        data["hybrids"][0]["parent_ids"][0] = data["meta_hybrids"][0]["concept_id"]
        seal(data["hybrids"][0])
    elif mutation == "duplicate_parent":
        data["hybrids"][0]["parent_ids"] = [data["ideas"][0]["concept_id"]] * 2
        seal(data["hybrids"][0])
    elif mutation == "duplicate_mechanism":
        data["ideas"][0]["mechanism"] = data["ideas"][1]["mechanism"]
        seal(data["ideas"][0])
    elif mutation == "missing_edge":
        data["lineage"].pop()
    elif mutation == "duplicate_edge":
        data["lineage"].append(data["lineage"][0])
    elif mutation == "bad_hash":
        data["ideas"][0]["mechanism"] = "altered bytes"
    elif mutation == "changed_version":
        data["ideas"][0]["version"] = 2
    elif mutation == "wrong_lens":
        data["ideas"][0]["lens_tags"] = ["L13"]
        seal(data["ideas"][0])
    elif mutation == "wrong_generation":
        data["ideas"][0]["generation"] = "hybrid"
        seal(data["ideas"][0])
    elif mutation == "fake_evidence":
        data["evidence"] = [{"status": "VERIFIED"}]
    elif mutation == "fake_approval":
        data["experiments"][0]["approval_state"] = "APPROVED"
    elif mutation == "fake_execution":
        data["experiments"][0]["execution_state"] = "SUCCEEDED"
    elif mutation == "score_tampering":
        data["evaluations"][0]["composite"] = 0
    elif mutation == "duplicate_evaluation":
        data["evaluations"][1] = data["evaluations"][0]
    elif mutation == "missing_candidate":
        data["shortlist"][0] = "not-a-concept"
    else:
        data["wildcards"][0]["mechanism"] = "invented"
    with pytest.raises(ValidationError):
        RunResult.model_validate(data)


@pytest.mark.parametrize("status,phase", [("RECEIVED", "RECEIVED"), ("BLOCKED", "PROVIDER_GAP"), ("PAUSED", "PAUSED"), ("CANCELLED", "CANCELLED")])
def test_no_premature_scoring_or_blocked_generated_outputs(result, status, phase):
    data = result.model_dump(mode="json")
    data.update(status=status, phase=phase)
    with pytest.raises(ValidationError, match="preterminal"):
        RunResult.model_validate(data)


def test_status_phase_disagreement_refused(brief):
    data = received_run(brief, "ir-disagreement").model_dump(mode="json")
    data["phase"] = "COMPLETED"
    with pytest.raises(ValidationError, match="status and phase"):
        RunResult.model_validate(data)


@pytest.mark.parametrize("key,value", [("max_cases", 11), ("max_seconds", 61), ("max_retries", 1), ("max_external_calls", 1)])
def test_experiment_bounds_are_enforced_even_with_recomputed_hash(result, key, value):
    data = result.model_dump(mode="json")
    data["experiments"][0]["resource_budget"][key] = value
    seal(data["experiments"][0])
    with pytest.raises(ValidationError, match="resource budget"):
        RunResult.model_validate(data)


def test_compiled_fixture_remains_reproducible():
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parents[3] / "packages/shared/tests/fixtures/innovation.json").read_text())
    result = RunResult.model_validate(data)
    brief = InnovationBrief(objective=result.objective, constraints=["No private user data"])
    assert compile_run(brief, result.run_id).model_dump(mode="json") == data


def test_retry_exhaustion_is_blocked_without_outputs(brief):
    data = received_run(brief, "ir-retry-exhaustion").model_dump(mode="json")
    data.update(status="BLOCKED", phase="RETRY_EXHAUSTED")
    result = RunResult.model_validate(data)
    assert result.simulation and not result.ideas and not result.evaluations and not result.experiments
    data["status"] = "COMPLETED"
    with pytest.raises(ValidationError, match="status and phase"):
        RunResult.model_validate(data)
