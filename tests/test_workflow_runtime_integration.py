
import asyncio
import json
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from server.services.execution.log_store import ExecutionAgentLogStore
from server.workflows.store import WorkflowStore
from server.workflows.resolver import Resolution
from server.workflows.dispatcher import WorkflowDispatcher
from server.workflows.openpoke_executor import OpenPokeExecutor


runtime_module = import_module(
    "server.agents.execution_agent.runtime"
)
agent_module = import_module(
    "server.agents.execution_agent.agent"
)

async def run_scenario():
    with TemporaryDirectory() as directory:
        root = Path(directory)

        store = WorkflowStore(root / "test.db")
        journal = ExecutionAgentLogStore(root / "logs")

        llm_calls = []
        tool_calls = []

        async def mock_lookup(thread_id: str) -> dict:
            tool_calls.append(thread_id)

            return {
                "thread_id": thread_id,
                "latest_reply": "Alice confirmed receipt."
            }

        def mock_registry(agent_name: str) -> dict:
            assert agent_name.startswith("workflow-")
            return {"mock_lookup": mock_lookup}

        mock_schema = {
            "type": "function",
            "function": {
                "name": "mock_lookup",
                "description": "Look up a fake email thread",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string"}
                    },
                    "required": ["thread_id"],
                    "additionalProperties": False
                }
            }
        }

        async def fake_chat_completion(
            *,
            model,
            messages,
            system,
            api_key,
            tools
        ):
            assert model == "mock-model"
            assert api_key == "TEST_KEY_NO_NETWORK"
            assert tools == [mock_schema]

            llm_calls.append({
                "system": system,
                "last_role": messages[-1]["role"]
            })

            # First LLM call: request a tool.
            if messages[-1]["role"] == "user":
                assert "thread_123" in messages[-1]["content"]

                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{
                                "id": "call_lookup",
                                "type": "function",
                                "function": {
                                    "name": "mock_lookup",
                                    "arguments": json.dumps({
                                        "thread_id": "thread_123"
                                    })
                                }
                            }]
                        }
                    }]
                }

            # Second LLM call: inspect tool result.
            if messages[-1]["role"] == "tool":
                assert (
                    messages[-1]["tool_call_id"]
                    == "call_lookup"
                )

                tool_result = json.loads(
                    messages[-1]["content"]
                )

                assert tool_result["tool"] == "mock_lookup"
                assert tool_result["status"] == "success"
                assert (
                    tool_result["result"]["thread_id"]
                    == "thread_123"
                )

                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Mock lookup completed: "
                                "Alice confirmed receipt."
                            ),
                            "tool_calls": []
                        }
                    }]
                }

            raise AssertionError(
                "Unexpected LLM conversation state"
            )

        with (
            patch.object(
                runtime_module,
                "get_settings",
                return_value=SimpleNamespace(
                    openrouter_api_key="TEST_KEY_NO_NETWORK",
                    execution_agent_model="mock-model"
                )
            ),
            patch.object(
                runtime_module,
                "request_chat_completion",
                side_effect=fake_chat_completion
            ),
            patch.object(
                runtime_module,
                "get_tool_registry",
                side_effect=mock_registry
            ),
            patch.object(
                runtime_module,
                "get_tool_schemas",
                return_value=[mock_schema]
            ),
            patch.object(
                agent_module,
                "get_execution_agent_logs",
                return_value=journal
            )
        ):
            executor = OpenPokeExecutor(
                runtime_factory=(
                    runtime_module.ExecutionAgentRuntime
                ),
                request_logger=journal.record_request
            )

            dispatcher = WorkflowDispatcher(
                store,
                executor
            )

            workflow_id = store.create_workflow(
                user_id="test_user",
                title="Alice Insurance",
                task_type="email",
                summary="Check Alice insurance messages",
                context={
                    "entities": {"contact": "Alice"},
                    "gmail_thread_id": "thread_123"
                }
            )

            resolution = Resolution(
                action="RESUME",
                workflow_id=workflow_id,
                candidates=[],
                reason="Matched workflow"
            )

            first = await dispatcher.dispatch(
                user_id="test_user",
                instructions="Check Alice's email",
                resolution=resolution
            )

            assert first.status == "completed"
            assert "Alice confirmed receipt" in first.response

            first_run = store.get_run(
                first.run_id, "test_user"
            )

            assert first_run["result"][
                "tools_executed"
            ] == ["mock_lookup"]

            assert tool_calls == ["thread_123"]
            assert len(llm_calls) == 2

            print("Native LLM tool loop PASSED")

            # Execute the SAME workflow again.
            second = await dispatcher.dispatch(
                user_id="test_user",
                instructions="Check Alice's email again",
                resolution=resolution
            )

            assert second.status == "completed"
            assert second.run_id != first.run_id

            # Second run's system prompt includes first run.
            assert (
                "Mock lookup completed"
                in llm_calls[2]["system"]
            )

            assert tool_calls == [
                "thread_123",
                "thread_123"
            ]

            assert len(llm_calls) == 4

            print("Native history restoration PASSED")

            agent_name = f"workflow-{workflow_id}"

            history = journal.load_transcript(
                agent_name
            )

            assert "mock_lookup" in history
            assert "Alice confirmed receipt" in history

            print("Tool journal persistence PASSED")

            events = store.list_events(
                workflow_id,
                "test_user"
            )

            completed_events = [
                e for e in events
                if e["event_type"] == "run_completed"
            ]

            assert len(completed_events) == 2

            print("Workflow run persistence PASSED")


def test_native_runtime_integration():
    asyncio.run(run_scenario())
