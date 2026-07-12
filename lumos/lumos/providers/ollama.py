from __future__ import annotations

import json
import uuid
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

_PROBE_TIMEOUT_SECONDS = 3.0


class OllamaProvider:
    """Speaks the Ollama `/api/chat` protocol against a local server or Ollama Cloud.

    Ollama Cloud (https://ollama.com) is wire-compatible with the local API and
    authenticates with a Bearer key, so one adapter covers both modes.
    """

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 90.0,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key
        self.name = "ollama-cloud" if api_key else "ollama"
        self._transport = transport
        # Auth truth comes from real chats, not probes (ollama.com has no
        # endpoint that cheaply verifies an API key): a chat 401/403 sets
        # _chat_auth_error (sticky until a chat succeeds); a successful chat
        # sets _chat_verified so check() can report the key as proven.
        self._chat_auth_error: str | None = None
        self._chat_verified = False

    @property
    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def _probe(self, path: str) -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            return await client.get(f"{self.base_url}{path}", headers=self._headers)

    async def check(self) -> ProviderCheck:
        if self._chat_auth_error:
            return ProviderCheck("auth_failed", self._chat_auth_error)

        # Reachability-only probe. ollama.com cannot verify a key via GET:
        # /api/tags is public (200 for any key) and /api/ps returns 401 for
        # valid keys too (observed 2026-07-07), so neither testifies about
        # auth. Do not "restore" an /api/ps probe here.
        try:
            response = await self._probe("/api/tags")
        except httpx.HTTPError as exc:
            return ProviderCheck("unreachable", f"{type(exc).__name__}: {exc}")

        if response.status_code in (401, 403):
            # Never happens on ollama.com (public endpoint), but a private
            # deployment behind an authenticating proxy does enforce here,
            # and there the 401 is a genuine auth signal.
            return ProviderCheck(
                "auth_failed",
                f"HTTP {response.status_code} from /api/tags — check LUMOS_OLLAMA_API_KEY",
            )
        if not response.is_success:
            return ProviderCheck("error", f"HTTP {response.status_code} from /api/tags")
        if not self.api_key:
            return ProviderCheck("available")  # keyless local mode: nothing to verify
        if self._chat_verified:
            return ProviderCheck("available", "verified by live chat")
        return ProviderCheck("reachable", "API key not verified yet — first chat will confirm")

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
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat", json=payload, headers=self._headers
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            detail = exc.response.text[:300]
            if status_code in (401, 403):
                hint = "check LUMOS_OLLAMA_API_KEY" if self.api_key else "server requires auth"
                self._chat_auth_error = f"HTTP {status_code} from /api/chat — {hint}"
                raise ProviderAuthError(
                    f"Ollama authentication failed ({status_code}): {hint}"
                ) from exc
            raise ProviderError(f"Ollama request failed ({status_code}): {detail}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        self._chat_auth_error = None
        self._chat_verified = True
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
