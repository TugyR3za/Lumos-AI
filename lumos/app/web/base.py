from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class WebResult:
    title: str
    url: str
    snippet: str


class WebSearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int = 5) -> list[WebResult]: ...

    async def is_available(self) -> bool: ...
