"""Contract tests for the optional evaluator; no network or real model required."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest

from services.langgraph.quality.evaluator import evaluate_quality
from services.langgraph.quality.grounded_evaluator import evaluate_grounded_faithfulness


OUTPUT = "The report cites the evidence provided for the user's question."
REQUEST = "Summarize the report."
EVIDENCE = ["The report contains evidence pertinent to the user's question."]


def judge(monkeypatch, score=0.9, *, failure=False):
    recorded = {}
    fake_pkg = ModuleType("deepeval")
    fake_pkg.__path__ = []
    metrics = ModuleType("deepeval.metrics")
    test_case = ModuleType("deepeval.test_case")

    class FakeLLMTestCase:
        def __init__(self, **kwargs):
            recorded["case"] = kwargs

    class FakeFaithfulnessMetric:
        def __init__(self, **kwargs):
            recorded["options"] = kwargs
            self.score = score

        def measure(self, case):
            recorded["measured_case"] = case
            if failure:
                raise RuntimeError("sensitive provider response")

    metrics.FaithfulnessMetric = FakeFaithfulnessMetric
    test_case.LLMTestCase = FakeLLMTestCase
    monkeypatch.setitem(sys.modules, "deepeval", fake_pkg)
    monkeypatch.setitem(sys.modules, "deepeval.metrics", metrics)
    monkeypatch.setitem(sys.modules, "deepeval.test_case", test_case)
    return recorded


def call(**changes):
    args = {
        "output": OUTPUT,
        "request": REQUEST,
        "retrieval_context": EVIDENCE,
        "model": "explicit-test-judge",
    }
    args.update(changes)
    return evaluate_grounded_faithfulness(**args)


def test_original_heuristic_contract_remains_truthful_and_unchanged(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    result = evaluate_quality("A sufficiently long ordinary text output for the existing quality gate.")
    assert result == {
        "evaluation_mode": "heuristic",
        "schema_valid": True,
        "non_empty": True,
        "length_chars": len("A sufficiently long ordinary text output for the existing quality gate."),
        "length_sufficient": True,
        "faithfulness": "NOT_MEASURED",
        "hallucination_rate": "NOT_MEASURED",
        "tool_selection_accuracy": "NOT_MEASURED",
        "output_relevance": "NOT_MEASURED",
        "threshold_passed": True,
    }


def test_missing_evidence_produces_no_measured_score_even_if_key_exists(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    result = call(retrieval_context=[])
    assert result["measurement_status"] == "not_measured"
    assert result["faithfulness"] == "NOT_MEASURED"
    assert result["faithfulness_threshold_passed"] is None


def test_missing_provider_does_not_import_or_call_deepeval(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert call()["reason"] == "provider_not_configured"


def test_non_string_or_blank_evidence_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    assert call(retrieval_context=[" "])["reason"] == "missing_retrieval_evidence"
    assert call(retrieval_context="not a list")["reason"] == "missing_retrieval_evidence"
    assert call(retrieval_context=["real", None])["reason"] == "missing_retrieval_evidence"


def test_success_requires_real_metric_score_and_preserves_provenance(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    recorded = judge(monkeypatch, 0.9)
    result = call()
    assert result["measurement_status"] == "measured"
    assert result["faithfulness"] == 0.9
    assert result["faithfulness_threshold_passed"] is True
    assert recorded["case"] == {
        "input": REQUEST, "actual_output": OUTPUT, "retrieval_context": EVIDENCE
    }
    assert recorded["options"]["model"] == "explicit-test-judge"
    assert recorded["options"]["async_mode"] is False


@pytest.mark.parametrize(
    ("score", "passed"),
    [(0.85, True), (0.84, False), (1.0, True), (0.0, False)],
)
def test_metric_threshold_boundaries(monkeypatch, score, passed):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    judge(monkeypatch, score)
    assert call()["faithfulness_threshold_passed"] is passed


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.01, 1.1, None, True])
def test_invalid_scores_are_never_reported_as_measured(monkeypatch, score):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    judge(monkeypatch, score)
    result = call()
    assert result["reason"] == "invalid_metric_score"
    assert result["faithfulness"] == "NOT_MEASURED"


def test_provider_failure_does_not_leak_data_into_logs(monkeypatch, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    judge(monkeypatch, failure=True)
    result = call()
    assert result["reason"] == "metric_execution_failed"
    assert "sensitive provider response" not in caplog.text
    assert EVIDENCE[0] not in caplog.text
    assert OUTPUT not in caplog.text


def test_invalid_threshold_is_rejected_without_calling_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-token")
    with pytest.raises(ValueError):
        call(threshold=float("nan"))
