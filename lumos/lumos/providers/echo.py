from __future__ import annotations

from lumos.providers.base import Message, ProviderCheck, ProviderResponse, ToolSchema


class EchoProvider:
    """Last-resort fallback so Lumos can always answer, even with no model set up.

    It does not think: it repeats the message and explains how to connect a real
    model. The router only reaches it in `auto` mode after every configured
    provider has failed, so a fresh install still gets a useful response instead
    of an error page.
    """

    name = "echo"
    model = "echo-fallback"

    async def check(self) -> ProviderCheck:
        return ProviderCheck("available")

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
            "To get real answers, set one of these in your `.env` and send your "
            "message again:\n"
            "- LUMOS_OLLAMA_API_KEY — Ollama Cloud key (default mode, no downloads)\n"
            "- LUMOS_CLOUD_API_KEY — OpenRouter (or compatible) fallback key\n\n"
            "Or go fully local: LUMOS_OLLAMA_MODE=local, install Ollama, and "
            "`ollama pull qwen3:1.7b`."
        )
        return ProviderResponse(content=text, provider=self.name, model=self.model)
