
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from server.workflows.store import WorkflowStore
from server.workflows.llm_planner import LLMPlannerResolver


class FakePlanner:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    async def propose(self, payload):
        self.calls.append(payload)
        return self.proposal


class FixedRetriever:
    def __init__(self, workflow_ids):
        self.workflow_ids = workflow_ids

    def search(self, user_id, query, top_k=5):
        return [
            {"workflow_id": workflow_id}
            for workflow_id in self.workflow_ids[:top_k]
        ]


async def run_tests():
    with TemporaryDirectory() as directory:
        store = WorkflowStore(
            Path(directory) / "planner_test.db"
        )

        alice = store.create_workflow(
            "user_1",
            "Alice Auto Insurance",
            "email",
            "Follow up on Alice auto insurance quote",
            context={"entities": {"contact": "Alice"}}
        )

        bob = store.create_workflow(
            "user_1",
            "Bob Auto Insurance",
            "email",
            "Follow up on Bob auto insurance quote",
            context={"entities": {"contact": "Bob"}}
        )

        meeting = store.create_workflow(
            "user_1",
            "Alice Meeting",
            "calendar",
            "Schedule a meeting with Alice",
            context={"entities": {"contact": "Alice"}}
        )

        private = store.create_workflow(
            "user_2",
            "Private Workflow",
            "email",
            "Confidential insurance follow-up"
        )

        retriever = FixedRetriever(
            [alice, bob, meeting]
        )

        def build(proposal, source=None):
            client = FakePlanner(proposal)
            resolver = LLMPlannerResolver(
                store,
                source or retriever,
                client
            )
            return resolver, client

        async def resolve(resolver, **kwargs):
            return await resolver.resolve(
                user_id="user_1",
                query="Follow up on Alice insurance",
                **kwargs
            )

        # 1. Valid planner selection
        planner, client = build({
            "action": "RESUME",
            "workflow_id": alice,
            "reason": "Matching insurance workflow"
        })

        result = await resolve(
            planner,
            entity_hints={"contact": "Alice"},
            task_type_hint="email"
        )

        assert result.action == "RESUME"
        assert result.workflow_id == alice
        assert len(client.calls) == 1
        assert len(
            client.calls[0]["candidate_workflows"]
        ) == 3

        print("Valid planner resume PASSED")

        # 2. Wrong entity must be rejected
        planner, _ = build({
            "action": "RESUME",
            "workflow_id": bob,
            "reason": "Incorrectly selected Bob"
        })

        result = await resolve(
            planner,
            entity_hints={"contact": "Alice"},
            task_type_hint="email"
        )

        assert result.action == "CLARIFY"
        assert result.workflow_id is None

        print("Entity conflict guard PASSED")

        # 3. Wrong task category must be rejected
        planner, _ = build({
            "action": "RESUME",
            "workflow_id": meeting,
            "reason": "Incorrectly selected meeting"
        })

        result = await resolve(
            planner,
            entity_hints={"contact": "Alice"},
            task_type_hint="email"
        )

        assert result.action == "CLARIFY"

        print("Task type guard PASSED")

        # 4. Invented ID must be rejected
        planner, _ = build({
            "action": "RESUME",
            "workflow_id": "invented-id",
            "reason": "Hallucinated workflow"
        })

        result = await resolve(planner)

        assert result.action == "CLARIFY"

        print("Hallucinated ID guard PASSED")

        # 5. Cross-user access must be rejected
        planner, _ = build(
            {
                "action": "RESUME",
                "workflow_id": private,
                "reason": "Wrong user's workflow"
            },
            FixedRetriever([private])
        )

        result = await resolve(planner)

        assert result.action == "CLARIFY"
        assert result.workflow_id is None

        print("Cross-user isolation PASSED")

        # 6. Explicit new task overrides the planner
        planner, client = build({
            "action": "RESUME",
            "workflow_id": alice,
            "reason": "Would resume"
        })

        result = await resolve(
            planner,
            explicit_new=True
        )

        assert result.action == "CREATE"
        assert len(client.calls) == 0

        print("Explicit CREATE guard PASSED")

        # 7. Valid planner CREATE
        planner, _ = build({
            "action": "CREATE",
            "workflow_id": None,
            "reason": "Independent new task"
        })

        result = await resolve(planner)
        assert result.action == "CREATE"

        print("Planner CREATE PASSED")

        # 8. Ambiguity
        planner, _ = build({
            "action": "CLARIFY",
            "workflow_id": None,
            "reason": "Multiple Alice workflows"
        })

        result = await resolve(planner)
        assert result.action == "CLARIFY"

        print("Planner CLARIFY PASSED")

        # 9. Invalid LLM output must fail safely
        planner, _ = build({
            "action": "DELETE",
            "workflow_id": alice,
            "reason": "Invalid action"
        })

        result = await resolve(planner)
        assert result.action == "CLARIFY"

        print("Invalid LLM output fallback PASSED")

    print("ALL LLM PLANNER TESTS PASSED")


def test_llm_planner_and_validator():
    asyncio.run(run_tests())
