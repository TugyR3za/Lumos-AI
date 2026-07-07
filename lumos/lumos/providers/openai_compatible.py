from __future__ import annotations

import json
from typing import Any

import httpx

from lumos.providers.base import Message, ProviderError, ProviderResponse, ToolCall, ToolSchema


class OpenAICompatibleProvider:
    """OpenAI-compatible `/chat/completions` provider.

    This intentionally uses a small HTTP adapter instead of coupling Lumos to one SDK.
    It can target OpenAI or another service that implements the same endpoint.
    """

    name = "cloud"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self._headers,
                )
                return response.is_success
        except httpx.HTTPError:
            return False

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ProviderError(
                f"Cloud provider returned {exc.response.status_code}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cloud provider request failed: {exc}") from exc

        data = response.json()
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Cloud provider returned an unexpected response") from exc

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
                    id=item.get("id", "tool-call"),
                    name=function.get("name", ""),
                    arguments=arguments or {},
                )
            )

        return ProviderResponse(
            content=message.get("content") or "",
            provider=self.name,
            model=data.get("model", self.model),
            tool_calls=calls,
            raw=data,
        )

    @staticmethod
    def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            item: dict[str, Any] = {"role": role, "content": message.get("content", "")}
            if role == "assistant" and message.get("tool_calls"):
                item["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call.get("arguments", {})),
                        },
                    }
                    for call in message["tool_calls"]
                ]
            elif role == "tool":
                item["tool_call_id"] = message.get("tool_call_id")
                item["name"] = message.get("name")
            converted.append(item)
        return converted
