"""The contract every model backend must satisfy.

Add a new backend (vLLM, llama.cpp, OpenAI, Gemini, ...) by subclassing
`ChatProvider` and implementing three methods. Nothing else in the codebase
needs to change — the router discovers providers through this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.schemas import ChatResponse, Message


class ChatProvider(ABC):
    """A source of chat completions (local or cloud)."""

    #: Short id used in config and logs, e.g. "ollama", "groq".
    name: str = "base"
    #: "local" or "cloud" — the router uses this to prefer on-device first.
    kind: str = "local"

    def __init__(self, model: str, **options: Any) -> None:
        self.model = model
        self.options = options

    @abstractmethod
    def is_available(self) -> bool:
        """True if this provider can actually be reached right now."""

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send messages (and optional tool schemas), return one response."""

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{self.__class__.__name__} model={self.model!r}>"
