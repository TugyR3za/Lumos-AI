from __future__ import annotations

import json
from typing import Any

import httpx

from lumos.providers.base import (
    Message,
    ProviderAuthError,
    ProviderCheck,
    ProviderError,
    ProviderResponse,
    ToolCall,
    ToolSchema,
)

_PROBE_TIMEOUT_SECONDS = 5.0


def _name_for_host(base_url: str) -> str:
    """A recognizable provider name for status displays and message records."""
    host = httpx.URL(base_url).host or ""
    for marker, label in (("openrouter", "openrouter"), ("openai", "openai"), ("groq", "groq")):
        if marker in host:
            return label
    return "openai-compatible"


class OpenAICompatibleProvider:
    """OpenAI-compatible `/chat/completions` provider.

    This intentionally uses a small HTTP adapter instead of coupling Lumos to one SDK.
    It can target OpenAI or another service that implements the same endpoint.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.name = _name_for_host(base_url)
        self._transport = transport
        # Chat-observed auth failure; see OllamaProvider for the rationale.
        self._chat_auth_error: str | None = None

    async def check(self) -> ProviderCheck:
        if not self.api_key:
            return ProviderCheck("auth_failed", "no API key configured")
        if self._chat_auth_error:
            return ProviderCheck("auth_failed", self._chat_auth_error)

        # OpenRouter serves /models without auth, so probe its /key endpoint,
        # which validates the Bearer token. Other OpenAI-compatible hosts
        # (OpenAI, Groq, ...) already enforce auth on /models.
        probe_path = "/key" if self.name == "openrouter" else "/models"
        try:
            async with httpx.AsyncClient(
                timeout=_PROBE_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.get(f"{self.base_url}{probe_path}", headers=self._headers)
        except httpx.HTTPError as exc:
            return ProviderCheck("unreachable", f"{type(exc).__name__}: {exc}")

        if response.status_code in (401, 403):
            return ProviderCheck(
                "auth_failed",
                f"HTTP {response.status_code} from {probe_path} — check LUMOS_CLOUD_API_KEY",
            )
        if response.is_success:
            return ProviderCheck("available")
        return ProviderCheck("error", f"HTTP {response.status_code} from {probe_path}")

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
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            detail = exc.response.text[:500]
            if status_code in (401, 403):
                self._chat_auth_error = (
                    f"HTTP {status_code} from /chat/completions — check LUMOS_CLOUD_API_KEY"
                )
                raise ProviderAuthError(
                    f"{self.name} authentication failed ({status_code}): check LUMOS_CLOUD_API_KEY"
                ) from exc
            raise ProviderError(f"{self.name} returned {status_code}: {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc

        self._chat_auth_error = None
        data = response.json()
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.name} returned an unexpected response") from exc

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
