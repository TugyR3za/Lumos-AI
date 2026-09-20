import pytest

from lumos.tools.registry import RegisteredTool, ToolRegistry


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
