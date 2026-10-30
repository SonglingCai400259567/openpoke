"""Tool definitions for interaction agent."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional

from ...logging_config import logger
from ...services.conversation import get_conversation_log
from ...services.execution import get_agent_roster, get_execution_agent_logs
from ..execution_agent.batch_manager import ExecutionBatchManager

from ...workflows.bridge import (
    preview_mode,
    resolve_request
)
from ...workflows.bridge import workflow_demo_mode
from ...workflows.demo import simulate_workflow

from copy import deepcopy

from ...workflows.bridge import workflow_live_mode
from ...workflows.demo import execute_workflow_live

@dataclass
class ToolResult:
    """Standardized payload returned by interaction-agent tools."""

    success: bool
    payload: Any = None
    user_message: Optional[str] = None
    recorded_reply: bool = False

# Tool schemas for OpenRouter
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "send_message_to_agent",
            "description": "Deliver instructions to a specific execution agent. Creates a new agent if the name doesn't exist in the roster, or reuses an existing one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Human-readable agent name describing its purpose (e.g., 'Vercel Job Offer', 'Email to Sharanjeet'). This name will be used to identify and potentially reuse the agent."
                    },
                    "instructions": {"type": "string", "description": "Instructions for the agent to execute."},
                },
                "required": ["agent_name", "instructions"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message_to_user",
            "description": "Deliver a natural-language response directly to the user. Use this for updates, confirmations, or any assistant response the user should see immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Plain-text message that will be shown to the user and recorded in the conversation log.",
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_draft",
            "description": "Record an email draft so the user can review the exact text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email for the draft.",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject for the draft.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body content (plain text).",
                    },
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Wait silently when a message is already in conversation history to avoid duplicating responses. Adds a <wait> log entry that is not visible to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why waiting (e.g., 'Message already sent', 'Draft already created').",
                    },
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    },
]


RESOLVE_WORKFLOW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "resolve_workflow",
        "description": (
            "Find whether a request belongs to an existing "
            "workflow or needs a new one. This is a read-only "
            "routing decision; it does not execute the task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Original user request"
                },
                "intent": {
                    "type": "string",
                    "enum": [
                        "new",
                        "continue",
                        "unspecified"
                    ]
                },
                "entity_hints": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string"
                    },
                    "description": (
                        "Explicit entities identified from "
                        "the request, such as contact or "
                        "policy_id. Do not invent values."
                    )
                },
                "task_type_hint": {
                    "type": "string",
                    "description": (
                        "Relevant task category such as email "
                        "or calendar, if clearly identifiable."
                    )
                }
            },
            "required": ["query", "intent"],
            "additionalProperties": False
        }
    }
}


DEMO_WORKFLOW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "route_and_simulate_workflow",
        "description": (
            "Resolve a user's request and simulate the "
            "workflow execution lifecycle. No external "
            "actions or real email operations occur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string"
                },
                "intent": {
                    "type": "string",
                    "enum": [
                        "new",
                        "continue",
                        "unspecified"
                    ]
                },
                "instructions": {
                    "type": "string"
                },
                "entity_hints": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string"
                    }
                },
                "task_type_hint": {
                    "type": "string"
                },
                "new_workflow": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "task_type": {"type": "string"},
                        "summary": {"type": "string"},
                        "context": {"type": "object"}
                    },
                    "required": [
                        "title",
                        "task_type",
                        "summary"
                    ],
                    "additionalProperties": False
                }
            },
            "required": [
                "query",
                "intent",
                "instructions"
            ],
            "additionalProperties": False
        }
    }
}


LIVE_WORKFLOW_SCHEMA = deepcopy(DEMO_WORKFLOW_SCHEMA)

LIVE_WORKFLOW_SCHEMA["function"]["name"] = (
    "route_and_execute_workflow"
)

LIVE_WORKFLOW_SCHEMA["function"]["description"] = (
    "Route the user's request to an internal persistent "
    "OpenPoke workflow using the LLM Planner, then execute "
    "the task with a real Execution Agent. "
    "Use this tool for actionable user requests. "
    "It can CREATE or RESUME workflows, or request "
    "CLARIFY when the correct workflow is ambiguous. "
    "The execution agent has access to registered "
    "external tools, and real operations may occur. "
    "This is NOT a simulation."
)


_EXECUTION_BATCH_MANAGER = ExecutionBatchManager()


# Create or reuse execution agent and dispatch instructions asynchronously
def send_message_to_agent(agent_name: str, instructions: str) -> ToolResult:
    """Send instructions to an execution agent."""
    roster = get_agent_roster()
    roster.load()
    existing_agents = set(roster.get_agents())
    is_new = agent_name not in existing_agents

    if is_new:
        roster.add_agent(agent_name)

    get_execution_agent_logs().record_request(agent_name, instructions)

    action = "Created" if is_new else "Reused"
    logger.info(f"{action} agent: {agent_name}")

    async def _execute_async() -> None:
        try:
            result = await _EXECUTION_BATCH_MANAGER.execute_agent(agent_name, instructions)
            status = "SUCCESS" if result.success else "FAILED"
            logger.info(f"Agent '{agent_name}' completed: {status}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Agent '{agent_name}' failed: {str(exc)}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("No running event loop available for async execution")
        return ToolResult(success=False, payload={"error": "No event loop available"})

    loop.create_task(_execute_async())

    return ToolResult(
        success=True,
        payload={
            "status": "submitted",
            "agent_name": agent_name,
            "new_agent_created": is_new,
        },
    )


# Send immediate message to user and record in conversation history
def send_message_to_user(message: str) -> ToolResult:
    """Record a user-visible reply in the conversation log."""
    log = get_conversation_log()
    log.record_reply(message)

    return ToolResult(
        success=True,
        payload={"status": "delivered"},
        user_message=message,
        recorded_reply=True,
    )


# Format and record email draft for user review
def send_draft(
    to: str,
    subject: str,
    body: str,
) -> ToolResult:
    """Record a draft update in the conversation log for the interaction agent."""
    log = get_conversation_log()

    message = f"To: {to}\nSubject: {subject}\n\n{body}"

    log.record_reply(message)
    logger.info(f"Draft recorded for: {to}")

    return ToolResult(
        success=True,
        payload={
            "status": "draft_recorded",
            "to": to,
            "subject": subject,
        },
        recorded_reply=True,
    )


# Record silent wait state to avoid duplicate responses
def wait(reason: str) -> ToolResult:
    """Wait silently and add a wait log entry that is not visible to the user."""
    log = get_conversation_log()
    
    # Record a dedicated wait entry so the UI knows to ignore it
    log.record_wait(reason)
    

    return ToolResult(
        success=True,
        payload={
            "status": "waiting",
            "reason": reason,
        },
        recorded_reply=True,
    )


# Return predefined tool schemas for LLM function calling
'''def get_tool_schemas():
    """Return OpenAI-compatible tool schemas."""
    return TOOL_SCHEMAS'''


def get_tool_schemas():
    safe_tools = [
        schema
        for schema in TOOL_SCHEMAS
        if schema["function"]["name"] in {
            "send_message_to_user",
            "wait",
        }
    ]

    # Real workflow orchestration.
    if workflow_live_mode():
        return [
            LIVE_WORKFLOW_SCHEMA,
            *safe_tools,
        ]

    # Existing simulated workflow mode.
    if workflow_demo_mode():
        return [
            DEMO_WORKFLOW_SCHEMA,
            *safe_tools,
        ]

    # Read-only workflow preview.
    if preview_mode():
        return [
            RESOLVE_WORKFLOW_SCHEMA,
            *safe_tools,
        ]

    # Original OpenPoke mode.
    return TOOL_SCHEMAS


# Wrap async Demo results in the same ToolResult contract as other tools.
async def _run_workflow_demo_tool(args: dict) -> ToolResult:
    try:
        outcome = await simulate_workflow(**args)
        return ToolResult(success=True, payload=outcome)
    except Exception as exc:
        logger.error(f"Workflow demo tool failed: {exc}")
        return ToolResult(success=False, payload={"error": str(exc)})


async def _run_workflow_live_tool(args: dict) -> ToolResult:
    try:
        outcome = await execute_workflow_live(**args)

        status = str(outcome.get("status", "")).upper()

        return ToolResult(
            success=status not in {"FAILED", "ERROR"},
            payload=outcome,
        )

    except Exception as exc:
        logger.exception("Live workflow execution failed")

        return ToolResult(
            success=False,
            payload={
                "error": str(exc),
            },
        )


# Route tool calls to appropriate handlers with argument validation and error handling
def handle_tool_call(name: str, arguments: Any) -> ToolResult:
    """Handle tool calls from interaction agent."""
    try:
        if isinstance(arguments, str):
            args = json.loads(arguments) if arguments.strip() else {}
        elif isinstance(arguments, dict):
            args = arguments
        else:
            return ToolResult(success=False, payload={"error": "Invalid arguments format"})



        if workflow_live_mode():
            if name == "route_and_execute_workflow":
                return _run_workflow_live_tool(args)

            if name not in {
                "send_message_to_user",
                "wait",
            }:
                return ToolResult(
                    success=False,
                    payload={
                        "error": "Tool disabled in workflow live mode"
                    },
                )

        elif workflow_demo_mode():
            if name == "route_and_simulate_workflow":
                return _run_workflow_demo_tool(args)

            if name not in {
                "send_message_to_user",
                "wait",
            }:
                return ToolResult(
                    success=False,
                    payload={
                        "error": "Tool disabled in demo mode"
                    },
                )

        elif preview_mode():
            if name == "resolve_workflow":
                return ToolResult(
                    success=True,
                    payload=resolve_request(**args),
                )

            if name not in {
                "send_message_to_user",
                "wait",
            }:
                return ToolResult(
                    success=False,
                    payload={
                        "error": "Tool disabled in preview mode"
                    },
                )



        if name == "send_message_to_agent":
            return send_message_to_agent(**args)
        if name == "send_message_to_user":
            return send_message_to_user(**args)
        if name == "send_draft":
            return send_draft(**args)
        if name == "wait":
            return wait(**args)

        logger.warning("unexpected tool", extra={"tool": name})
        return ToolResult(success=False, payload={"error": f"Unknown tool: {name}"})
    except json.JSONDecodeError:
        return ToolResult(success=False, payload={"error": "Invalid JSON"})
    except TypeError as exc:
        return ToolResult(success=False, payload={"error": f"Missing required arguments: {exc}"})
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("tool call failed", extra={"tool": name, "error": str(exc)})
        return ToolResult(success=False, payload={"error": "Failed to execute"})
