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
    # Mirrors how planner.py / validation.py currently call evaluate_quality:
    # positionally, with no context argument.
    result = evaluate_quality("a" * 500)
    assert "threshold_passed" in result
    assert result["evaluator"] == "length_heuristic"
