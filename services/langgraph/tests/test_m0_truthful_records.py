"""M0 truthful records (G-01 to G-03): scores are measured or NOT_MEASURED,
the Zod provenance twin carries every field the backend writes, and every
variable the code reads is documented in .env.example."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.agency.execution.models import (
    NOT_MEASURED,
    CompletionCriterionResult,
    CompletionEvaluation,
    CriterionStatus,
    proof_coverage_from,
)
from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import GenerationOutcome

ROOT = Path(__file__).resolve().parents[3]
client = TestClient(app)


def _criterion(ref: str, status: CriterionStatus) -> CompletionCriterionResult:
    return CompletionCriterionResult(criterion_ref=ref, status=status)


# --- G-01: completion scores --------------------------------------------------


def test_proof_coverage_is_the_satisfied_share_of_the_criteria():
    assert proof_coverage_from(()) == 0.0
    assert proof_coverage_from((_criterion("a", CriterionStatus.BLOCKED),)) == 0.0
    assert proof_coverage_from((
        _criterion("a", CriterionStatus.SATISFIED),
        _criterion("b", CriterionStatus.SATISFIED),
        _criterion("c", CriterionStatus.BLOCKED),
    )) == pytest.approx(2 / 3)


def test_evidence_and_quality_default_to_not_measured():
    evaluation = CompletionEvaluation(
        terminal_candidate="BLOCKED",
        criteria=(_criterion("a", CriterionStatus.BLOCKED),),
        proof_coverage=0.0,
        confidence=0.5,
    )
    assert evaluation.evidence_score == NOT_MEASURED
    assert evaluation.quality_score == NOT_MEASURED


def test_a_real_measurement_is_still_accepted_and_range_checked():
    evaluation = CompletionEvaluation(
        terminal_candidate="COMPLETE",
        criteria=(_criterion("a", CriterionStatus.SATISFIED),),
        proof_coverage=1.0,
        evidence_score=0.8,
        quality_score=0.9,
        confidence=0.9,
    )
    assert (evaluation.evidence_score, evaluation.quality_score) == (0.8, 0.9)
    with pytest.raises(ValueError):
        CompletionEvaluation(
            terminal_candidate="COMPLETE",
            criteria=(_criterion("a", CriterionStatus.SATISFIED),),
            proof_coverage=1.0,
            evidence_score=1.5,
            confidence=0.9,
        )
    with pytest.raises(ValueError):
        CompletionEvaluation(
            terminal_candidate="COMPLETE",
            criteria=(_criterion("a", CriterionStatus.SATISFIED),),
            proof_coverage=1.0,
            quality_score="UNKNOWN",  # type: ignore[arg-type]
            confidence=0.9,
        )


def test_a_degraded_run_stores_computed_coverage_and_not_measured_scores(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post(
        "/agency/runs",
        json={"project_id": f"proj-m0-{uuid4()}", "brief": {"brand_name": "Northwind", "target_audience": "Makers"}},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    evaluation = response.json()["proof"]["completion_evaluation"]
    assert evaluation["terminal_candidate"] == "BLOCKED"
    assert evaluation["evidence_score"] == NOT_MEASURED
    assert evaluation["quality_score"] == NOT_MEASURED
    # Two of three criteria are satisfied (execution, observation); approval is blocked.
    assert evaluation["proof_coverage"] == pytest.approx(2 / 3)


# --- G-02: the Zod provenance twin carries every field the backend writes -------


def test_zod_provenance_twin_has_every_field_the_backend_writes():
    outcome = GenerationOutcome(
        data={}, mode="FALLBACK_DEGRADED", provider=None, model=None, schema_version="s",
        prompt_version="p", prompt_hash="h", attempts=0, started_at="2026-10-18T00:00:00+00:00",
        completed_at="2026-10-18T00:00:00+00:00", fallback_used=True, error_class="X",
    )
    python_keys = set(outcome.provenance("task"))
    source = (ROOT / "packages" / "shared" / "src" / "schemas" / "agency.ts").read_text(encoding="utf-8")
    block = source.split("export const GenerationProvenanceSchema = z.object({", 1)[1].split("\n});", 1)[0]
    zod_keys = set(re.findall(r"^  (\w+):", block, re.M))
    assert python_keys <= zod_keys, f"Zod drops fields the backend writes: {sorted(python_keys - zod_keys)}"


# --- G-03: every variable the code reads is documented -------------------------


def test_every_environment_variable_the_code_reads_is_documented():
    spec = importlib.util.spec_from_file_location("system_inventory", ROOT / "scripts" / "system_inventory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    undocumented = module.env_vars()["read_but_undocumented"]
    assert undocumented == [], f"document these in .env.example: {undocumented}"
