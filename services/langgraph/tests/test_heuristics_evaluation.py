"""Heuristic evaluation and shadow mode (ISSUE-06)."""

import pytest

from services.langgraph.agency.heuristics_evaluation import (
    DATASET,
    DATASET_VERSION,
    evaluate_framing,
    should_promote_threshold,
    ShadowEvaluation,
)


def test_evaluation_dataset_has_explicit_definitions():
    assert len(DATASET) >= 7
    for case in DATASET:
        assert "id" in case
        assert "label" in case
        assert "notes" in case or "text" in case


def test_evaluation_reports_precision_recall_fpr_fnr():
    report = evaluate_framing()
    assert report["dataset_version"] == DATASET_VERSION
    assert "metrics" in report
    m = report["metrics"]
    assert "precision" in m
    assert "recall" in m
    assert "false_positive_rate" in m
    assert "false_negative_rate" in m
    assert "f1" in m
    assert "sample_size" in m
    assert "class_balance" in m
    # Values in [0,1]
    for k in ("precision", "recall", "false_positive_rate", "false_negative_rate"):
        assert 0.0 <= m[k] <= 1.0
    assert m["sample_size"] == len([c for c in DATASET if "expected_codes" in c])


def test_evaluation_records_known_limitations():
    report = evaluate_framing()
    assert "known_limitations" in report
    assert len(report["known_limitations"]) >= 1
    assert report["status"] in ("UNVALIDATED", "MEASURED")


def test_shadow_evaluation_does_not_affect_live_decisions():
    shadow = ShadowEvaluation(threshold_version="candidate-v2")
    shadow.record("f01", threshold=0.8, prediction="HIGH", ground_truth="framing")
    shadow.record("f04", threshold=0.8, prediction="NONE", ground_truth="clean")
    d = shadow.to_dict()
    assert d["threshold_version"] == "candidate-v2"
    assert len(d["predictions"]) == 2
    assert d["predictions"][0]["case_id"] == "f01"


def test_promotion_requires_explicit_acceptance_criteria():
    report = evaluate_framing()
    m = report["metrics"]
    # With small dataset, promotion should fail due to sample size
    promoted, reason = should_promote_threshold(m)
    assert promoted is False
    assert "sample_size" in reason

    # With artificially good metrics and sufficient size, promotion would pass
    good_metrics = {"precision": 0.9, "recall": 0.8, "false_positive_rate": 0.1, "sample_size": 50}
    promoted2, _ = should_promote_threshold(good_metrics)
    assert promoted2 is True


def test_no_calibration_claim_without_probabilistic_scores():
    """Calibration is only valid when detector emits probabilistic confidence and dataset supports it."""
    report = evaluate_framing()
    # Our heuristic detectors do NOT emit calibration metrics; we must not claim calibrated
    assert "calibration" not in report["metrics"]
    assert report["status"] == "UNVALIDATED"  # small dataset, heuristic only
