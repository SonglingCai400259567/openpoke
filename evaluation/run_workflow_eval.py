"""Run the OpenPoke V2 workflow retrieval and rule-routing benchmark.

Run from OpenPoke repository root:
    python -m evaluation.run_workflow_eval --sizes 200 1000
    python -m evaluation.run_workflow_eval --dataset evaluation/datasets/workflow_routing_v2_holdout.json --sizes 200
No Gmail/OpenRouter calls. Initial embedding model download may require internet access.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .metrics import latency_summary, summarize_quality

USER_ID = "synthetic_eval_user"
OTHER_USER_ID = "synthetic_other_user"
DATASET_PATH = Path(__file__).parent / "datasets" / "workflow_routing_v2_200.json"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FIXTURE_NAMESPACE = uuid.UUID("8671f413-ec3b-43e7-a9f5-e65489a42923")


def stable_id(key: str) -> str:
    """Stable UUIDs avoid random tie-breaking across repeated evaluations."""
    return str(uuid.uuid5(FIXTURE_NAMESPACE, key))


def load_dataset(path: Path = DATASET_PATH) -> tuple[dict, str]:
    raw = path.read_bytes()
    dataset = json.loads(raw.decode("utf-8"))
    return dataset, hashlib.sha256(raw).hexdigest()


def make_decoy(index: int) -> dict:
    """Deterministic hard negatives, including same-contact related workflows."""
    contacts = ["Alice", "Bob", "Carol", "David", "Emily", "Frank", "Grace", "Henry"]
    topics = [
        ("email", "vehicle insurance quote", "car insurance premium and claim coverage"),
        ("email", "home insurance renewal", "residential policy quote and annual coverage"),
        ("calendar", "contract meeting", "schedule a negotiation and follow-up meeting"),
        ("research", "air travel monitoring", "check flight details, arrival and delay"),
        ("research", "weekly AI research report", "summarize new papers for a research project"),
        ("email", "invoice follow-up", "request the receipt for an outstanding invoice"),
    ]
    contact = contacts[index % len(contacts)]
    task_type, topic, description = topics[index % len(topics)]
    return {
        "key": f"decoy_{index:05d}",
        "title": f"{contact} {topic} {index:05d}",
        "task_type": task_type,
        "summary": f"Follow up with {contact} about {description} for CASE-{index:05d}",
        "entities": {"contact": contact, "case_id": f"CASE-{index:05d}"},
    }


def seed_corpus(store: Any, dataset: dict, size: int) -> tuple[dict[str, str], list[dict]]:
    """Insert deterministic benchmark fixtures directly; not a production write path."""
    base = dataset["workflows"]
    if size < len(base):
        raise ValueError(f"size must be >= {len(base)}")
    corpus = base + [make_decoy(i) for i in range(size - len(base))]
    keys = [w["key"] for w in corpus]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate fixture keys")

    id_by_key = {w["key"]: stable_id(w["key"]) for w in corpus}
    timestamp = "2026-10-01T00:00:00+00:00"
    rows = [
        (
            id_by_key[w["key"]], USER_ID, w["title"], w["task_type"],
            w["summary"], "active", json.dumps({"entities": w["entities"]}),
            timestamp, timestamp,
        )
        for w in corpus
    ]

    # Deliberate cross-user near-duplicate; omitted from size and inaccessible to USER_ID.
    rows.append((
        stable_id("private_alice"), OTHER_USER_ID, "Alice Auto Insurance Quote",
        "email", "Follow up on private Alice auto insurance quote AUTO-101",
        "active", json.dumps({"entities": {"contact": "PrivateUser", "case_id": "AUTO-101"}}),
        timestamp, timestamp,
    ))

    with store._connection() as conn:
        conn.executemany(
            """INSERT INTO workflows (
                   workflow_id, user_id, title, task_type, summary,
                   status, context_json, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return id_by_key, corpus


def legacy_roster_chars(corpus: list[dict]) -> int:
    """Length of original-style name-only roster section, not API tokens."""
    roster = "\n".join(
        f'<agent name="{escape(w["title"], quote=True)}" />' for w in corpus
    )
    return len(f"<active_agents>\n{roster}\n</active_agents>")


def topk_context_chars(items: list[dict]) -> int:
    """Length of proposed workflow-candidate XML section, not API tokens."""
    rendered = "\n".join(
        f'<workflow id="{escape(w["workflow_id"], quote=True)}" '
        f'title="{escape(w["title"], quote=True)}" '
        f'task_type="{escape(w["task_type"], quote=True)}">'
        f'<summary>{escape(w["summary"], quote=False)}</summary></workflow>'
        for w in items
    ) or "None"
    return len(f"<workflow_candidates>\n{rendered}\n</workflow_candidates>")


def commit_id() -> str | None:
    try:
        repo_root = Path(__file__).resolve().parent.parent
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, capture_output=True, text=True,
            check=True, timeout=3,
        )
        return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def run_scale(dataset: dict, size: int, model_name: str) -> tuple[dict, list[dict]]:
    # Import only here, so pure metrics tests don't require torch/model packages.
    from server.workflows.store import WorkflowStore
    from server.workflows.dense import DenseWorkflowRetriever
    from server.workflows.hybrid import HybridWorkflowRetriever
    from server.workflows.resolver import WorkflowResolver

    with TemporaryDirectory(prefix=f"openpoke_eval_{size}_") as directory:
        store = WorkflowStore(Path(directory) / "benchmark.sqlite")
        id_by_key, corpus = seed_corpus(store, dataset, size)
        dense = DenseWorkflowRetriever(store, model_name=model_name)
        hybrid = HybridWorkflowRetriever(store, dense, candidate_k=20, rrf_k=60)
        resolver = WorkflowResolver(store, hybrid)

        start_index = time.perf_counter()
        encoded = dense.refresh(USER_ID)
        index_seconds = time.perf_counter() - start_index
        if encoded != size:
            raise AssertionError(f"Expected {size} indexed vectors, got {encoded}")

        # Isolation self-check before scoring; private exact-title match must not leak.
        assert all(
            r["workflow_id"] != stable_id("private_alice")
            for r in hybrid.search(USER_ID, "Alice Auto Insurance Quote", top_k=5)
        ), "Cross-user leak detected"

        details = []
        latencies: dict[str, list[float]] = {
            "bm25": [], "dense": [], "hybrid": [], "resolver": []
        }
        topk_lengths = []
        for case in dataset["cases"]:
            query = case["query"]
            rankings: dict[str, list[dict]] = {}
            for method, search in (
                ("bm25", lambda: store.search_workflows(USER_ID, query, top_k=5)),
                ("dense", lambda: dense.search(USER_ID, query, top_k=5)),
                ("hybrid", lambda: hybrid.search(USER_ID, query, top_k=5)),
            ):
                start = time.perf_counter()
                rankings[method] = search()
                latencies[method].append((time.perf_counter() - start) * 1000)

            start = time.perf_counter()
            decision = resolver.resolve(
                user_id=USER_ID, query=query, intent=case["intent"],
                entity_hints=case["entity_hints"],
                task_type_hint=case["task_type_hint"], top_k=5,
            )
            latencies["resolver"].append((time.perf_counter() - start) * 1000)
            topk_lengths.append(topk_context_chars(rankings["hybrid"]))

            gold_id = id_by_key.get(case["target_key"]) if case["target_key"] else None
            if case["expected_action"] == "RESUME" and gold_id is None:
                raise ValueError(f"Unresolved gold target for {case['case_id']}")
            details.append({
                "case_id": case["case_id"], "group": case["group"],
                "query": query, "intent": case["intent"],
                "expected_action": case["expected_action"],
                "gold_workflow_id": gold_id,
                "predicted_action": decision.action,
                "predicted_workflow_id": decision.workflow_id,
                "decision_reason": decision.reason,
                "bm25_ids": [x["workflow_id"] for x in rankings["bm25"]],
                "dense_ids": [x["workflow_id"] for x in rankings["dense"]],
                "hybrid_ids": [x["workflow_id"] for x in rankings["hybrid"]],
            })

        quality = summarize_quality(details)
        routing = quality["routing"]
        for detail in details:
            detail["correct"] = (
                detail["predicted_action"] == detail["expected_action"]
                and (
                    detail["expected_action"] != "RESUME"
                    or detail["predicted_workflow_id"] == detail["gold_workflow_id"]
                )
            )

        summary = {
            "workflow_count": size,
            "index_build_seconds": round(index_seconds, 3),
            "indexed_workflows": encoded,
            "retrieval": quality["retrieval"],
            "routing": routing,
            "latency": {name: latency_summary(samples) for name, samples in latencies.items()},
            "context": {
                "legacy_full_roster_chars": legacy_roster_chars(corpus),
                "workflow_top5_chars_mean": round(sum(topk_lengths) / len(topk_lengths), 1),
                "measurement": "routing-section character count only; NOT tokens, LLM latency, or full prompts",
            },
        }
        return summary, details


