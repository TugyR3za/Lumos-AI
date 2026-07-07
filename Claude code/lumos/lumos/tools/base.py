"""The Tool contract.

A tool is anything the model can invoke: web search, notes lookup, and later a
file reader, a shell sandbox, a calendar, an MCP bridge. Subclass `Tool`, declare
a name/description/parameters (JSON-Schema), and implement `run`. The registry
exposes it to any provider in OpenAI-style function-calling format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    #: Unique, model-facing name (snake_case).
    name: str = "tool"
    #: One clear sentence — the model reads this to decide when to call it.
    description: str = ""
    #: JSON-Schema for the arguments object.
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    def run(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result for the model."""

    def schema(self) -> dict:
        """OpenAI/Ollama-style function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
