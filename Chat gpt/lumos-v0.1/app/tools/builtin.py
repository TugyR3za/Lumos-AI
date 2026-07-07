from __future__ import annotations

from app.memory.database import Database
from app.retrieval.service import RetrievalService
from app.tools.registry import RegisteredTool, ToolRegistry
from app.web.service import WebSearchService


def build_tool_registry(
    *,
    retrieval: RetrievalService,
    web_search: WebSearchService,
    database: Database,
    allow_memory_writes: bool,
) -> ToolRegistry:
    registry = ToolRegistry()

    def search_notes(query: str, limit: int = 5):
        limit = max(1, min(limit, 10))
        rows = retrieval.search_notes(query, limit=limit)
        return [
            {
                "title": row["title"],
                "path": row["path"],
                "snippet": str(row["content"])[:1_000],
                "score": row["score"],
            }
            for row in rows
        ]

    registry.register(
        RegisteredTool(
            name="search_notes",
            description="Search the user's locally indexed notes and project files.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to find in local notes."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=search_notes,
        )
    )

    async def search_web(query: str, limit: int = 5):
        limit = max(1, min(limit, 10))
        rows = await web_search.search(query, limit=limit)
        return [
            {"title": row.title, "url": row.url, "snippet": row.snippet[:1_000]}
            for row in rows
        ]

    registry.register(
        RegisteredTool(
            name="search_web",
            description="Search the public web for current or external information.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "A focused web search query."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=search_web,
        )
    )

    if allow_memory_writes:
        def save_memory(value: str, key: str | None = None, importance: float = 0.5):
            importance = max(0.0, min(float(importance), 1.0))
            memory_id = database.save_memory(
                value,
                memory_key=key,
                importance=importance,
                source="model_tool",
            )
            return {"saved": True, "memory_id": memory_id}

        registry.register(
            RegisteredTool(
                name="save_memory",
                description=(
                    "Save a durable personal memory only when the user explicitly asks "
                    "Lumos to remember it."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "key": {"type": ["string", "null"]},
                        "importance": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                },
                handler=save_memory,
            )
        )

    return registry
