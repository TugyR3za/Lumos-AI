"""Provider-neutral data types.

These are the *internal* shapes the whole system speaks. Each provider is
responsible for translating to/from its own wire format, so nothing outside
`providers/` ever depends on Ollama's or Groq's specific JSON.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A request from the model to run one tool."""

    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")


@dataclass
class Message:
    """One turn in a conversation.

    role: "system" | "user" | "assistant" | "tool"
    - assistant messages may carry `tool_calls`
    - tool messages carry `tool_call_id` and `name`
    """

    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class ChatResponse:
    """A model's reply: free text, and/or a set of tool calls to run."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)
