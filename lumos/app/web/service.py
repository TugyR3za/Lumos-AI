from __future__ import annotations

from app.web.base import WebResult, WebSearchProvider


class WebSearchService:
    def __init__(self, provider: WebSearchProvider | None) -> None:
        self.provider = provider

    @property
    def name(self) -> str:
        return self.provider.name if self.provider else "disabled"

    async def is_available(self) -> bool:
        return bool(self.provider and await self.provider.is_available())

    async def search(self, query: str, limit: int = 5) -> list[WebResult]:
        if not self.provider:
            return []
        return await self.provider.search(query=query, limit=limit)
