"""Holds the active tools and runs them by name."""

from __future__ import annotations

from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        """All tool schemas, for passing to a provider's `tools` param."""
        return [t.schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def run(self, name: str, arguments: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"[error] unknown tool: {name}"
        try:
            return tool.run(**(arguments or {}))
        except TypeError as e:
            return f"[error] bad arguments for {name}: {e}"
        except Exception as e:  # tools must never crash the loop
            return f"[error] {name} failed: {e}"

    def __len__(self) -> int:
        return len(self._tools)
