import random

def evaluate_quality(output: str) -> dict:
    """
    Evaluate artifact quality using local heuristics as a stand-in for LLM-as-a-judge.
    In production, this should integrate with LangSmith or DeepEval.
    """
    # Heuristic: Extremely short output usually lacks detail
    if len(output) < 10:
        return {
            "faithfulness": 0.2,
            "hallucination_rate": 0.8,
            "tool_selection_accuracy": 0.0,
            "output_relevance": 0.1,
            "threshold_passed": False
        }
        
    # Simulated heuristic evaluation (mocking LangSmith logic locally)
    # Replaces the [VOID_DETECTED] gap with deterministic rules combined with variance
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
        "threshold_passed": threshold_passed
    }
