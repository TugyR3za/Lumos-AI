from __future__ import annotations

import httpx

from lumos.web.base import WebResult


class SearxNGSearchProvider:
    name = "searxng"

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(self.base_url)
                return response.is_success
        except httpx.HTTPError:
            return False

    async def search(self, query: str, limit: int = 5) -> list[WebResult]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json"},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        rows = response.json().get("results", [])[:limit]
        return [
            WebResult(
                title=str(row.get("title") or "Untitled"),
                url=str(row.get("url") or ""),
                snippet=str(row.get("content") or ""),
            )
            for row in rows
            if row.get("url")
        ]
