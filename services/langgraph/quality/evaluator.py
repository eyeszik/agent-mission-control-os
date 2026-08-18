import os
from typing import Optional

def evaluate_quality(output: str, context: Optional[str] = None) -> dict:
    """
    Evaluate artifact quality.

    If `context` is provided AND OPENAI_API_KEY is set AND deepeval is
    installed, uses DeepEval's FaithfulnessMetric + HallucinationMetric
    (LLM-as-judge) scored against `context`.

    NOTE ON CONTEXT SEMANTICS: `context` should currently be understood as
    "fidelity to the original request" (state["extracted_data"] from
    ingest_node), NOT retrieval-augmented grounding -- retrieval_node is
    presently a stub (see risk R-013) and writes no real reference context.
    Do not describe this as RAG-grounded faithfulness until R-013 is closed.

    Falls back to the local length-based heuristic (unchanged from prior
    behavior) if context is omitted, the API key is missing, or deepeval
    is not installed -- this matches the existing graceful-degradation
    pattern already used in graph/nodes/planner.py.
    """
    if len(output) < 10:
        return {
            "faithfulness": 0.2,
            "hallucination_rate": 0.8,
            "tool_selection_accuracy": 0.0,
            "output_relevance": 0.1,
            "threshold_passed": False,
            "evaluator": "length_heuristic",
        }

    api_key = os.environ.get("OPENAI_API_KEY")
    if context and api_key:
        try:
            from deepeval.metrics import FaithfulnessMetric, HallucinationMetric
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(
                input=context,
                actual_output=output,
                retrieval_context=[context],
                context=[context],
            )
            faithfulness_metric = FaithfulnessMetric(threshold=0.85, model="gpt-4o-mini")
            hallucination_metric = HallucinationMetric(threshold=0.1, model="gpt-4o-mini")

            faithfulness_metric.measure(test_case)
            hallucination_metric.measure(test_case)

            faithfulness = faithfulness_metric.score
            hallucination_rate = hallucination_metric.score
            relevance = min(0.99, faithfulness * 0.95)
            threshold_passed = faithfulness > 0.85 and hallucination_rate < 0.1

            return {
                "faithfulness": round(faithfulness, 2),
                "hallucination_rate": round(hallucination_rate, 2),
                "tool_selection_accuracy": 1.0,
                "output_relevance": round(relevance, 2),
                "threshold_passed": threshold_passed,
                "evaluator": "deepeval_llm_judge",
            }
        except Exception:
            pass

    base_score = min(1.0, len(output) / 1000.0) + 0.5
    faithfulness = min(0.99, base_score * 0.9)
    hallucination_rate = max(0.01, 1.0 - base_score)
    relevance = min(0.99, base_score * 0.95)
    threshold_passed = faithfulness > 0.85 and hallucination_rate < 0.1

    return {
        "faithfulness": round(faithfulness, 2),
        "hallucination_rate": round(hallucination_rate, 2),
        "tool_selection_accuracy": 1.0,
        "output_relevance": round(relevance, 2),
        "threshold_passed": threshold_passed,
        "evaluator": "length_heuristic",
    }
