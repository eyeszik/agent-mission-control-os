"""Opt-in RAG faithfulness evaluation with source-provenance boundaries.

The canonical evaluate_quality() contract is unchanged. This helper is only
called deliberately by evaluation tooling with real retrieval evidence. A
request, retrieved passages, or output alone cannot establish general factual
correctness; a measured score is an LLM judgment against supplied passages.
"""
from __future__ import annotations

import logging
import math
import os
from collections.abc import Sequence

LOGGER = logging.getLogger(__name__)
NOT_MEASURED = "NOT_MEASURED"


def evaluate_grounded_faithfulness(
    output: str,
    *,
    request: str,
    retrieval_context: Sequence[str],
    model: str,
    threshold: float = 0.85,
) -> dict:
    """Opt in to a DeepEval faithfulness judgment against retrieved evidence.

    This is deliberately NOT wired into the production evaluator, schemas, or
    planner/validation gates. An API key, explicit model, and real retrieved
    references are required. Passing means the *faithfulness metric*, not
    overall output quality, met the threshold.

    The caller is responsible for evidence quality and provider authorization.
    DeepEval may make billable third-party API calls with these inputs.
    """
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be a finite value between 0 and 1")

    def unavailable(reason: str) -> dict:
        return {
            "evaluation_mode": "deepeval_faithfulness",
            "measurement_status": "not_measured",
            "reason": reason,
            "faithfulness": NOT_MEASURED,
            "faithfulness_threshold_passed": None,
        }

    if not isinstance(output, str) or not output.strip() or not isinstance(request, str) or not request.strip():
        return unavailable("missing_request_or_output")
    if isinstance(retrieval_context, (str, bytes)) or not isinstance(retrieval_context, Sequence):
        return unavailable("missing_retrieval_evidence")
    passages = [item.strip() for item in retrieval_context if isinstance(item, str) and item.strip()]
    if not passages or len(passages) != len(retrieval_context):
        return unavailable("missing_retrieval_evidence")
    if not isinstance(model, str) or not model.strip():
        return unavailable("missing_model")
    if not os.environ.get("OPENAI_API_KEY"):
        return unavailable("provider_not_configured")

    try:
        from deepeval.metrics import FaithfulnessMetric
        from deepeval.test_case import LLMTestCase
    except ImportError:
        return unavailable("optional_dependency_missing")

    try:
        test_case = LLMTestCase(
            input=request,
            actual_output=output,
            retrieval_context=passages,
        )
        metric = FaithfulnessMetric(
            threshold=float(threshold),
            model=model,
            include_reason=False,
            async_mode=False,
        )
        metric.measure(test_case)
        score = metric.score
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0.0 <= score <= 1.0
        ):
            return unavailable("invalid_metric_score")
        return {
            "evaluation_mode": "deepeval_faithfulness",
            "measurement_status": "measured",
            "reason": None,
            "faithfulness": float(score),
            "faithfulness_threshold_passed": score >= threshold,
        }
    except Exception as exc:
        # Never log retrieved passages, generated output, provider responses or keys.
        LOGGER.warning("Optional DeepEval faithfulness evaluation failed: %s", type(exc).__name__)
        return unavailable("metric_execution_failed")
