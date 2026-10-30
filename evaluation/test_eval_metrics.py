"""Unit test for metric definitions, independent of the OpenPoke server."""
from .metrics import summarize_quality, latency_summary
from .run_workflow_eval import load_dataset


def test_dataset_integrity():
    dataset, sha = load_dataset()
    workflows = dataset["workflows"]
    cases = dataset["cases"]
    keys = {w["key"] for w in workflows}
    assert len(keys) == len(workflows)
    assert len({c["case_id"] for c in cases}) == len(cases)
    assert len(cases) >= 60
    assert len(sha) == 64
    for case in cases:
        assert case["expected_action"] in {"CREATE", "RESUME", "CLARIFY"}
        assert (case["target_key"] in keys) if case["expected_action"] == "RESUME" else case["target_key"] is None


def test_quality_metrics():
    rows = [
        dict(expected_action="RESUME", predicted_action="RESUME", gold_workflow_id="A", predicted_workflow_id="A",
             bm25_ids=["B", "A"], dense_ids=["A"], hybrid_ids=["A"]),
        dict(expected_action="CREATE", predicted_action="CLARIFY", gold_workflow_id=None, predicted_workflow_id=None,
             bm25_ids=[], dense_ids=[], hybrid_ids=[]),
        dict(expected_action="CLARIFY", predicted_action="RESUME", gold_workflow_id=None, predicted_workflow_id="C",
             bm25_ids=[], dense_ids=[], hybrid_ids=[]),
    ]
    scores = summarize_quality(rows)
    assert scores["retrieval"]["bm25"]["recall_at_1"] == 0.0
    assert scores["retrieval"]["bm25"]["recall_at_5"] == 1.0
    assert scores["retrieval"]["bm25"]["mrr_at_5"] == 0.5
    assert scores["routing"]["routing_accuracy"] == 0.3333
    assert scores["routing"]["false_resume_rate_non_resume"] == 0.5
    assert scores["routing"]["correct_resume_rate"] == 1.0


def test_latency_summary():
    result = latency_summary([1.0, 2.0, 3.0, 4.0])
    assert result["p50_ms"] == 2.5
    assert result["p95_ms"] == 4.0
