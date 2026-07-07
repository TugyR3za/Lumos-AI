"""A zero-dependency, always-available fallback provider.

It doesn't think — it just echoes and reports what it received. Its only job is
to let you run the whole pipeline (UI -> router -> memory -> RAG -> tools) end to
end before you've installed a model or added an API key. Replace it the moment
Ollama or Groq is available; the router does that automatically.
"""

from __future__ import annotations

from typing import Any

from ..core.schemas import ChatResponse, Message
from .base import ChatProvider


class EchoProvider(ChatProvider):
    name = "echo"
    kind = "local"

    def __init__(self, model: str = "echo-dev", **options: Any) -> None:
        super().__init__(model, **options)

    def is_available(self) -> bool:
        return True

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        tool_names = ", ".join(t["function"]["name"] for t in (tools or [])) or "none"
        text = (
            "[echo provider — no model connected yet]\n"
            f"You said: {last_user}\n"
            f"Tools I could call once a real model is connected: {tool_names}.\n"
            "Install Ollama or set GROQ_API_KEY to get real answers."
        )
        return ChatResponse(content=text, provider=self.name, model=self.model)
