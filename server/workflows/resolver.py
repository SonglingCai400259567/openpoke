
from dataclasses import dataclass
from typing import Literal

from .store import WorkflowStore
from .hybrid import HybridWorkflowRetriever


RouteAction = Literal[
    "RESUME",
    "CREATE",
    "CLARIFY"
]

RequestIntent = Literal[
    "new",
    "continue",
    "unspecified"
]


@dataclass
class Resolution:
    action: RouteAction
    workflow_id: str | None
    candidates: list[dict]
    reason: str


class WorkflowResolver:

    def __init__(
        self,
        store: WorkflowStore,
        retriever: HybridWorkflowRetriever
    ):
        self.store = store
        self.retriever = retriever

    def resolve(
        self,
        user_id: str,
        query: str,
        intent: RequestIntent = "unspecified",
        entity_hints: dict[str, str] | None = None,
        task_type_hint: str | None = None,
        top_k: int = 5
    ) -> Resolution:

        if intent not in ("new", "continue", "unspecified"):
            raise ValueError("Invalid request intent")

        if not query.strip():
            raise ValueError("Query cannot be empty")

        if intent == "new":
            return Resolution(
                action="CREATE",
                workflow_id=None,
                candidates=[],
                reason="User explicitly requested a new workflow"
            )

        candidates = self.retriever.search(
            user_id=user_id,
            query=query,
            top_k=top_k
        )

        if not candidates:
            action = (
                "CLARIFY" if intent == "continue"
                else "CREATE"
            )

            return Resolution(
                action=action,
                workflow_id=None,
                candidates=[],
                reason="No workflow candidates were retrieved"
            )

        hints = {
            key.strip().casefold(): value.strip().casefold()
            for key, value in (entity_hints or {}).items()
            if key.strip() and value.strip()
        }

        task_hint = (
            task_type_hint.strip().casefold()
            if task_type_hint
            else None
        )

        viable = []

        for candidate in candidates:
            workflow = self.store.get_workflow(
                candidate["workflow_id"],
                user_id
            )

            if workflow is None:
                continue

            if (
                task_hint is not None
                and workflow["task_type"].casefold() != task_hint
            ):
                continue

            context = workflow.get("context") or {}
            stored_entities = context.get("entities") or {}

            stored = {
                str(key).strip().casefold():
                    str(value).strip().casefold()
                for key, value in stored_entities.items()
            }

            has_conflict = any(
                key in stored and stored[key] != value
                for key, value in hints.items()
            )

            if has_conflict:
                continue

            missing_metadata = any(
                key not in stored
                for key in hints
            )

            viable.append({
                "candidate": candidate,
                "missing_metadata": missing_metadata
            })

        if (
            intent == "continue"
            and hints
            and len(viable) == 1
            and not viable[0]["missing_metadata"]
        ):
            selected = viable[0]["candidate"]

            return Resolution(
                action="RESUME",
                workflow_id=selected["workflow_id"],
                candidates=[selected],
                reason=(
                    "Unique candidate matches the supplied "
                    "workflow entity constraints"
                )
            )

        return Resolution(
            action="CLARIFY",
            workflow_id=None,
            candidates=[
                item["candidate"]
                for item in viable
            ] or candidates,
            reason=(
                "Insufficient evidence for an unambiguous "
                "workflow match"
            )
        )
