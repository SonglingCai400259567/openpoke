"""Evaluate rule-based vs LLM Planner+Validator on the SAME V2 synthetic corpus.

Run from OpenPoke repository root (real OpenRouter API calls / charges):
    python -m evaluation.run_llm_planner_eval --sizes 200 --limit 3
    python -m evaluation.run_llm_planner_eval --sizes 200

Requires the optional intent_hint argument in LLMPlannerResolver.resolve(),
as documented in the accompanying assistant instructions.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .metrics import latency_summary
from .run_workflow_eval import (
    DATASET_PATH,
    USER_ID,
    commit_id,
    load_dataset,
    seed_corpus,
)


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def routing_metrics(rows: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    """Correct action AND exact workflow ID for RESUME; safe for small subsets."""
    n = len(rows)
    gold_resume = [r for r in rows if r["expected_action"] == "RESUME"]
    gold_non_resume = [r for r in rows if r["expected_action"] != "RESUME"]
    def correct(r: dict) -> bool:
        return (
            r[f"{prefix}_action"] == r["expected_action"]
            and (
                r["expected_action"] != "RESUME"
                or r[f"{prefix}_workflow_id"] == r["gold_workflow_id"]
            )
        )
    return {
        "evaluated_cases": n,
        "routing_accuracy": ratio(sum(map(correct, rows)), n),
        "correct_resume_rate": ratio(
            sum(correct(r) for r in gold_resume), len(gold_resume)
        ),
        "false_resume_rate_non_resume": ratio(
            sum(r[f"{prefix}_action"] == "RESUME" for r in gold_non_resume),
            len(gold_non_resume),
        ),
        "wrong_resume_count_all": sum(
            r[f"{prefix}_action"] == "RESUME"
            and (
                r["expected_action"] != "RESUME"
                or r[f"{prefix}_workflow_id"] != r["gold_workflow_id"]
            )
            for r in rows
        ),
        "clarify_instead_of_resume_count": sum(
            r[f"{prefix}_action"] == "CLARIFY" for r in gold_resume
        ),
        "action_counts": {
            a: sum(r[f"{prefix}_action"] == a for r in rows)
            for a in ("RESUME", "CREATE", "CLARIFY")
        },
    }


def write_outputs(path: Path, report: dict, rows: list[dict]) -> tuple[Path, Path]:
    path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"llm_planner_eval_{timestamp}"
    json_path, csv_path = path / f"{stem}.json", path / f"{stem}.csv"
    suffix = 2
    while json_path.exists() or csv_path.exists():
        json_path = path / f"{stem}_{suffix}.json"
        csv_path = path / f"{stem}_{suffix}.csv"
        suffix += 1
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                    for k, v in row.items()
                })
    return json_path, csv_path


async def evaluate_scale(
    *, dataset: dict, size: int, cases: list[dict],
    model: str | None, timeout_seconds: float,
) -> tuple[dict, list[dict]]:
    # Delayed imports: importing this script to run pure metrics tests does not load torch.
    from server.workflows.store import WorkflowStore
    from server.workflows.dense import DenseWorkflowRetriever
    from server.workflows.hybrid import HybridWorkflowRetriever
    from server.workflows.resolver import WorkflowResolver
    from server.workflows.llm_planner import OpenRouterPlannerClient, LLMPlannerResolver

    with TemporaryDirectory(prefix=f"openpoke_llm_eval_{size}_") as temp:
        store = WorkflowStore(Path(temp) / "bench.sqlite")
        id_by_key, _ = seed_corpus(store, dataset, size)
        dense = DenseWorkflowRetriever(store)
        hybrid = HybridWorkflowRetriever(store, dense, candidate_k=20, rrf_k=60)
        rule_resolver = WorkflowResolver(store, hybrid)
        planner_client = OpenRouterPlannerClient(
            model=model, timeout_seconds=timeout_seconds
        )
        llm_resolver = LLMPlannerResolver(
            store, hybrid, planner_client, top_k=5, raise_on_error=True
        )

        started_index = time.perf_counter()
        indexed = dense.refresh(USER_ID)
        index_seconds = time.perf_counter() - started_index
        if indexed != size:
            raise AssertionError(f"Expected {size} vectors, got {indexed}")

        rows: list[dict] = []
        retrieval_ms: list[float] = []
        rule_ms: list[float] = []
        planner_ms: list[float] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        usage_recorded = 0
        planner_failures = 0

        for i, case in enumerate(cases, start=1):
            query = case["query"]
            start = time.perf_counter()
            candidates = hybrid.search(USER_ID, query, top_k=5)
            retrieval_ms.append((time.perf_counter() - start) * 1000)
            candidate_ids = [c["workflow_id"] for c in candidates]
            gold_id = id_by_key.get(case["target_key"]) if case["target_key"] else None

            start = time.perf_counter()
            rule_decision = rule_resolver.resolve(
                user_id=USER_ID,
                query=query,
                intent=case["intent"],
                entity_hints=case["entity_hints"],
                task_type_hint=case["task_type_hint"],
                top_k=5,
            )
            rule_ms.append((time.perf_counter() - start) * 1000)

            # Reset per-call measurements so a failed request never reuses old usage.
            planner_client.last_usage = None
            planner_client.last_latency_ms = None
            start = time.perf_counter()
            llm_decision = await llm_resolver.resolve(
                user_id=USER_ID,
                query=query,
                intent_hint=case["intent"],
                entity_hints=case["entity_hints"],
                task_type_hint=case["task_type_hint"],
                precomputed_candidates=candidates,
                explicit_new=False,
            )
            planner_ms.append((time.perf_counter() - start) * 1000)
            usage = planner_client.last_usage
            if isinstance(usage, dict):
                try:
                    total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
                    total_completion_tokens += int(usage.get("completion_tokens") or 0)
                    if "prompt_tokens" in usage or "completion_tokens" in usage:
                        usage_recorded += 1
                except (TypeError, ValueError):
                    pass
            if "Planner unavailable" in llm_decision.reason:
                planner_failures += 1

            row = {
                "workflow_count": size,
                "case_id": case["case_id"],
                "group": case["group"],
                "query": query,
                "expected_action": case["expected_action"],
                "gold_workflow_id": gold_id,
                "candidate_workflow_ids": candidate_ids,
                "gold_in_top5": gold_id in candidate_ids if gold_id else None,
                "rule_action": rule_decision.action,
                "rule_workflow_id": rule_decision.workflow_id,
                "rule_reason": rule_decision.reason,
                "llm_action": llm_decision.action,
                "llm_workflow_id": llm_decision.workflow_id,
                "llm_reason": llm_decision.reason,
                "retrieval_ms": round(retrieval_ms[-1], 2),
                "rule_total_ms": round(rule_ms[-1], 2),
                "llm_resolution_ms": round(planner_ms[-1], 2),
                "provider_prompt_tokens": usage.get("prompt_tokens") if isinstance(usage, dict) else None,
                "provider_completion_tokens": usage.get("completion_tokens") if isinstance(usage, dict) else None,
            }
            for name in ("rule", "llm"):
                row[f"{name}_correct"] = (
                    row[f"{name}_action"] == row["expected_action"]
                    and (
                        row["expected_action"] != "RESUME"
                        or row[f"{name}_workflow_id"] == gold_id
                    )
                )
            rows.append(row)
            print(
                f"[{size:>4}] {i:>2}/{len(cases)} {case['case_id']}: "
                f"gold={case['expected_action']:7} rule={rule_decision.action:7} "
                f"llm={llm_decision.action:7} correct={row['llm_correct']}",
                flush=True,
            )

        summary = {
            "workflow_count": size,
            "case_count": len(rows),
            "indexed_workflows": indexed,
            "index_build_seconds": round(index_seconds, 3),
            "rule": routing_metrics(rows, "rule"),
            "llm_planner_validator": routing_metrics(rows, "llm"),
            "latency": {
                "hybrid_retrieval": latency_summary(retrieval_ms),
                "rule_including_own_retrieval": latency_summary(rule_ms),
                "llm_resolver_using_precomputed_candidates": latency_summary(planner_ms),
            },
            "provider_usage": {
                "calls_with_token_usage": usage_recorded,
                "prompt_tokens_total_reported": total_prompt_tokens if usage_recorded else None,
                "completion_tokens_total_reported": total_completion_tokens if usage_recorded else None,
                "planner_fallback_count": planner_failures,
            },
        }
        return summary, rows


async def async_main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[200])
    parser.add_argument("--limit", type=int, default=None,
                        help="First N cases; for connectivity smoke test only")
    parser.add_argument("--case-ids", nargs="+", default=None,
                        help="Specific case IDs, e.g. R13 C10 A01")
    parser.add_argument("--model", default=None,
                        help="OpenRouter model ID; default from project settings")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--dataset", type=Path,
        default=Path("evaluation/datasets/workflow_routing_v2_holdout.json")
    )
    parser.add_argument("--output", type=Path, default=Path("evaluation/results"))
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    dataset, sha256 = load_dataset(args.dataset)
    cases = dataset["cases"]
    if args.case_ids:
        requested = set(args.case_ids)
        cases = [c for c in cases if c["case_id"] in requested]
        missing = requested - {c["case_id"] for c in cases}
        if missing:
            parser.error(f"Unknown case IDs: {sorted(missing)}")
    if args.limit is not None:
        cases = cases[:args.limit]
    if not cases:
        parser.error("No cases selected")
    if any(n < len(dataset["workflows"]) for n in args.sizes):
        parser.error(f"All sizes must be >= {len(dataset['workflows'])}")

    # Fail before embedding/index work if a live LLM request cannot be made.
    from server.config import get_settings
    if not get_settings().openrouter_api_key:
        parser.error("OPENROUTER_API_KEY is not configured for live planner evaluation")

    print(f"Dataset hash {sha256[:12]}, cases={len(cases)}, sizes={args.sizes}")
    print("LIVE OPENROUTER ROUTING CALLS: API usage/charges apply. Gmail is NOT invoked.")
    print("Oracle intent/entity/type hints supplied equally to both routing approaches.")
    summaries, rows = [], []
    for size in args.sizes:
        summary, details = await evaluate_scale(
            dataset=dataset, size=size, cases=cases,
            model=args.model, timeout_seconds=args.timeout,
        )
        summaries.append(summary)
        rows.extend(details)
        print(f"Scale {size}: rule={summary['rule']['routing_accuracy']} "
              f"LLM={summary['llm_planner_validator']['routing_accuracy']} "
              f"LLM p50={summary['latency']['llm_resolver_using_precomputed_candidates']['p50_ms']} ms")

    report = {
        "benchmark": "OpenPoke LLM Planner + Validator vs Rule-based Resolver",
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": sha256,
        "dataset_file": str(args.dataset),
        "label_scope": "internal OpenPoke workflows",
        "cases": [c["case_id"] for c in cases],
        "git_commit": commit_id(),
        "model": args.model or "project interaction_agent_model",
        "conditions": {
            "oracle_intent_entity_type_hints": True,
            "same_corpus_same_hybrid_top5": True,
            "external_actions_executed": False,
            "execution_runtime_tested": False,
            "end_to_end_nlu_tested": False,
            "live_openrouter_requests": True,
        },
        "limitations": [
            "Synthetic V2 cases; not representative traffic or independently blind-annotated",
            "Planner uses oracle intent/entity/type hints; natural-language extraction is not evaluated",
            "Rule resolver includes its own retrieval in latency; planner latency excludes retrieval",
            "Model/provider usage is recorded only if available in API response",
            "Use the 160-case V2 holdout for meaningful category coverage; short smoke tests are not representative",
        ],
        "scales": summaries,
    }
    json_path, csv_path = write_outputs(args.output, report, rows)
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
