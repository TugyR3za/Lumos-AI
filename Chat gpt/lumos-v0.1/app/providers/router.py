from __future__ import annotations

import logging
from typing import Literal

from app.providers.base import ChatProvider, Message, ProviderError, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)


class ProviderRouter:
    """Routes requests without leaking provider-specific code into the agent."""

    def __init__(
        self,
        local: ChatProvider | None,
        cloud: ChatProvider | None,
    ) -> None:
        self.local = local
        self.cloud = cloud

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
            if not self.local:
                raise ProviderError("Local provider is not configured")
            return [self.local]
        if route == "cloud":
            if not self.cloud:
                raise ProviderError("Cloud provider is not configured")
            return [self.cloud]

        ordered: list[ChatProvider] = []
        if self.local:
            ordered.append(self.local)
        if self.cloud:
            ordered.append(self.cloud)
        if not ordered:
            raise ProviderError("No providers are configured")
        return ordered

    async def status(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for label, provider in (("local", self.local), ("cloud", self.cloud)):
            if provider is None:
                result[label] = {"configured": False, "available": False}
                continue
            result[label] = {
                "configured": True,
                "available": await provider.is_available(),
                "provider": provider.name,
                "model": provider.model,
            }
        return result
