from unittest.mock import MagicMock, patch
import pytest
from services.langgraph.quality.evaluator import evaluate_quality

def test_short_output_returns_low_scores():
    result = evaluate_quality("hi")
    assert result["threshold_passed"] is False
    assert result["evaluator"] == "length_heuristic"

def test_falls_back_to_heuristic_without_context():
    result = evaluate_quality("a" * 500)
    assert result["evaluator"] == "length_heuristic"

def test_falls_back_to_heuristic_when_context_given_but_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = evaluate_quality("a" * 500, context="some request context")
    assert result["evaluator"] == "length_heuristic"

def test_existing_call_sites_unaffected_when_context_omitted():
    result = evaluate_quality("a" * 500)
    assert "threshold_passed" in result
    assert result["evaluator"] == "length_heuristic"

def test_deepeval_successful_execution_above_threshold(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-test-key")
    with patch("deepeval.metrics.FaithfulnessMetric") as mock_faith, \
         patch("deepeval.metrics.HallucinationMetric") as mock_hallu, \
         patch("deepeval.test_case.LLMTestCase"):
        
        inst_faith = MagicMock()
        inst_faith.score = 0.90
        mock_faith.return_value = inst_faith

        inst_hallu = MagicMock()
        inst_hallu.score = 0.05
        mock_hallu.return_value = inst_hallu

        result = evaluate_quality("Valid generated artifact output text", context="Original user prompt request")
        assert result["evaluator"] == "deepeval_llm_judge"
        assert result["faithfulness"] == 0.90
        assert result["hallucination_rate"] == 0.05
        assert result["threshold_passed"] is True

def test_deepeval_exact_boundary_conditions_pass(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-test-key")
    with patch("deepeval.metrics.FaithfulnessMetric") as mock_faith, \
         patch("deepeval.metrics.HallucinationMetric") as mock_hallu, \
         patch("deepeval.test_case.LLMTestCase"):
        
        inst_faith = MagicMock()
        inst_faith.score = 0.85
        mock_faith.return_value = inst_faith

        inst_hallu = MagicMock()
        inst_hallu.score = 0.10
        mock_hallu.return_value = inst_hallu

        result = evaluate_quality("Exact boundary artifact output text", context="Original user prompt request")
        assert result["evaluator"] == "deepeval_llm_judge"
        assert result["faithfulness"] == 0.85
        assert result["hallucination_rate"] == 0.10
        assert result["threshold_passed"] is True

def test_deepeval_threshold_failure_behavior(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-test-key")
    with patch("deepeval.metrics.FaithfulnessMetric") as mock_faith, \
         patch("deepeval.metrics.HallucinationMetric") as mock_hallu, \
         patch("deepeval.test_case.LLMTestCase"):
        
        inst_faith = MagicMock()
        inst_faith.score = 0.84
        mock_faith.return_value = inst_faith

        inst_hallu = MagicMock()
        inst_hallu.score = 0.11
        mock_hallu.return_value = inst_hallu

        result = evaluate_quality("Failed threshold artifact output text", context="Original user prompt request")
        assert result["evaluator"] == "deepeval_llm_judge"
        assert result["threshold_passed"] is False

def test_deepeval_exception_triggers_observable_fallback(monkeypatch, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-test-key")
    with patch("deepeval.metrics.FaithfulnessMetric", side_effect=RuntimeError("Remote API Timeout")):
        result = evaluate_quality("Valid generated text under network failure", context="Original prompt")
        assert result["evaluator"] == "length_heuristic"
        assert "DeepEval evaluation failed; falling back to the length heuristic" in caplog.text
