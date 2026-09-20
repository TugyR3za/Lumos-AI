from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Any

ToolHandler = Callable[..., Any | Awaitable[Any]]


@dataclass(slots=True)
class RegisteredTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Explicit allowlist of functions an AI provider may request."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self, permitted_names: Collection[str] | None = None) -> list[dict[str, Any]]:
        return [
            tool.schema()
            for tool in self._tools.values()
            if permitted_names is None or tool.name in permitted_names
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        permitted_names: Collection[str] | None = None,
    ) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise KeyError(f"Unknown or disallowed tool: {name}")
        if permitted_names is not None and name not in permitted_names:
            raise PermissionError(f"Tool '{name}' is not permitted for this request.")
        result = tool.handler(**arguments)
        if inspect.isawaitable(result):
            return await result
        return result

    def names(self) -> list[str]:
        return sorted(self._tools)
