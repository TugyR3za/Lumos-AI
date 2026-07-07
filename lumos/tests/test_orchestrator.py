from pathlib import Path

import pytest

from lumos.agent.orchestrator import AgentOrchestrator
from lumos.memory.database import Database
from lumos.providers.base import ProviderResponse, ToolCall
from lumos.providers.router import ProviderRouter
from lumos.retrieval.service import RetrievalService
from lumos.tools.registry import RegisteredTool, ToolRegistry
from lumos.web.service import WebSearchService


class ToolHungryProvider:
    """Requests a tool call whenever tools are offered; answers plainly otherwise."""

    name = "hungry"
    model = "hungry-model"

    def __init__(self):
        self.tool_rounds = 0
        self.plain_calls = 0

    async def is_available(self) -> bool:
        return True

    async def chat(self, messages, tools=None):
        if tools:
            self.tool_rounds += 1
            return ProviderResponse(
                content="",
                provider=self.name,
                model=self.model,
                tool_calls=[ToolCall(id=f"call-{self.tool_rounds}", name="ping", arguments={})],
            )
        self.plain_calls += 1
        return ProviderResponse("plain final answer", self.name, self.model)


class CapturingProvider:
    """Answers plainly and records every message list it was sent."""

    name = "capture"
    model = "capture-model"

    def __init__(self):
        self.seen_messages: list[list[dict]] = []

    async def is_available(self) -> bool:
        return True

    async def chat(self, messages, tools=None):
        self.seen_messages.append([dict(m) for m in messages])
        return ProviderResponse("ok", self.name, self.model)


def make_agent(tmp_path: Path, provider, max_tool_rounds: int = 2) -> AgentOrchestrator:
    database = Database(tmp_path / "lumos.db")
    database.initialize()
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            name="ping",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda: {"pong": True},
        )
    )
    return AgentOrchestrator(
        database=database,
        providers=ProviderRouter(local=provider, cloud=None),
        retrieval=RetrievalService(database),
        web_search=WebSearchService(None),
        tools=registry,
        history_limit=8,
        retrieval_top_k=3,
        web_search_max_results=3,
        max_tool_rounds=max_tool_rounds,
    )


@pytest.mark.asyncio
async def test_tool_exhaustion_returns_plain_answer(tmp_path: Path):
    provider = ToolHungryProvider()
    agent = make_agent(tmp_path, provider, max_tool_rounds=2)

    response = await agent.chat(
        user_message="hello",
        conversation_id=None,
        route="auto",
        use_notes=False,
        use_web=False,
    )

    assert response.answer == "plain final answer"
    assert provider.tool_rounds == 2  # the full tool budget was spent
    assert provider.plain_calls == 1  # then one final no-tools call
    assert len(response.tool_events) == 2
    assert all(event["ok"] for event in response.tool_events)


@pytest.mark.asyncio
async def test_normal_turn_unaffected_by_exhaustion_handling(tmp_path: Path):
    provider = CapturingProvider()
    agent = make_agent(tmp_path, provider)

    response = await agent.chat(
        user_message="hello",
        conversation_id=None,
        route="auto",
        use_notes=False,
        use_web=False,
    )

    assert response.answer == "ok"
    assert len(provider.seen_messages) == 1  # answered on the first call
    assert response.tool_events == []
