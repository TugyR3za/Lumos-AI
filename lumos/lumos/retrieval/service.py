from __future__ import annotations

from lumos.memory.database import Database


class RetrievalService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def search_notes(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        return self.database.search_chunks(query=query, limit=limit)

    @staticmethod
    def format_context(results: list[dict[str, object]]) -> str:
        if not results:
            return ""
        blocks = []
        for index, result in enumerate(results, start=1):
            blocks.append(
                f"[NOTE {index}] {result['title']} ({result['path']})\n{result['content']}"
            )
        return "\n\n".join(blocks)
