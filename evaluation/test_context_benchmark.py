"""Pure context-metric tests (no model, API, or tool side effects)."""
import csv
import json
from pathlib import Path

from .context_benchmark import (
    extract_snapshot, measure_contexts, render_full_roster, render_top5
)
from .run_workflow_eval import stable_id


def test_xml_encoding_and_bounded_topk():
    w = {"workflow_id": stable_id("tiny"), "title": 'A&B "Quote"',
         "task_type": "email", "summary": "<awaiting reply>"}
    assert "A&amp;B &quot;Quote&quot;" in render_full_roster([w])
    assert "&lt;awaiting reply&gt;" in render_top5([w])
    assert "<workflow_candidates>" in render_top5([])


def test_context_calculations_without_tokenizer():
    corpus = [{"key": "a", "title": "Alice Task", "summary": "Check reply", "task_type": "email"},
              {"key": "b", "title": "Bob Task", "summary": "Review report", "task_type": "research"}]
    candidates = [{"case_id": "Q1", "candidates": [{"workflow_id": stable_id("a"), **corpus[0]}]}]
    report, rows = measure_contexts(corpus, candidates, dataset_hash="test", source="test", split="test")
    assert report["workflow_count"] == 2
    assert rows[0]["full_roster_chars"] == len(render_full_roster(corpus))
    assert rows[0]["top5_chars"] == len(render_top5(candidates[0]["candidates"]))
    assert report["token_reduction_pct"] is None


def test_v2_holdout_snapshot_matches_160_cases():
    base = Path(__file__).parent
    data = json.loads((base / 'datasets/workflow_routing_v2_holdout.json').read_text(encoding='utf-8'))
    snapshot = base / 'results/v2_llm_holdout_gpt41mini.csv'
    if not snapshot.exists():
        return
    entries = extract_snapshot(snapshot, data['workflows'], data['cases'])
    assert len(entries) == 160
    assert all(len(entry['candidates']) == 5 for entry in entries)
