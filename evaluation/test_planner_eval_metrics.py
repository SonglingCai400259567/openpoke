"""Pure evaluator metric tests: no OpenRouter or embedding model required."""
from .run_llm_planner_eval import routing_metrics


def test_perfect_planner_and_imperfect_rule():
    rows = [
        {
            "expected_action": "RESUME", "gold_workflow_id": "W1",
            "rule_action": "RESUME", "rule_workflow_id": "W1",
            "llm_action": "RESUME", "llm_workflow_id": "W1",
        },
        {
            "expected_action": "CREATE", "gold_workflow_id": None,
            "rule_action": "CLARIFY", "rule_workflow_id": None,
            "llm_action": "CREATE", "llm_workflow_id": None,
        },
        {
            "expected_action": "CLARIFY", "gold_workflow_id": None,
            "rule_action": "RESUME", "rule_workflow_id": "W1",
            "llm_action": "CLARIFY", "llm_workflow_id": None,
        },
    ]
    r = routing_metrics(rows, "rule")
    l = routing_metrics(rows, "llm")
    assert r["routing_accuracy"] == 0.3333
    assert r["false_resume_rate_non_resume"] == 0.5
    assert l["routing_accuracy"] == 1.0
    assert l["false_resume_rate_non_resume"] == 0.0


def test_partial_dataset_without_non_resume():
    rows = [{
        "expected_action": "RESUME", "gold_workflow_id": "W1",
        "rule_action": "CLARIFY", "rule_workflow_id": None,
        "llm_action": "RESUME", "llm_workflow_id": "W1",
    }]
    r = routing_metrics(rows, "rule")
    assert r["routing_accuracy"] == 0.0
    assert r["false_resume_rate_non_resume"] is None


def test_wrong_target_resume():
    rows = [{
        "expected_action": "RESUME", "gold_workflow_id": "W1",
        "rule_action": "RESUME", "rule_workflow_id": "W2",
        "llm_action": "RESUME", "llm_workflow_id": "W1",
    }]
    r = routing_metrics(rows, "rule")
    assert r["wrong_resume_count_all"] == 1
    assert r["routing_accuracy"] == 0.0
