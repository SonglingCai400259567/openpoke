"""Pure benchmark metrics; no dependency on OpenPoke or embedding models."""
from __future__ import annotations

from math import ceil
from statistics import median
from typing import Any


def latency_summary(values_ms: list[float]) -> dict[str, float]:
    if not values_ms:
        return {"p50_ms": 0.0, "p95_ms": 0.0, "mean_ms": 0.0}
    sorted_values = sorted(values_ms)
    p95_index = max(0, ceil(len(sorted_values) * 0.95) - 1)
    return {
        "p50_ms": round(median(sorted_values), 3),
        "p95_ms": round(sorted_values[p95_index], 3),
        "mean_ms": round(sum(values_ms) / len(values_ms), 3),
    }


def summarize_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rows have oracle-labeled gold IDs, ranked IDs and actual decisions."""
    if not rows:
        raise ValueError("Evaluation requires at least one labeled case")

    n = len(rows)
    resume_rows = [r for r in rows if r["expected_action"] == "RESUME"]
    non_resume_rows = [r for r in rows if r["expected_action"] != "RESUME"]
    assert resume_rows, "Dataset must have resume examples"
    assert non_resume_rows, "Dataset must have non-resume examples"

    retrieval = {}
    for method in ("bm25", "dense", "hybrid"):
        ids_key = f"{method}_ids"
        hit1 = hit5 = 0
        rr_sum = 0.0
        for r in resume_rows:
            ranked_ids = r[ids_key]
            target = r["gold_workflow_id"]
            if target in ranked_ids[:1]:
                hit1 += 1
            if target in ranked_ids[:5]:
                hit5 += 1
                rr_sum += 1.0 / (ranked_ids[:5].index(target) + 1)
        denominator = len(resume_rows)
        retrieval[method] = {
            "recall_at_1": round(hit1 / denominator, 4),
            "recall_at_5": round(hit5 / denominator, 4),
            "mrr_at_5": round(rr_sum / denominator, 4),
            "evaluated_resume_queries": denominator,
        }

    correct_action = sum(r["predicted_action"] == r["expected_action"] for r in rows)
    correct_full = sum(
        r["predicted_action"] == r["expected_action"]
        and (
            r["expected_action"] != "RESUME"
            or r["predicted_workflow_id"] == r["gold_workflow_id"]
        )
        for r in rows
    )
    false_resume_non_resume = sum(
        r["predicted_action"] == "RESUME" for r in non_resume_rows
    )
    wrong_resume_any = sum(
        r["predicted_action"] == "RESUME"
        and (
            r["expected_action"] != "RESUME"
            or r["predicted_workflow_id"] != r["gold_workflow_id"]
        )
        for r in rows
    )
    correct_resume = sum(
        r["predicted_action"] == "RESUME"
        and r["predicted_workflow_id"] == r["gold_workflow_id"]
        for r in resume_rows
    )
    clarify_instead_of_resume = sum(
        r["predicted_action"] == "CLARIFY" for r in resume_rows
    )
    create_instead_of_resume = sum(
        r["predicted_action"] == "CREATE" for r in resume_rows
    )

    routing = {
        "total_queries": n,
        "action_accuracy": round(correct_action / n, 4),
        "routing_accuracy": round(correct_full / n, 4),
        "correct_resume_rate": round(correct_resume / len(resume_rows), 4),
        "false_resume_rate_non_resume": round(false_resume_non_resume / len(non_resume_rows), 4),
        "wrong_resume_count_all": wrong_resume_any,
        "clarify_instead_of_resume_rate": round(clarify_instead_of_resume / len(resume_rows), 4),
        "create_instead_of_resume_rate": round(create_instead_of_resume / len(resume_rows), 4),
        "decision_counts": {
            action: sum(r["predicted_action"] == action for r in rows)
            for action in ("RESUME", "CREATE", "CLARIFY")
        },
        "gold_counts": {
            action: sum(r["expected_action"] == action for r in rows)
            for action in ("RESUME", "CREATE", "CLARIFY")
        },
    }
    return {"retrieval": retrieval, "routing": routing}
