from pathlib import Path

import pytest

from lumos.memory.database import Database
from lumos.retrieval.service import RetrievalService
from lumos.tools.builtin import build_tool_registry
from lumos.tools.registry import RegisteredTool, ToolRegistry
from lumos.web.service import WebSearchService


@pytest.mark.asyncio
async def test_registry_executes_only_registered_tools():
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            name="add",
            description="Add numbers",
            parameters={"type": "object"},
            handler=lambda a, b: a + b,
        )
    )

    assert await registry.execute("add", {"a": 2, "b": 3}) == 5
    with pytest.raises(KeyError):
        await registry.execute("shell", {"command": "whoami"})


@pytest.mark.asyncio
async def test_request_permissions_only_narrow_the_global_allowlist():
    registry = ToolRegistry()
    handler_calls = 0

    def handler():
        nonlocal handler_calls
        handler_calls += 1
        return "ran"

    registry.register(
        RegisteredTool(
            name="allowed",
            description="Allowed tool",
            parameters={"type": "object"},
            handler=handler,
        )
    )

    permitted_names = {"allowed", "not_registered"}
    schemas = registry.schemas(permitted_names)
    assert [schema["function"]["name"] for schema in schemas] == ["allowed"]
    assert await registry.execute("allowed", {}, permitted_names=permitted_names) == "ran"

    with pytest.raises(PermissionError, match="not permitted for this request"):
        await registry.execute("allowed", {}, permitted_names=set())
    assert handler_calls == 1

    with pytest.raises(KeyError):
        await registry.execute("not_registered", {}, permitted_names=permitted_names)


def built_registry(path: Path, *, allow_memory_writes: bool) -> ToolRegistry:
    database = Database(path)
    database.initialize()
    return build_tool_registry(
        retrieval=RetrievalService(database),
        web_search=WebSearchService(None),
        database=database,
        allow_memory_writes=allow_memory_writes,
    )


def registered_names(registry: ToolRegistry) -> set[str]:
    return {schema["function"]["name"] for schema in registry.schemas()}


@pytest.mark.asyncio
async def test_managing_memories_is_not_something_the_model_can_do(tmp_path: Path):
    """Listing, reading, deleting and exporting memories are the user's, not the model's.

    Not registering is the whole enforcement: the registry is an allowlist and
    `execute` raises for anything absent from it, so a note or a web page that
    tells the model to "export all memories" has nothing to call. Delete is
    irreversible and an export is every private fact in one file — both are worth
    a keystroke from the person whose memories they are.
    """
    registry = built_registry(tmp_path / "lumos.db", allow_memory_writes=False)
    with_writes = built_registry(tmp_path / "writes.db", allow_memory_writes=True)

    assert registered_names(registry) == {"search_notes", "search_web"}
    assert registered_names(with_writes) == {"search_notes", "search_web", "save_memory"}

    for name in ("list_memories", "get_memory", "delete_memory", "export_memories", "memory"):
        for candidate in (registry, with_writes):
            with pytest.raises(KeyError):
                await candidate.execute(name, {})
