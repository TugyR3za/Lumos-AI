"""Chooses which provider handles a given turn.

Policy (all configurable in config.yaml):
- "local"   : prefer the on-device model, fall back to cloud, then echo.
- "cloud"   : prefer the cloud model, fall back to local, then echo.
- "<name>"  : force a specific provider by name.

The router probes availability lazily and caches the result for the session so
it doesn't hammer the network. Call `route(prefer=...)` per turn to override.
"""

from __future__ import annotations

from ..config import Config
from ..core.schemas import ChatResponse, Message
from .base import ChatProvider
from .echo_provider import EchoProvider
from .groq_provider import GroqProvider
from .ollama_provider import OllamaProvider


class Router:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.default_policy = config.get("router.prefer", "local")
        self._providers: dict[str, ChatProvider] = self._build(config)
        self._availability: dict[str, bool] = {}

    def _build(self, cfg: Config) -> dict[str, ChatProvider]:
        return {
            "ollama": OllamaProvider(
                model=cfg.get("providers.ollama.model", "qwen2.5:3b"),
                host=cfg.get("providers.ollama.host", "http://localhost:11434"),
            ),
            "groq": GroqProvider(
                model=cfg.get("providers.groq.model", "llama-3.3-70b-versatile"),
                api_key=cfg.groq_api_key,
            ),
            "echo": EchoProvider(),
        }

    def available(self, name: str) -> bool:
        if name not in self._availability:
            prov = self._providers.get(name)
            self._availability[name] = bool(prov and prov.is_available())
        return self._availability[name]

    def route(self, prefer: str | None = None) -> ChatProvider:
        """Return the provider to use for this turn."""
        policy = prefer or self.default_policy

        # Forced provider by name.
        if policy in self._providers and policy not in ("local", "cloud"):
            if self.available(policy):
                return self._providers[policy]

        order = {
            "local": ["ollama", "groq", "echo"],
            "cloud": ["groq", "ollama", "echo"],
        }.get(policy, ["ollama", "groq", "echo"])

        for name in order:
            if self.available(name):
                return self._providers[name]
        return self._providers["echo"]  # guaranteed available

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        prefer: str | None = None,
        **kwargs,
    ) -> ChatResponse:
        return self.route(prefer).chat(messages, tools=tools, **kwargs)

    def status(self) -> dict[str, str]:
        """Human-readable availability map for the UI."""
        out = {}
        for name, prov in self._providers.items():
            out[name] = (
                f"{'available' if self.available(name) else 'offline'} "
                f"({prov.kind}, {prov.model})"
            )
        return out
