
from dataclasses import dataclass, field
from typing import Any, Protocol

from .store import WorkflowStore
from .resolver import Resolution
import asyncio


@dataclass
class ExecutionOutcome:
    success: bool
    response: str
    error: str | None = None
    tools_executed: list[str] = field(
        default_factory=list
    )


@dataclass
class NewWorkflowSpec:
    title: str
    task_type: str
    summary: str
    context: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class DispatchResult:
    action: str
    workflow_id: str | None
    run_id: str | None
    status: str
    response: str


class WorkflowExecutor(Protocol):

    async def execute(
        self,
        *,
        workflow: dict,
        run_id: str,
        instructions: str
    ) -> ExecutionOutcome:
        ...


class WorkflowDispatcher:

    def __init__(
        self,
        store: WorkflowStore,
        executor: WorkflowExecutor
    ):
        self.store = store
        self.executor = executor

    async def dispatch(
        self,
        *,
        user_id: str,
        instructions: str,
        resolution: Resolution,
        new_workflow: NewWorkflowSpec | None = None
    ) -> DispatchResult:

        if not user_id.strip():
            raise ValueError("user_id cannot be empty")

        # 1. Clarification must not execute anything.
        if resolution.action == "CLARIFY":
            return DispatchResult(
                action="CLARIFY",
                workflow_id=None,
                run_id=None,
                status="needs_clarification",
                response=resolution.reason
            )

        if not instructions.strip():
            raise ValueError("instructions cannot be empty")

        # 2. Load an existing workflow.
        if resolution.action == "RESUME":
            if not resolution.workflow_id:
                raise ValueError("Missing workflow_id")

            workflow = self.store.get_workflow(
                resolution.workflow_id,
                user_id
            )

            if workflow is None:
                raise ValueError(
                    "Workflow not found or access denied"
                )

            if workflow["status"] != "active":
                raise ValueError(
                    "Cannot execute an inactive workflow"
                )

            workflow_id = workflow["workflow_id"]

        # 3. Create a new workflow.
        elif resolution.action == "CREATE":
            if new_workflow is None:
                raise ValueError(
                    "CREATE requires NewWorkflowSpec"
                )

            if not all([
                new_workflow.title.strip(),
                new_workflow.task_type.strip(),
                new_workflow.summary.strip()
            ]):
                raise ValueError(
                    "New workflow metadata cannot be empty"
                )

            workflow_id = self.store.create_workflow(
                user_id=user_id,
                title=new_workflow.title,
                task_type=new_workflow.task_type,
                summary=new_workflow.summary,
                context=new_workflow.context
            )

            workflow = self.store.get_workflow(
                workflow_id,
                user_id
            )

        else:
            raise ValueError(
                f"Unknown resolution action: {resolution.action}"
            )

        # 4. Create a persistent execution run.
        run_id = self.store.start_run(
            workflow_id=workflow_id,
            user_id=user_id,
            instructions=instructions
        )

        # 5. Execute using the injected executor.
        try:
            outcome = await self.executor.execute(
                workflow=workflow,
                run_id=run_id,
                instructions=instructions
            )

            if not isinstance(outcome, ExecutionOutcome):
                raise TypeError(
                    "Executor returned an invalid result"
                )


        except asyncio.CancelledError:
            self.store.finish_run(
                run_id=run_id,
                user_id=user_id,
                success=False,
                result={
                    "response": "Execution cancelled",
                    "tools_executed": []
                },
                error="Cancelled"
            )
            raise

        except Exception as exc:
            outcome = ExecutionOutcome(
                success=False,
                response="Execution failed",
                error=f"{type(exc).__name__}: {exc}"
            )

        # 6. Atomically persist final status and event.
        self.store.finish_run(
            run_id=run_id,
            user_id=user_id,
            success=outcome.success,
            result={
                "response": outcome.response,
                "tools_executed": outcome.tools_executed
            },
            error=outcome.error
        )

        return DispatchResult(
            action=resolution.action,
            workflow_id=workflow_id,
            run_id=run_id,
            status=(
                "completed" if outcome.success else "failed"
            ),
            response=outcome.response
        )
