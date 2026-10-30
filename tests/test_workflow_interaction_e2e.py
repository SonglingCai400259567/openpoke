
import asyncio
import json
import os

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from server.workflows.bridge import (
    PREVIEW_USER_ID,
    get_components,
)

from server.agents.interaction_agent import (
    runtime as interaction_runtime,
)


class FakeConversationLog:
    def __init__(self):
        self.messages = []
        self.replies = []

    def load_transcript(self):
        return ""

    def record_user_message(self, message):
        self.messages.append(message)

    def record_reply(self, message):
        self.replies.append(message)


async def run_e2e():
    with TemporaryDirectory() as directory:
        environment = {
            "OPENPOKE_ORCHESTRATION_MODE":
                "workflow_demo",
            "OPENPOKE_WORKFLOW_DB":
                str(Path(directory) / "workflow.db"),
        }

        with patch.dict(os.environ, environment):
            store, _, _ = get_components()

            workflow_id = store.create_workflow(
                user_id=PREVIEW_USER_ID,
                title="Alice Insurance Quote",
                task_type="email",
                summary="Follow up on Alice insurance quote",
                context={
                    "entities": {
                        "contact": "Alice"
                    },
                    "gmail_thread_id": "thread_123",
                },
            )

            fake_log = FakeConversationLog()
            llm_calls = []

            async def fake_llm(
                *,
                model,
                messages,
                system,
                api_key,
                tools,
            ):
                llm_calls.append(messages[-1]["role"])

                tool_names = {
                    t["function"]["name"] for t in tools
                }

                assert "route_and_simulate_workflow" in tool_names
                assert "send_message_to_agent" not in tool_names

                if messages[-1]["role"] == "user":
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [{
                                    "id": "call_demo_1",
                                    "type": "function",
                                    "function": {
                                        "name":
                                            "route_and_simulate_workflow",
                                        "arguments": json.dumps({
                                            "query":
                                                "Did Alice reply about insurance?",
                                            "intent": "continue",
                                            "instructions":
                                                "Check Alice insurance reply",
                                            "entity_hints": {
                                                "contact": "Alice"
                                            },
                                            "task_type_hint": "email",
                                        })
                                    }
                                }]
                            }
                        }]
                    }

                assert messages[-1]["role"] == "tool"

                tool_message = json.loads(
                    messages[-1]["content"]
                )

                assert tool_message["status"] == "success"

                decision = tool_message["result"]

                assert decision["simulation"] is True
                assert decision["action"] == "RESUME"
                assert decision["workflow_id"] == workflow_id
                assert decision["external_actions_executed"] is False

                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": (
                                "SIMULATION ONLY: Resumed Alice "
                                "Insurance workflow. No email "
                                "was sent."
                            ),
                            "tool_calls": [],
                        }
                    }]
                }

            fake_settings = SimpleNamespace(
                openrouter_api_key="TEST_KEY",
                interaction_agent_model="mock-model",
                summarization_enabled=False,
            )

            with (
                patch.object(
                    interaction_runtime,
                    "get_settings",
                    return_value=fake_settings,
                ),
                patch.object(
                    interaction_runtime,
                    "get_conversation_log",
                    return_value=fake_log,
                ),
                patch.object(
                    interaction_runtime,
                    "get_working_memory_log",
                    return_value=SimpleNamespace(),
                ),
                patch.object(
                    interaction_runtime,
                    "request_chat_completion",
                    side_effect=fake_llm,
                ),
            ):
                agent = (
                    interaction_runtime.InteractionAgentRuntime()
                )

                result = await agent.execute(
                    "Did Alice reply about insurance?"
                )

            assert result.success, result.error
            assert len(llm_calls) == 2

            print("Interaction LLM loop PASSED")

            assert "No email was sent" in result.response

            print("Simulation safety PASSED")

            events = store.list_events(
                workflow_id,
                PREVIEW_USER_ID,
            )

            completed = [
                e for e in events
                if e["event_type"] == "run_completed"
            ]

            assert len(completed) == 1

            run_id = completed[0]["payload"]["run_id"]
            run = store.get_run(run_id, PREVIEW_USER_ID)

            assert run["status"] == "completed"
            assert "SIMULATION ONLY" in (
                run["result"]["response"]
            )

            print("Workflow lifecycle PASSED")
            print("ALL E2E TESTS PASSED")


def test_workflow_interaction_e2e():
    asyncio.run(run_e2e())
