from pathlib import Path

import pytest

from lumos.agent.orchestrator import AgentOrchestrator
from lumos.memory.database import Database
from lumos.providers.base import ProviderCheck, ProviderResponse, ToolCall
from lumos.providers.echo import EchoProvider
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

    async def check(self) -> ProviderCheck:
        return ProviderCheck("available")

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

    async def check(self) -> ProviderCheck:
        return ProviderCheck("available")

    async def chat(self, messages, tools=None):
        self.seen_messages.append([dict(m) for m in messages])
        return ProviderResponse("ok", self.name, self.model)


def make_agent(
    tmp_path: Path,
    provider,
    max_tool_rounds: int = 2,
    router: ProviderRouter | None = None,
) -> tuple[Database, AgentOrchestrator]:
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
    agent = AgentOrchestrator(
        database=database,
        providers=router or ProviderRouter(primary=provider, fallback=None),
        retrieval=RetrievalService(database),
        web_search=WebSearchService(None),
        tools=registry,
        history_limit=8,
        retrieval_top_k=3,
        web_search_max_results=3,
        max_tool_rounds=max_tool_rounds,
        memory_top_k=4,
    )
    return database, agent


@pytest.mark.asyncio
async def test_tool_exhaustion_returns_plain_answer(tmp_path: Path):
    provider = ToolHungryProvider()
    _, agent = make_agent(tmp_path, provider, max_tool_rounds=2)

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
    _, agent = make_agent(tmp_path, provider)

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


@pytest.mark.asyncio
async def test_relevant_memories_are_injected_into_system_prompt(tmp_path: Path):
    provider = CapturingProvider()
    database, agent = make_agent(tmp_path, provider)
    database.save_memory("Family pizza night is every Friday", source="test")
    database.save_memory("The car insurance renews in March", memory_key="insurance", source="test")

    await agent.chat(
        user_message="When is pizza night?",
        conversation_id=None,
        route="auto",
        use_notes=False,
        use_web=False,
    )

    system_message = provider.seen_messages[0][0]
    assert system_message["role"] == "system"
    assert "SAVED PERSONAL MEMORIES" in system_message["content"]
    assert "Family pizza night is every Friday" in system_message["content"]
    # The unrelated memory shares no words with the query and must not appear.
    assert "car insurance" not in system_message["content"]


@pytest.mark.asyncio
async def test_no_memory_section_when_nothing_is_saved(tmp_path: Path):
    provider = CapturingProvider()
    _, agent = make_agent(tmp_path, provider)

    await agent.chat(
        user_message="hello there",
        conversation_id=None,
        route="auto",
        use_notes=False,
        use_web=False,
    )

    system_message = provider.seen_messages[0][0]
    assert "SAVED PERSONAL MEMORIES" not in system_message["content"]


def index_note(database: Database, text: str) -> None:
    database.replace_document(
        path="notes/pizza.md",
        title="pizza",
        sha256="test-hash",
        mtime_ns=1,
        chunks=[text],
    )


@pytest.mark.asyncio
async def test_echo_answers_carry_no_sources(tmp_path: Path):
    # When every real provider is out and echo answers, the note context that
    # was gathered must not be presented as citations under the canned reply.
    echo_router = ProviderRouter(primary=None, fallback=None, echo=EchoProvider())
    database, agent = make_agent(tmp_path, None, router=echo_router)
    index_note(database, "Family pizza night is every Friday")

    response = await agent.chat(
        user_message="When is pizza night?",
        conversation_id=None,
        route="auto",
        use_notes=True,
        use_web=False,
    )

    assert response.provider == "echo"
    assert response.sources == []


@pytest.mark.asyncio
async def test_real_provider_answers_keep_note_sources(tmp_path: Path):
    # Guard for the echo case above: source suppression must apply only to echo.
    provider = CapturingProvider()
    database, agent = make_agent(tmp_path, provider)
    index_note(database, "Family pizza night is every Friday")

    response = await agent.chat(
        user_message="When is pizza night?",
        conversation_id=None,
        route="auto",
        use_notes=True,
        use_web=False,
    )

    assert response.provider == "capture"
    assert response.sources
    assert all(source.kind == "note" for source in response.sources)
