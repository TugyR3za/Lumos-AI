"""Query-time retrieval over ingested notes."""

from __future__ import annotations

from .base import Embedder, Hit, VectorStore


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self.embedder = embedder
        self.store = store

    def retrieve(self, query: str, k: int = 4) -> list[Hit]:
        if self.store.count() == 0:
            return []
        vec = self.embedder.embed([query])[0]
        return self.store.search(vec, k=k)

    def as_context(self, query: str, k: int = 4) -> str:
        """Format hits as a compact block to hand to the model."""
        hits = self.retrieve(query, k=k)
        if not hits:
            return ""
        lines = []
        for h in hits:
            src = h.metadata.get("source", "note")
            lines.append(f"[{src}] {h.text.strip()}")
        return "\n\n".join(lines)
