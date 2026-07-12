from __future__ import annotations

import logging
from typing import Literal

from lumos.providers.base import ChatProvider, Message, ProviderError, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


class ProviderRouter:
    """Routes requests without leaking provider-specific code into the agent.

    Slots, in `auto` order:
      primary  — the Ollama provider (cloud or local mode); forced by route "local"
      fallback — an OpenAI-compatible provider (OpenRouter by default); forced by
                 route "cloud"
      echo     — last-resort canned responder; only `auto` routing may reach it
    The route literals "local"/"cloud" are kept for wire compatibility even
    though the primary provider may itself be a cloud service (Ollama Cloud).
    """

    def __init__(
        self,
        primary: ChatProvider | None,
        fallback: ChatProvider | None,
        echo: ChatProvider | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.echo = echo

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        route: Literal["auto", "local", "cloud"] = "auto",
    ) -> ProviderResponse:
        providers = self._ordered(route)
        errors: list[str] = []

        for provider in providers:
            try:
                return await provider.chat(messages=messages, tools=tools)
            except ProviderError as exc:
                logger.warning("Provider %s failed: %s", provider.name, exc)
                errors.append(f"{provider.name}: {exc}")

        raise ProviderError("No provider completed the request. " + " | ".join(errors))

    def _ordered(self, route: str) -> list[ChatProvider]:
        if route == "local":
            if not self.primary:
                raise ProviderError(
                    "The primary provider (Ollama) is not configured; route 'local' requires it"
                )
            return [self.primary]
        if route == "cloud":
            if not self.fallback:
                raise ProviderError(
                    "The fallback provider (OpenRouter/OpenAI-compatible) is not "
                    "configured; route 'cloud' requires it"
                )
            return [self.fallback]

        ordered: list[ChatProvider] = []
        if self.primary:
            ordered.append(self.primary)
        if self.fallback:
            ordered.append(self.fallback)
        if self.echo:
            ordered.append(self.echo)
        if not ordered:
            raise ProviderError("No providers are configured")
        return ordered

    async def status(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for label, provider in (
            ("primary", self.primary),
            ("fallback", self.fallback),
            ("echo", self.echo),
        ):
            if provider is None:
                result[label] = {
                    "configured": False,
                    "state": "not_configured",
                    "available": False,
                }
                continue
            check = await provider.check()
            result[label] = {
                "configured": True,
                "state": check.state,
                "available": check.ok,
                "detail": check.detail,
                "provider": provider.name,
                "model": provider.model,
            }
        return result
