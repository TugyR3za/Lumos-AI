from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Message = dict[str, Any]
ToolSchema = dict[str, Any]

CheckState = Literal["available", "reachable", "auth_failed", "unreachable", "error"]


@dataclass(slots=True)
class ProviderCheck:
    """Structured probe result: what we actually know about a provider.

    `available` means the probe verified the provider end to end (including
    auth where the endpoint enforces it). `reachable` means the endpoint
    answered but the probe could not verify the API key, so a chat may still
    fail with an auth error.
    """

    state: CheckState
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.state in ("available", "reachable")


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ProviderResponse:
    content: str
    provider: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class ProviderAuthError(ProviderError):
    """The provider rejected our credentials (HTTP 401/403) — almost always a
    missing, mistyped, or expired API key rather than an outage."""


class ChatProvider(Protocol):
    name: str
    model: str

    async def check(self) -> ProviderCheck: ...

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse: ...
