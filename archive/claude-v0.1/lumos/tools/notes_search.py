"""Expose the notes retriever as a tool the model can call on demand.

This makes RAG *agentic*: instead of always stuffing notes into the prompt, the
model decides when your personal notes are relevant and searches them itself.
"""

from __future__ import annotations

from ..rag.retriever import Retriever
from .base import Tool


class NotesSearchTool(Tool):
    name = "search_notes"
    description = (
        "Search the user's private notes and documents for personal or "
        "project-specific information. Use when the question refers to the "
        "user's own files, notes, plans, or past decisions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for in the notes."},
            "k": {"type": "integer", "description": "How many passages (1-6).", "default": 4},
        },
        "required": ["query"],
    }

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    def run(self, query: str, k: int = 4) -> str:
        hits = self.retriever.retrieve(query, k=max(1, min(int(k), 6)))
        if not hits:
            return "No matching notes found."
        lines = ["Relevant notes:"]
        for h in hits:
            src = h.metadata.get("source", "note")
            lines.append(f"- [{src}] {h.text.strip()}")
        return "\n".join(lines)
