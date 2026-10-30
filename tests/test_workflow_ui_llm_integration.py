"""Mock-only regression checks for UI -> LLM Resolution -> Demo Dispatcher.

Run: python -m pytest -q tests/test_workflow_ui_llm_integration.py
No OpenRouter or external services are called by these tests.
"""
import asyncio
import inspect
from types import SimpleNamespace

from server.workflows import bridge, demo
from server.agents.interaction_agent import tools


def test_bridge_preserves_original_component_contract(monkeypatch, tmp_path):
    objects = tuple(object() for _ in range(4))
    monkeypatch.setenv("OPENPOKE_WORKFLOW_DB", str(tmp_path / "mock.sqlite"))
    monkeypatch.setattr(bridge, "_build_components", lambda db_path: objects)
    assert bridge.get_components() == objects[:3]
    assert bridge.get_components(include_dense=True) == objects


def _run_demo_case(monkeypatch, action, new_workflow=None):
    store, hybrid, resolver, dense = [object() for _ in range(4)]
    called = {}
    monkeypatch.setattr(demo, "get_components", lambda **kwargs: (store, hybrid, resolver, dense))

    async def fake_llm(**kwargs):
        called["planner"] = kwargs
        return SimpleNamespace(action=action, reason="mock decision", workflow_id="workflow-123")

    class FakeDispatcher:
        def __init__(self, *, store: object, executor: object):
            assert store is called["planner"]["store"]
            assert isinstance(executor, demo.DemoExecutor)

        async def dispatch(self, *, user_id, instructions, resolution, new_workflow):
            called["dispatch"] = dict(
                user_id=user_id, instructions=instructions,
                resolution=resolution, new_workflow=new_workflow
            )
            return SimpleNamespace(
                action=resolution.action, workflow_id="workflow-123",
                run_id=None if action == "CLARIFY" else "run-123",
                status="clarify" if action == "CLARIFY" else "completed",
                response="simulated"
            )

    monkeypatch.setattr(demo, "resolve_request_llm", fake_llm)
    monkeypatch.setattr(demo, "WorkflowDispatcher", FakeDispatcher)
    result = asyncio.run(demo.simulate_workflow(
        query="Track the Contoso interview TEST-UI-0429",
        intent="unspecified", instructions="Track interview",
        new_workflow=new_workflow,
    ))
    assert result["action"] == action
    assert result["external_actions_executed"] is False
    assert called["planner"]["dense"] is dense
    assert called["planner"]["user_id"] == demo.PREVIEW_USER_ID
    assert called["dispatch"]["resolution"].action == action
    return called


def test_demo_create_uses_llm_and_fallback_metadata(monkeypatch):
    called = _run_demo_case(monkeypatch, "CREATE")
    spec = called["dispatch"]["new_workflow"]
    assert spec is not None
    assert "Contoso" in spec.title
    assert spec.task_type == "general"


def test_demo_resume_uses_llm_without_new_metadata(monkeypatch):
    called = _run_demo_case(monkeypatch, "RESUME")
    assert called["dispatch"]["new_workflow"] is None


def test_demo_clarify_does_not_require_metadata(monkeypatch):
    called = _run_demo_case(monkeypatch, "CLARIFY")
    assert called["dispatch"]["new_workflow"] is None


def test_interaction_tool_awaits_and_wraps_demo(monkeypatch):
    monkeypatch.setattr(tools, "workflow_demo_mode", lambda: True)

    async def fake_demo(**args):
        return {"action": "CREATE", "simulation": True, "external_actions_executed": False}

    monkeypatch.setattr(tools, "simulate_workflow", fake_demo)
    result = tools.handle_tool_call("route_and_simulate_workflow", {
        "query": "create test", "intent": "new", "instructions": "create test"
    })
    assert inspect.isawaitable(result)
    payload = asyncio.run(result)
    assert isinstance(payload, tools.ToolResult)
    assert payload.success
    assert payload.payload["action"] == "CREATE"


def test_bridge_planner_receives_precomputed_candidates(monkeypatch):
    called = {}
    expected_candidates = [{"workflow_id": "w-1"}]

    class FakeDense:
        def refresh(self, user_id):
            called["refresh"] = user_id

    class FakeHybrid:
        def search(self, *, user_id, query, top_k):
            called["search"] = (user_id, query, top_k)
            return expected_candidates

    class FakeClient:
        def __init__(self, **kwargs):
            called["model"] = kwargs.get("model")

    class FakePlannerResolver:
        def __init__(self, **kwargs):
            called["planner_args"] = kwargs

        async def resolve(self, **kwargs):
            called["resolve_args"] = kwargs
            return SimpleNamespace(action="RESUME", workflow_id="w-1", reason="match")

    monkeypatch.setattr(bridge, "OpenRouterPlannerClient", FakeClient)
    monkeypatch.setattr(bridge, "LLMPlannerResolver", FakePlannerResolver)
    store, dense, hybrid = object(), FakeDense(), FakeHybrid()
    decision = asyncio.run(bridge.resolve_request_llm(
        store=store, hybrid=hybrid, dense=dense,
        user_id="local_demo", query="continue task"
    ))
    assert decision.action == "RESUME"
    assert called["refresh"] == "local_demo"
    assert called["search"] == ("local_demo", "continue task", 5)
    assert called["resolve_args"]["precomputed_candidates"] is expected_candidates
    assert called["resolve_args"]["intent_hint"] is None
    assert called["planner_args"]["raise_on_error"] is True


def test_interaction_tool_returns_error_on_planner_failure(monkeypatch):
    monkeypatch.setattr(tools, "workflow_demo_mode", lambda: True)

    async def bad_demo(**args):
        raise RuntimeError("Mock provider failure")

    monkeypatch.setattr(tools, "simulate_workflow", bad_demo)
    result = tools.handle_tool_call("route_and_simulate_workflow", {
        "query": "test", "intent": "new", "instructions": "test"
    })
    payload = asyncio.run(result)
    assert isinstance(payload, tools.ToolResult)
    assert not payload.success
    assert "Mock provider failure" in payload.payload["error"]
