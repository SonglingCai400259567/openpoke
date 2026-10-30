
import os
from functools import lru_cache
from pathlib import Path

from .store import WorkflowStore
from .dense import DenseWorkflowRetriever
from .hybrid import HybridWorkflowRetriever
from .resolver import WorkflowResolver

from .llm_planner import (
    LLMPlannerResolver,
    OpenRouterPlannerClient,
)

# Temporary single-user identity for local demonstration.
# Replace with an authenticated user ID before multi-user use.
PREVIEW_USER_ID = "local_demo"


def preview_mode() -> bool:
    mode = os.getenv(
        "OPENPOKE_ORCHESTRATION_MODE", "legacy"
    ).strip().lower()

    return mode in {"preview", "workflow_demo", "workflow_live"}


@lru_cache(maxsize=4)
def _build_components(db_path: str):
    store = WorkflowStore(db_path)
    dense = DenseWorkflowRetriever(store)
    hybrid = HybridWorkflowRetriever(store, dense)
    resolver = WorkflowResolver(store, hybrid)
    return store, hybrid, resolver, dense


def get_components(*, include_dense: bool = False):
    configured_path = os.getenv("OPENPOKE_WORKFLOW_DB")

    db_path = (
        Path(configured_path)
        if configured_path
        else Path(__file__).resolve().parent.parent
             / "data" / "workflow_registry.sqlite"
    )

    components = _build_components(str(db_path.resolve()))
    # Keep original three-item return for existing callers.
    return components if include_dense else components[:3]


def retrieve_candidates(query: str) -> list[dict]:
    _, retriever, _ = get_components()

    return retriever.search(
        user_id=PREVIEW_USER_ID,
        query=query,
        top_k=5
    )


def resolve_request(
    query: str,
    intent: str,
    entity_hints: dict | None = None,
    task_type_hint: str | None = None
) -> dict:
    _, _, resolver = get_components()

    if entity_hints is not None:
        if not isinstance(entity_hints, dict):
            raise ValueError("entity_hints must be an object")

        if not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in entity_hints.items()
        ):
            raise ValueError("Entity names and values must be strings")

    resolution = resolver.resolve(
        user_id=PREVIEW_USER_ID,
        query=query,
        intent=intent,
        entity_hints=entity_hints,
        task_type_hint=task_type_hint
    )

    return {
        "action": resolution.action,
        "workflow_id": resolution.workflow_id,
        "reason": resolution.reason,
        "candidates": resolution.candidates,
        "preview_only": True
    }


def workflow_demo_mode() -> bool:
    return os.getenv(
        "OPENPOKE_ORCHESTRATION_MODE", "legacy"
    ).strip().lower() == "workflow_demo"

async def resolve_request_llm(
    *,
    store,
    hybrid,
    dense,
    user_id: str,
    query: str,
):
    """Resolve a UI request using the LLM Planner."""

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    # 1. Synchronize embeddings for existing and new workflows.
    dense.refresh(user_id)

    # 2. Retrieve the most relevant workflow candidates.
    candidates = hybrid.search(
        user_id=user_id,
        query=query,
        top_k=5,
    )

    # 3. Construct the same planner used by V2 evaluation.
    planner_client = OpenRouterPlannerClient(
        model=os.getenv(
            "OPENPOKE_WORKFLOW_PLANNER_MODEL", "openai/gpt-4.1-mini"
        ),
        timeout_seconds=30.0,
    )

    llm_resolver = LLMPlannerResolver(
        store=store,
        retriever=hybrid,
        planner=planner_client,
        top_k=5,
        raise_on_error=True,
    )

    # 4. Resolve without benchmark-only oracle annotations.
    resolution = await llm_resolver.resolve(
        user_id=user_id,
        query=query,
        intent_hint=None,
        entity_hints={},
        task_type_hint=None,
        precomputed_candidates=candidates,
        explicit_new=False,
    )

    return resolution


def workflow_live_mode() -> bool:
    return os.getenv(
        "OPENPOKE_ORCHESTRATION_MODE", "legacy"
    ).strip().lower() == "workflow_live"

