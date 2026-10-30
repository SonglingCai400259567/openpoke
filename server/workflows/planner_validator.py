
from dataclasses import dataclass
from typing import Any

from .resolver import Resolution
from .store import WorkflowStore


@dataclass(frozen=True)
class PlannerProposal:
    action: str
    workflow_id: str | None
    reason: str

    @classmethod
    def from_dict(cls, data: Any) -> "PlannerProposal":
        if not isinstance(data, dict):
            raise ValueError("Planner output must be an object")

        action = data.get("action")
        workflow_id = data.get("workflow_id")
        reason = data.get("reason")

        if action not in {"RESUME", "CREATE", "CLARIFY"}:
            raise ValueError("Invalid planner action")

        if workflow_id is not None and not isinstance(
            workflow_id, str
        ):
            raise ValueError("Invalid workflow_id")

        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Planner reason is required")

        return cls(
            action=action,
            workflow_id=workflow_id,
            reason=reason.strip()[:500]
        )


class PlannerValidator:
    def __init__(self, store: WorkflowStore):
        self.store = store

    def validate(
        self,
        *,
        proposal: PlannerProposal,
        user_id: str,
        candidates: list[dict],
        entity_hints: dict[str, str] | None = None,
        task_type_hint: str | None = None,
        explicit_new: bool = False,
    ) -> Resolution:

        def clarify(reason: str) -> Resolution:
            return Resolution(
                action="CLARIFY",
                workflow_id=None,
                candidates=candidates,
                reason=reason
            )

        # A trusted explicit new-task instruction wins.
        if explicit_new:
            return Resolution(
                action="CREATE",
                workflow_id=None,
                candidates=[],
                reason="Explicit new-workflow instruction"
            )

        if proposal.action == "CLARIFY":
            return clarify(proposal.reason)

        if proposal.action == "CREATE":
            if proposal.workflow_id is not None:
                return clarify(
                    "CREATE must not select an existing workflow"
                )

            return Resolution(
                action="CREATE",
                workflow_id=None,
                candidates=candidates,
                reason=proposal.reason
            )

        # RESUME requires an existing, retrieved workflow.
        selected_id = proposal.workflow_id

        allowed_ids = {
            item["workflow_id"] for item in candidates
        }

        if not selected_id or selected_id not in allowed_ids:
            return clarify(
                "Planner selected a workflow outside Top-K"
            )

        workflow = self.store.get_workflow(
            selected_id, user_id
        )

        if workflow is None:
            return clarify(
                "Workflow does not exist or access denied"
            )

        if workflow["status"] != "active":
            return clarify(
                "Selected workflow is not active"
            )

        if task_type_hint is not None:
            if (
                workflow["task_type"].strip().casefold()
                != task_type_hint.strip().casefold()
            ):
                return clarify("Task type mismatch")

        context = workflow.get("context") or {}
        stored_entities = context.get("entities") or {}

        if not isinstance(stored_entities, dict):
            stored_entities = {}

        normalized = {
            str(k).strip().casefold():
                str(v).strip().casefold()
            for k, v in stored_entities.items()
        }

        for key, value in (entity_hints or {}).items():
            normalized_key = key.strip().casefold()
            normalized_value = value.strip().casefold()

            if normalized.get(normalized_key) != normalized_value:
                return clarify(
                    f"Missing or conflicting entity: {key}"
                )

        return Resolution(
            action="RESUME",
            workflow_id=selected_id,
            candidates=candidates,
            reason=f"Planner selection validated: {proposal.reason}"
        )
