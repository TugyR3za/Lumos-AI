from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from app.providers.base import Message, ProviderError, ProviderResponse, ToolCall, ToolSchema


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.is_success
        except httpx.HTTPError:
            return False

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        message = data.get("message", {})
        calls: list[ToolCall] = []
        for item in message.get("tool_calls", []) or []:
            function = item.get("function", {})
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments}
            calls.append(
                ToolCall(
                    id=item.get("id") or f"ollama-{uuid.uuid4().hex[:12]}",
                    name=function.get("name", ""),
                    arguments=arguments or {},
                )
            )

        return ProviderResponse(
            content=message.get("content", "") or "",
            provider=self.name,
            model=data.get("model", self.model),
            tool_calls=calls,
            raw=data,
        )

    @staticmethod
    def _to_ollama_messages(messages: list[Message]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            item: dict[str, Any] = {"role": role, "content": message.get("content", "")}
            if role == "assistant" and message.get("tool_calls"):
                item["tool_calls"] = [
                    {
                        "function": {
                            "name": call["name"],
                            "arguments": call.get("arguments", {}),
                        }
                    }
                    for call in message["tool_calls"]
                ]
            elif role == "tool":
                item["role"] = "tool"
                item["tool_name"] = message.get("name", "tool")
            converted.append(item)
        return converted
