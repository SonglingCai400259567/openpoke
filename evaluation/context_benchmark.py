"""V2 routing-context benchmark: saved Top-5 snapshot or fresh local retrieval.

Offline (stdlib only):
  python -m evaluation.context_benchmark --candidate-csv evaluation/results/v2_llm_holdout_gpt41mini.csv

Fresh 200/1000-workflow retrieval (needs OpenPoke + SentenceTransformer):
  python -m evaluation.context_benchmark --live --sizes 200 1000

Optional exact routing-section token counts: pip install tiktoken
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .run_workflow_eval import (
    DATASET_PATH,
    USER_ID,
    load_dataset,
    make_decoy,
    seed_corpus,
    stable_id,
)


def render_full_roster(corpus: list[dict]) -> str:
    """Same name-only XML roster shape used by the existing interaction agent."""
    contents = "\n".join(
        f'<agent name="{escape(w["title"], quote=True)}" />' for w in corpus
    ) or "None"
    return f"<active_agents>\n{contents}\n</active_agents>"


def render_top5(items: list[dict]) -> str:
    """Same workflow-candidate XML shape as preview-mode context injection."""
    contents = "\n".join(
        f'<workflow id="{escape(w["workflow_id"], quote=True)}" '
        f'title="{escape(w["title"], quote=True)}" '
        f'task_type="{escape(w["task_type"], quote=True)}">'
        f'<summary>{escape(w["summary"], quote=False)}</summary></workflow>'
        for w in items
    ) or "None"
    return f"<workflow_candidates>\n{contents}\n</workflow_candidates>"


def optional_token_encoder():
    """The GPT-4.1-family routing-section tokenizer; None if not installed."""
    try:
        import tiktoken
    except ImportError:
        return None
    return tiktoken.encoding_for_model("gpt-4.1-mini")


def extract_snapshot(csv_path: Path, corpus: list[dict], cases: list[dict]) -> list[dict]:
    """Reconstruct exact Top-5 from a saved V2 live-planner evaluation CSV."""
    by_id = {stable_id(w["key"]): {**w, "workflow_id": stable_id(w["key"])} for w in corpus}
    allowed_cases = {c["case_id"] for c in cases}
    rows = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["case_id"] not in allowed_cases:
                raise ValueError(f"Case {row['case_id']} is not in selected V2 dataset")
            if int(row["workflow_count"]) != len(corpus):
                raise ValueError("Snapshot workflow_count does not match V2 corpus size")
            identifiers = json.loads(row["candidate_workflow_ids"])
            if not isinstance(identifiers, list) or len(identifiers) > 5:
                raise ValueError("Invalid Top-K snapshot")
            try:
                candidates = [by_id[identifier] for identifier in identifiers]
            except KeyError as exc:
                raise ValueError(f"Candidate not found in V2 corpus: {exc}") from exc
            rows.append({"case_id": row["case_id"], "candidates": candidates})
    if not rows:
        raise ValueError("No V2 candidate rows found")
    if len({r["case_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate case IDs in CSV")
    return rows


def fresh_candidates(dataset: dict, size: int) -> tuple[list[dict], list[dict]]:
    """Perform real Hybrid Retrieval locally; never contacts OpenRouter/Gmail."""
    from server.workflows.store import WorkflowStore
    from server.workflows.dense import DenseWorkflowRetriever
    from server.workflows.hybrid import HybridWorkflowRetriever

    with TemporaryDirectory(prefix="openpoke_v2_context_") as directory:
        store = WorkflowStore(Path(directory) / "bench.sqlite")
        _, corpus = seed_corpus(store, dataset, size)
        dense = DenseWorkflowRetriever(store)
        hybrid = HybridWorkflowRetriever(store, dense, candidate_k=20, rrf_k=60)
        dense.refresh(USER_ID)
        output = []
        for case in dataset["cases"]:
            output.append({
                "case_id": case["case_id"],
                "candidates": hybrid.search(USER_ID, case["query"], top_k=5),
            })
        return corpus, output


def percentile(values: list[float], pct: int) -> float:
    if not values:
        raise ValueError("Empty sample")
    s = sorted(values)
    pos = max(0, (len(s) * pct + 99) // 100 - 1)
    return float(s[pos])


def measure_contexts(
    corpus: list[dict], case_candidates: list[dict], *,
    dataset_hash: str, source: str, split: str,
    encoder=None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    full_text = render_full_roster(corpus)
    full_chars = len(full_text)
    full_bytes = len(full_text.encode("utf-8"))
    full_tokens = len(encoder.encode(full_text)) if encoder else None
    details: list[dict[str, Any]] = []
    for case in case_candidates:
        top_text = render_top5(case["candidates"])
        top_chars = len(top_text)
        top_bytes = len(top_text.encode("utf-8"))
        top_tokens = len(encoder.encode(top_text)) if encoder else None
        details.append({
            "case_id": case["case_id"],
            "candidate_count": len(case["candidates"]),
            "full_roster_chars": full_chars,
            "top5_chars": top_chars,
            "char_reduction_pct": round((1 - top_chars / full_chars) * 100, 3),
            "full_roster_utf8_bytes": full_bytes,
            "top5_utf8_bytes": top_bytes,
            "full_roster_tokens": full_tokens,
            "top5_tokens": top_tokens,
            "token_reduction_pct": round((1 - top_tokens / full_tokens) * 100, 3)
            if full_tokens and top_tokens is not None else None,
        })
    top_chars = [r["top5_chars"] for r in details]
    top_bytes = [r["top5_utf8_bytes"] for r in details]
    top_tokens = [r["top5_tokens"] for r in details if r["top5_tokens"] is not None]
    summary = {
        "benchmark": "OpenPoke V2 routing-section context comparison",
        "source": source,
        "dataset_version": "v2.0",
        "split": split,
        "dataset_sha256": dataset_hash,
        "workflow_count": len(corpus),
        "query_count": len(details),
        "full_roster_chars": full_chars,
        "top5_chars_mean": round(statistics.mean(top_chars), 3),
        "top5_chars_p50": round(statistics.median(top_chars), 3),
        "top5_chars_p95": round(percentile(top_chars, 95), 3),
        "top5_chars_min": min(top_chars),
        "top5_chars_max": max(top_chars),
        "char_reduction_pct": round((1 - statistics.mean(top_chars) / full_chars) * 100, 3),
        "full_roster_utf8_bytes": full_bytes,
        "top5_utf8_bytes_mean": round(statistics.mean(top_bytes), 3),
        "tokenizer": "tiktoken / GPT-4.1-mini" if encoder else None,
        "full_roster_tokens": full_tokens,
        "top5_tokens_mean": round(statistics.mean(top_tokens), 3) if top_tokens else None,
        "token_reduction_pct": round((1 - statistics.mean(top_tokens) / full_tokens) * 100, 3)
        if full_tokens and top_tokens else None,
        "methodology": (
            "Compare original-style name-only full roster XML to workflow ID/title/type/summary Top-5 XML. "
            "Same synthetic V2 owned workflows and per-query retrieval candidates. "
            "Only the routing section is measured; not the full chat prompt or actual API billing."
        ),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    return summary, details


def write_outputs(output_dir: Path, summary: dict, rows: list[dict]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"v2_context_{summary['workflow_count']}_{summary['split']}"
    json_path = output_dir / f"{suffix}.json"
    csv_path = output_dir / f"{suffix}.csv"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/datasets/workflow_routing_v2_holdout.json"))
    parser.add_argument("--candidate-csv", type=Path,
                        default=Path("evaluation/results/v2_llm_holdout_gpt41mini.csv"))
    parser.add_argument("--live", action="store_true", help="Recompute Hybrid Top-5 locally")
    parser.add_argument("--sizes", type=int, nargs="+", default=[200])
    parser.add_argument("--require-tokens", action="store_true", help="Fail if tiktoken is not installed")
    parser.add_argument("--output", type=Path, default=Path("evaluation/results"))
    args = parser.parse_args()
    dataset, sha = load_dataset(args.dataset)
    encoder = optional_token_encoder()
    if args.require_tokens and encoder is None:
        parser.error("Install tiktoken in the openpoke environment: python -m pip install tiktoken")
    if args.live:
        for size in args.sizes:
            if size < len(dataset["workflows"]):
                parser.error("Size smaller than V2 corpus")
            corpus, candidates = fresh_candidates(dataset, size)
            report, rows = measure_contexts(
                corpus, candidates, dataset_hash=sha,
                source="fresh_local_hybrid_retrieval", split="all" if len(dataset['cases']) == 200 else "holdout_or_dev",
                encoder=encoder,
            )
            json_path, csv_path = write_outputs(args.output, report, rows)
            print(f"{size} workflows: {report['full_roster_chars']} -> {report['top5_chars_mean']} chars "
                  f"({report['char_reduction_pct']}% reduction)")
            print(f"JSON {json_path} | CSV {csv_path}")
    else:
        corpus = dataset["workflows"]
        candidates = extract_snapshot(args.candidate_csv, corpus, dataset["cases"])
        source_hash = hashlib.sha256(args.candidate_csv.read_bytes()).hexdigest()
        split = "holdout" if len(dataset["cases"]) == 160 else "selected"
        report, rows = measure_contexts(
            corpus, candidates, dataset_hash=sha,
            source=f"saved_live_planner_candidate_csv_sha256:{source_hash}",
            split=split, encoder=encoder,
        )
        json_path, csv_path = write_outputs(args.output, report, rows)
        print(f"{len(corpus)} workflows, {len(rows)} V2 queries: "
              f"{report['full_roster_chars']} -> {report['top5_chars_mean']} chars "
              f"({report['char_reduction_pct']}% reduction)")
        if report["token_reduction_pct"] is None:
            print("Exact token count unavailable: python -m pip install tiktoken, then rerun")
        else:
            print(f"Token comparison: {report['full_roster_tokens']} -> "
                  f"{report['top5_tokens_mean']} tokens "
                  f"({report['token_reduction_pct']}% reduction)")
        print(f"JSON {json_path} | CSV {csv_path}")


if __name__ == "__main__":
    main()
