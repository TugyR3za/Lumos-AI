"""The memory contract.

Swap SQLite for Postgres, Redis, or a vector-backed store later by implementing
this interface — the Assistant only ever calls these methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.schemas import Message


class MemoryStore(ABC):
    @abstractmethod
    def add_message(self, session: str, message: Message) -> None:
        """Persist one conversation turn."""

    @abstractmethod
    def recent_messages(self, session: str, limit: int = 20) -> list[Message]:
        """Return the last `limit` turns for a session, oldest first."""

    @abstractmethod
    def add_fact(self, text: str, source: str = "user", tags: str = "") -> int:
        """Store a durable fact/memory. Returns its id."""

    @abstractmethod
    def search_facts(self, query: str, limit: int = 5) -> list[dict]:
        """Find facts relevant to a query (keyword match in v0.1)."""

    @abstractmethod
    def close(self) -> None:
        ...
