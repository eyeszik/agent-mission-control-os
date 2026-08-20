def evaluate_quality(output: str) -> dict:
    """
    Deterministic local heuristics with truthful metric names.

    This function does not measure factual faithfulness, hallucination rate, or
    semantic relevance because no grounding corpus/reference answer is supplied.
    Those properties remain NOT_MEASURED rather than receiving invented scores.
    """

    text = output or ""
    non_empty = bool(text.strip())
    length = len(text.strip())
    length_sufficient = length >= 40

    return {
        "evaluation_mode": "heuristic",
        "schema_valid": True,
        "non_empty": non_empty,
        "length_chars": length,
        "length_sufficient": length_sufficient,
        "faithfulness": "NOT_MEASURED",
        "hallucination_rate": "NOT_MEASURED",
        "tool_selection_accuracy": "NOT_MEASURED",
        "output_relevance": "NOT_MEASURED",
        "threshold_passed": non_empty and length_sufficient,
    }
