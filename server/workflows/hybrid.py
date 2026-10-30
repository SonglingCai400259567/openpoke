
from typing import Any

from .store import WorkflowStore
from .dense import DenseWorkflowRetriever


def rrf_fuse(
    rankings: dict[str, list[dict[str, Any]]],
    top_k: int = 5,
    rrf_k: int = 60
) -> list[dict[str, Any]]:
    """Fuse retrieval rankings using Reciprocal Rank Fusion."""

    if top_k < 1:
        raise ValueError("top_k must be positive")

    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused = {}

    for source, results in rankings.items():
        for rank, item in enumerate(results, start=1):
            workflow_id = item["workflow_id"]

            if workflow_id not in fused:
                fused[workflow_id] = {
                    "workflow_id": workflow_id,
                    "title": item["title"],
                    "summary": item["summary"],
                    "task_type": item["task_type"],
                    "status": item["status"],
                    "rrf_score": 0.0,
                    "source_ranks": {}
                }

            fused[workflow_id]["rrf_score"] += (
                1.0 / (rrf_k + rank)
            )

            fused[workflow_id]["source_ranks"][source] = rank

    ranked = sorted(
        fused.values(),
        key=lambda item: (
            -item["rrf_score"],
            item["workflow_id"]
        )
    )

    return ranked[:top_k]


class HybridWorkflowRetriever:

    def __init__(
        self,
        store: WorkflowStore,
        dense: DenseWorkflowRetriever,
        candidate_k: int = 20,
        rrf_k: int = 60
    ):
        if not 1 <= candidate_k <= 20:
            raise ValueError("candidate_k must be 1..20")

        self.store = store
        self.dense = dense
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5
    ) -> list[dict[str, Any]]:

        if not 1 <= top_k <= self.candidate_k:
            raise ValueError("Invalid top_k")

        if not query.strip():
            return []

        bm25_results = self.store.search_workflows(
            user_id=user_id,
            query=query,
            top_k=self.candidate_k
        )

        dense_results = self.dense.search(
            user_id=user_id,
            query=query,
            top_k=self.candidate_k
        )

        return rrf_fuse(
            rankings={
                "bm25": bm25_results,
                "dense": dense_results
            },
            top_k=top_k,
            rrf_k=self.rrf_k
        )
