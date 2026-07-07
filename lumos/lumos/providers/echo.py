from __future__ import annotations

from lumos.providers.base import Message, ProviderResponse, ToolSchema


class EchoProvider:
    """Last-resort fallback so Lumos can always answer, even with no model set up.

    It does not think: it repeats the message and explains how to connect a real
    model. The router only reaches it in `auto` mode after every configured
    provider has failed, so a fresh install still gets a useful response instead
    of an error page.
    """

    name = "echo"
    model = "echo-fallback"

    async def is_available(self) -> bool:
        return True

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        last_user = next(
            (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        text = (
            "No AI model is reachable right now, so this is Lumos's built-in echo "
            "fallback speaking.\n\n"
            f"You said: {last_user}\n\n"
            "To get real answers, either start Ollama and pull a small model "
            "(for example `ollama pull qwen3:1.7b`), or set LUMOS_CLOUD_API_KEY "
            "in your `.env`, then send your message again."
        )
        return ProviderResponse(content=text, provider=self.name, model=self.model)
