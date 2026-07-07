"""One factory that wires the whole app together from config.

Both the CLI and the web UI call `build_app()` so they share exactly the same
assembled system. This is the single place that knows which concrete class fills
each role — swap an implementation here and the rest of the app follows.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config, load_config
from .core.assistant import Assistant, DEFAULT_SYSTEM_PROMPT
from .memory.sqlite_store import SQLiteMemory
from .providers.router import Router
from .rag.embedder import get_embedder
from .rag.ingest import NotesIngestor
from .rag.retriever import Retriever
from .rag.store import NumpyVectorStore
from .tools.notes_search import NotesSearchTool
from .tools.registry import ToolRegistry
from .tools.web_search import WebSearchTool


@dataclass
class App:
    """Container holding every live subsystem, so UIs can reach any of them."""

    config: Config
    assistant: Assistant
    router: Router
    memory: SQLiteMemory
    ingestor: NotesIngestor
    retriever: Retriever
    tools: ToolRegistry

    def reindex(self, force: bool = False) -> dict:
        return self.ingestor.ingest(force=force)


def build_app(config_file: str | None = None) -> App:
    config = load_config(config_file)

    # Model routing (local -> cloud -> echo).
    router = Router(config)

    # Memory.
    memory = SQLiteMemory(config.db_path)

    # RAG: embedder + vector store + retriever + ingestor.
    embedder = get_embedder(config)
    store = NumpyVectorStore(config.vector_path)
    retriever = Retriever(embedder, store)
    ingestor = NotesIngestor(config.notes_dir, embedder, store)

    # Tools.
    tools = ToolRegistry()
    tools.register(WebSearchTool(api_key=config.tavily_api_key))
    tools.register(NotesSearchTool(retriever))

    assistant = Assistant(
        router=router,
        memory=memory,
        tools=tools,
        system_prompt=config.get("assistant.system_prompt") or DEFAULT_SYSTEM_PROMPT,
        max_tool_rounds=config.get("assistant.max_tool_rounds", 4),
        history_limit=config.get("assistant.history_limit", 12),
    )

    return App(
        config=config,
        assistant=assistant,
        router=router,
        memory=memory,
        ingestor=ingestor,
        retriever=retriever,
        tools=tools,
    )
