"""Quality evaluation with an optional DeepEval LLM-judge path."""

from __future__ import annotations

import logging
import math
import os
from typing import Optional

LOGGER = logging.getLogger(__name__)

FAITHFULNESS_THRESHOLD = 0.85
HALLUCINATION_THRESHOLD = 0.10
DEFAULT_DEEPEVAL_MODEL = "gpt-4o-mini"

def _validated_metric_score(value: object, metric_name: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{metric_name} did not return a numeric score") from exc
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError(f"{metric_name} returned a score outside [0, 1]")
    return score

def _length_heuristic(output: str) -> dict:
    if len(output) < 10:
        return {
            "faithfulness": 0.2,
            "hallucination_rate": 0.8,
            "tool_selection_accuracy": 0.0,
            "output_relevance": 0.1,
            "threshold_passed": False,
            "evaluator": "length_heuristic",
        }

    base_score = min(1.0, len(output) / 1000.0) + 0.5
    faithfulness = min(0.99, base_score * 0.9)
    hallucination_rate = max(0.01, 1.0 - base_score)
    relevance = min(0.99, base_score * 0.95)
    threshold_passed = (
        faithfulness >= FAITHFULNESS_THRESHOLD
        and hallucination_rate <= HALLUCINATION_THRESHOLD
    )

    return {
        "faithfulness": round(faithfulness, 2),
        "hallucination_rate": round(hallucination_rate, 2),
        "tool_selection_accuracy": 1.0,
        "output_relevance": round(relevance, 2),
        "threshold_passed": threshold_passed,
        "evaluator": "length_heuristic",
    }

def evaluate_quality(output: str, context: Optional[str] = None) -> dict:
    """Evaluate artifact quality.

    With non-empty ``context``, an OpenAI API key, and the optional DeepEval
    extra installed, this uses FaithfulnessMetric and HallucinationMetric.
    Otherwise it returns the original deterministic length heuristic.

    ``context`` currently means fidelity to the original request, not genuine
    retrieval grounding: ``retrieval_node`` does not yet supply reference
    evidence (see risk R-013). The returned evaluator name makes the active
    path explicit.
    """
    if len(output) < 10:
        return _length_heuristic(output)

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

            model = os.environ.get("DEEPEVAL_MODEL", DEFAULT_DEEPEVAL_MODEL)
            faithfulness_metric = FaithfulnessMetric(
                threshold=FAITHFULNESS_THRESHOLD,
                model=model,
            )
            hallucination_metric = HallucinationMetric(
                threshold=HALLUCINATION_THRESHOLD,
                model=model,
            )

            faithfulness_metric.measure(test_case)
            hallucination_metric.measure(test_case)

            faithfulness = _validated_metric_score(
                faithfulness_metric.score,
                "FaithfulnessMetric",
            )
            hallucination_rate = _validated_metric_score(
                hallucination_metric.score,
                "HallucinationMetric",
            )

            relevance = min(0.99, faithfulness * 0.95)

            # DeepEval defines Faithfulness threshold as a minimum and
            # Hallucination threshold as a maximum, so equality passes.
            threshold_passed = (
                faithfulness >= FAITHFULNESS_THRESHOLD
                and hallucination_rate <= HALLUCINATION_THRESHOLD
            )

            return {
                "faithfulness": round(faithfulness, 2),
                "hallucination_rate": round(hallucination_rate, 2),
                "tool_selection_accuracy": 1.0,
                "output_relevance": round(relevance, 2),
                "threshold_passed": threshold_passed,
                "evaluator": "deepeval_llm_judge",
            }

        except ImportError:
            LOGGER.warning(
                "DeepEval is not installed; falling back to the length heuristic"
            )
        except Exception:
            # Never log the raw output, context, or API key: they may be sensitive.
            LOGGER.warning(
                "DeepEval evaluation failed; falling back to the length heuristic",
                exc_info=True,
            )

    return _length_heuristic(output)
