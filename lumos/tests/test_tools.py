import pytest

from app.tools.registry import RegisteredTool, ToolRegistry


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
