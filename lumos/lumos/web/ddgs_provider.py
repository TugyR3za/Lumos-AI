from __future__ import annotations

import asyncio

from ddgs import DDGS

from lumos.web.base import WebResult


class DDGSSearchProvider:
    name = "ddgs"

    async def is_available(self) -> bool:
        return True

    async def search(self, query: str, limit: int = 5) -> list[WebResult]:
        def _search() -> list[WebResult]:
            rows = DDGS().text(query, max_results=limit)
            return [
                WebResult(
                    title=str(row.get("title") or row.get("heading") or "Untitled"),
                    url=str(row.get("href") or row.get("url") or ""),
                    snippet=str(row.get("body") or row.get("snippet") or ""),
                )
                for row in rows
                if row.get("href") or row.get("url")
            ]

        return await asyncio.to_thread(_search)
