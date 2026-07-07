from __future__ import annotations

from app.providers.base import Message, ProviderResponse, ToolSchema


class MockProvider:
    name = "mock"
    model = "mock-echo"

    async def is_available(self) -> bool:
        return True

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return ProviderResponse(
            content=f"Mock Lumos response: {last}",
            provider=self.name,
            model=self.model,
        )
