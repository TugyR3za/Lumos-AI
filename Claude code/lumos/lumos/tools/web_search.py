"""Web search via the Tavily API (free tier available).

Tavily returns clean, LLM-friendly results in one call. Without a key the tool
stays registered but returns a helpful setup message, so the rest of the system
keeps working. Swap in another search backend by editing only this file.
"""

from __future__ import annotations

import requests

from .base import Tool


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the public web for current or factual information the assistant "
        "does not already know. Use for news, prices, recent events, or lookups."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "description": "How many results to return (1-5).",
                "default": 3,
            },
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str | None = None, timeout: int = 20) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def run(self, query: str, max_results: int = 3) -> str:
        if not self.api_key:
            return (
                "[web_search unavailable] Set TAVILY_API_KEY in your .env to enable "
                "web search (free key at tavily.com)."
            )
        try:
            r = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max(1, min(int(max_results), 5)),
                    "search_depth": "basic",
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            return f"[web_search error] {e}"

        results = data.get("results", [])
        if not results:
            return f"No results found for: {query}"
        lines = [f"Search results for '{query}':"]
        for i, res in enumerate(results, 1):
            title = res.get("title", "").strip()
            url = res.get("url", "")
            content = (res.get("content", "") or "").strip()
            lines.append(f"{i}. {title}\n   {content}\n   Source: {url}")
        return "\n".join(lines)
