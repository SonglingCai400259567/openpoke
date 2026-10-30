
from .bridge import (
    PREVIEW_USER_ID,
    get_components,
    resolve_request_llm,
)
from .dispatcher import (
    WorkflowDispatcher,
    ExecutionOutcome,
    NewWorkflowSpec,
)

import os

from .openpoke_executor import OpenPokeExecutor


class DemoExecutor:
    async def execute(
        self,
        *,
        workflow: dict,
        run_id: str,
        instructions: str,
    ) -> ExecutionOutcome:

        return ExecutionOutcome(
            success=True,
            response=(
                "SIMULATION ONLY: Workflow routing and "
                "execution lifecycle completed. "
                "No external tools were called."
            ),
            tools_executed=[],
        )


async def simulate_workflow(
    query: str,
    intent: str,
    instructions: str,
    entity_hints: dict | None = None,
    task_type_hint: str | None = None,
    new_workflow: dict | None = None,
) -> dict:

    if not instructions.strip():
        raise ValueError("Instructions cannot be empty")

    # Shared cached components, including the SAME dense retriever used by hybrid.
    store, hybrid, _, dense = get_components(include_dense=True)

    # Route exactly once. The Planner's validated Resolution goes to Dispatcher.
    resolution = await resolve_request_llm(
        store=store,
        hybrid=hybrid,
        dense=dense,
        user_id=PREVIEW_USER_ID,
        query=query,
    )

    specification = None

    if resolution.action == "CREATE":
        # Metadata is needed only after the Planner has decided CREATE.
        # Allow a safe demo fallback when the Interaction Agent omitted metadata.
        metadata = new_workflow if new_workflow is not None else {}
        if not isinstance(metadata, dict):
            raise ValueError("new_workflow must be an object")

        context = metadata.get("context", {})
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise ValueError("context must be an object")

        def nonempty(value, fallback: str) -> str:
            return value.strip() if isinstance(value, str) and value.strip() else fallback

        specification = NewWorkflowSpec(
            title=nonempty(metadata.get("title"), query.strip()[:120]),
            task_type=nonempty(metadata.get("task_type"), task_type_hint or "general"),
            summary=nonempty(metadata.get("summary"), query.strip()),
            context=context,
        )

    dispatcher = WorkflowDispatcher(
        store=store,
        executor=DemoExecutor(),
    )

    result = await dispatcher.dispatch(
        user_id=PREVIEW_USER_ID,
        instructions=instructions,
        resolution=resolution,
        new_workflow=specification,
    )

    return {
        "simulation": True,
        "action": result.action,
        "workflow_id": result.workflow_id,
        "run_id": result.run_id,
        "status": result.status,
        "reason": resolution.reason,
        "response": result.response,
        "external_actions_executed": False,
    }


async def execute_workflow_live(
    query: str,
    intent: str,
    instructions: str,
    entity_hints: dict | None = None,
    task_type_hint: str | None = None,
    new_workflow: dict | None = None,
) -> dict:
    """
    Route and execute a workflow using the real
    OpenPoke ExecutionAgentRuntime.
    """

    # Require explicit opt-in for actual external tools.
    if os.getenv("OPENPOKE_ENABLE_LIVE_TOOLS") != "1":
        raise RuntimeError(
            "Live tools are disabled. "
            "Set OPENPOKE_ENABLE_LIVE_TOOLS=1."
        )

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query cannot be empty")

    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("Instructions cannot be empty")

    # 1. Load the shared persistent components.
    store, hybrid, _, dense = get_components(
        include_dense=True
    )

    # 2. Use the real LLM Planner to route exactly once.
    resolution = await resolve_request_llm(
        store=store,
        hybrid=hybrid,
        dense=dense,
        user_id=PREVIEW_USER_ID,
        query=query,
    )

    # 3. Prepare workflow metadata only for CREATE.
    specification = None

    if resolution.action == "CREATE":
        metadata = new_workflow if new_workflow is not None else {}

        if not isinstance(metadata, dict):
            raise ValueError("new_workflow must be an object")

        context = metadata.get("context") or {}

        if not isinstance(context, dict):
            raise ValueError("Workflow context must be an object")

        def nonempty(value, fallback: str) -> str:
            if isinstance(value, str) and value.strip():
                return value.strip()
            return fallback

        specification = NewWorkflowSpec(
            title=nonempty(
                metadata.get("title"),
                query.strip()[:120],
            ),
            task_type=nonempty(
                metadata.get("task_type"),
                task_type_hint or "general",
            ),
            summary=nonempty(
                metadata.get("summary"),
                query.strip(),
            ),
            context=context,
        )

    # 4. Instantiate the real execution adapter.
    executor = OpenPokeExecutor(
        allow_live=True,
        timeout_seconds=180,
    )

    # 5. Reuse the original WorkflowDispatcher.
    dispatcher = WorkflowDispatcher(
        store=store,
        executor=executor,
    )

    # 6. Dispatch the validated Planner decision.
    result = await dispatcher.dispatch(
        user_id=PREVIEW_USER_ID,
        instructions=instructions,
        resolution=resolution,
        new_workflow=specification,
    )

    # 7. Return the actual execution result to the UI.
    return {
        "simulation": False,
        "external_tools_enabled": True,
        "action": result.action,
        "workflow_id": result.workflow_id,
        "run_id": result.run_id,
        "status": result.status,
        "reason": resolution.reason,
        "response": result.response,
    }
