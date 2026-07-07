"""Cloud models via Groq (https://groq.com).

Groq serves open-weight models (Llama, Qwen, ...) behind an OpenAI-compatible
API, so this same class also works for any OpenAI-style endpoint by changing
`base_url`. Used as the quality fallback when the local model isn't enough.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from ..core.schemas import ChatResponse, Message, ToolCall
from .base import ChatProvider


class GroqProvider(ChatProvider):
    name = "groq"
    kind = "cloud"

    def __init__(
        self,
        model: str = "llama-3.3-70b-versatile",
        api_key: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout: int = 60,
        **options: Any,
    ) -> None:
        super().__init__(model, **options)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _to_wire(self, messages: list[Message]) -> list[dict]:
        wire: list[dict] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                wire.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            elif m.role == "tool":
                wire.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id or "",
                        "content": m.content,
                    }
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
            "temperature": kwargs.get("temperature", self.options.get("temperature", 0.7)),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}

        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args)
            )

        return ChatResponse(
            content=msg.get("content") or "",
            tool_calls=tool_calls,
            provider=self.name,
            model=self.model,
            raw=data,
        )