def write_results(result_dir: Path, summary: dict, details: list[dict]) -> tuple[Path, Path]:
    result_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = result_dir / f"workflow_eval_{stamp}.json"
    csv_path = result_dir / f"workflow_eval_{stamp}.csv"
    # Make same-second repeat runs safe instead of silently overwriting.
    suffix = 2
    while json_path.exists() or csv_path.exists():
        json_path = result_dir / f"workflow_eval_{stamp}_{suffix}.json"
        csv_path = result_dir / f"workflow_eval_{stamp}_{suffix}.csv"
        suffix += 1
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if details:
        columns = ["workflow_count", *[k for k in details[0] if k != "workflow_count"]]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            for detail in details:
                writer.writerow({
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                    for k, v in detail.items()
                })
    return json_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH, help="V2 dataset JSON, full/dev/holdout")
    parser.add_argument("--sizes", nargs="+", type=int, default=[200], help="Number of user workflows per scale, e.g. 10 100 500 1000")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="SentenceTransformer embedding model name")
    parser.add_argument("--output", type=Path, default=Path("evaluation/results"))
    args = parser.parse_args()

    dataset, dataset_hash = load_dataset(args.dataset)
    if any(size < len(dataset["workflows"]) for size in args.sizes):
        parser.error(f"All --sizes must be >= {len(dataset['workflows'])} base workflows")
    print(f"Dataset {dataset['dataset_version']} | {len(dataset['cases'])} labeled queries | SHA256 {dataset_hash[:12]}")
    print("No Gmail or OpenRouter calls. Initial model download may require internet access.")

    summaries = []
    all_details = []
    for size in args.sizes:
        print(f"\n=== Scale: {size} workflows ===", flush=True)
        summary, details = run_scale(dataset, size, args.model)
        summaries.append(summary)
        for detail in details:
            all_details.append({"workflow_count": size, **detail})
        print(f"Index: {summary['index_build_seconds']} s")
        for method in ("bm25", "dense", "hybrid"):
            metric = summary["retrieval"][method]
            latency = summary["latency"][method]
            print(f"{method:>6}: R@1={metric['recall_at_1']:.3f} R@5={metric['recall_at_5']:.3f} "
                  f"MRR@5={metric['mrr_at_5']:.3f} p50={latency['p50_ms']:.1f}ms")
        route = summary["routing"]
        print(f"Resolver: routing_acc={route['routing_accuracy']:.3f} "
              f"false_resume={route['false_resume_rate_non_resume']:.3f} "
              f"correct_resume={route['correct_resume_rate']:.3f}")
        print(f"Routing-section chars: full-roster={summary['context']['legacy_full_roster_chars']} "
              f"top5-avg={summary['context']['workflow_top5_chars_mean']}")

    report = {
        "benchmark": "OpenPoke V2 workflow retrieval and oracle-NLU routing",
        "label_scope": "internal OpenPoke workflows",
        "dataset_file": str(args.dataset),
        "dataset_version": dataset["dataset_version"],
        "dataset_sha256": dataset_hash,
        "query_count": len(dataset["cases"]),
        "model_name": args.model,
        "top_k": 5,
        "hybrid_candidate_k": 20,
        "rrf_k": 60,
        "git_commit": commit_id(),
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "Synthetic labels; not real user distribution or blinded human evaluation",
            "Intent/entity hints are oracle annotations; LLM extraction not evaluated",
            "No original full-roster LLM routing baseline; roster is a name-only character-count proxy",
            "Latency is local warm-cache retrieval; no OpenRouter latency or API token measurement",
            "Corpus generation is deterministic, but first model download and machine load can affect timing",
        ],
        "scales": summaries,
    }
    json_path, csv_path = write_results(args.output, report, all_details)
    print(f"\nWrote JSON: {json_path}")
    print(f"Wrote per-case CSV: {csv_path}")


if __name__ == "__main__":
    main()
