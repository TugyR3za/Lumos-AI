"""Local models via Ollama (https://ollama.com).

Ollama exposes an HTTP API on localhost:11434. This provider speaks its
/api/chat endpoint, including native tool calling, and normalizes the reply
into our provider-neutral `ChatResponse`.
"""

from __future__ import annotations

from typing import Any

import requests

from ..core.schemas import ChatResponse, Message, ToolCall
from .base import ChatProvider


class OllamaProvider(ChatProvider):
    name = "ollama"
    kind = "local"

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        host: str = "http://localhost:11434",
        timeout: int = 120,
        **options: Any,
    ) -> None:
        super().__init__(model, **options)
        self.host = host.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def _to_wire(self, messages: list[Message]) -> list[dict]:
        wire: list[dict] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                wire.append(
                    {
                        "role": "assistant",
                        "content": m.content,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                }
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            elif m.role == "tool":
                # Ollama identifies tool results by name, not id.
                wire.append(
                    {"role": "tool", "content": m.content, "name": m.name or ""}
                )
            else:
                wire.append({"role": m.role, "content": m.content})
        return wire

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_wire(messages),
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.options.get("temperature", 0.7)),
                # Keep the context modest to stay light on 8GB machines.
                "num_ctx": kwargs.get("num_ctx", self.options.get("num_ctx", 4096)),
            },
        }
        if tools:
            payload["tools"] = tools

        r = requests.post(
            f"{self.host}/api/chat", json=payload, timeout=self.timeout
        )
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {}) or {}

        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):  # some builds return a JSON string
                import json

                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(name=fn.get("name", ""), arguments=args or {}))

        return ChatResponse(
            content=msg.get("content", "") or "",
            tool_calls=tool_calls,
            provider=self.name,
            model=self.model,
            raw=data,
        )
