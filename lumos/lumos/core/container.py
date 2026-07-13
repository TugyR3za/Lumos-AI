from __future__ import annotations

import logging
from dataclasses import dataclass

from lumos.agent.orchestrator import AgentOrchestrator
from lumos.config import Settings
from lumos.graph.service import GraphService
from lumos.memory.database import Database
from lumos.notes.ingestor import NotesIngestor
from lumos.providers.echo import EchoProvider
from lumos.providers.ollama import OllamaProvider
from lumos.providers.openai_compatible import OpenAICompatibleProvider
from lumos.providers.router import ProviderRouter
from lumos.retrieval.service import RetrievalService
from lumos.tools.builtin import build_tool_registry
from lumos.tools.registry import ToolRegistry
from lumos.web.ddgs_provider import DDGSSearchProvider
from lumos.web.searxng import SearxNGSearchProvider
from lumos.web.service import WebSearchService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LumosContainer:
    settings: Settings
    database: Database
    ingestor: NotesIngestor
    retrieval: RetrievalService
    graph: GraphService
    web_search: WebSearchService
    providers: ProviderRouter
    tools: ToolRegistry
    agent: AgentOrchestrator


def build_container(settings: Settings) -> LumosContainer:
    database = Database(settings.resolved_database_path)
    database.initialize()

    graph = GraphService(
        database,
        enabled=settings.graph_enabled,
        max_related=settings.graph_max_related,
        max_neighbors=settings.graph_max_neighbors,
    )
    if settings.graph_expand_retrieval and not settings.graph_enabled:
        # A silent no-op is worse than either answer: say which flag is winning.
        logger.warning(
            "LUMOS_GRAPH_EXPAND_RETRIEVAL is on but LUMOS_GRAPH_ENABLED is off, "
            "so graph reads are disabled and retrieval expansion does nothing."
        )
    retrieval = RetrievalService(
        database,
        graph=graph,
        expand=settings.graph_expand_retrieval,
        max_linked=settings.graph_expand_max_notes,
        max_linked_chars=settings.graph_expand_max_chars,
        score_floor=settings.retrieval_score_floor,
    )
    ingestor = NotesIngestor(
        database,
        settings.resolved_notes_path,
        max_file_bytes=settings.notes_max_file_bytes,
        chunk_size_chars=settings.chunk_size_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
    )

    web_provider = None
    if settings.web_search_provider != "disabled":
        if settings.web_search_provider == "searxng" or (
            settings.web_search_provider == "auto" and settings.searxng_base_url
        ):
            if not settings.searxng_base_url:
                raise ValueError("LUMOS_SEARXNG_BASE_URL is required for the SearxNG provider")
            web_provider = SearxNGSearchProvider(settings.searxng_base_url)
        else:
            web_provider = DDGSSearchProvider()
    web_search = WebSearchService(web_provider)

    primary_provider = None
    if settings.ollama_enabled:
        ollama_key = (
            settings.ollama_api_key_value if settings.ollama_mode == "cloud" else None
        )
        # Cloud mode without a key means Ollama is simply not configured yet;
        # the router then falls through to the fallback provider, then echo.
        if settings.ollama_mode == "local" or ollama_key:
            primary_provider = OllamaProvider(
                settings.resolved_ollama_base_url,
                settings.resolved_ollama_model,
                settings.request_timeout_seconds,
                api_key=ollama_key,
            )

    fallback_provider = None
    if settings.cloud_enabled and settings.cloud_api_key_value:
        fallback_provider = OpenAICompatibleProvider(
            settings.cloud_base_url,
            settings.cloud_api_key_value,
            settings.cloud_model,
            settings.request_timeout_seconds,
        )

    echo_provider = EchoProvider() if settings.echo_fallback else None
    providers = ProviderRouter(
        primary=primary_provider,
        fallback=fallback_provider,
        echo=echo_provider,
    )
    tools = build_tool_registry(
        retrieval=retrieval,
        web_search=web_search,
        database=database,
        allow_memory_writes=settings.allow_model_memory_writes,
    )
    agent = AgentOrchestrator(
        database=database,
        providers=providers,
        retrieval=retrieval,
        web_search=web_search,
        tools=tools,
        history_limit=settings.conversation_history_limit,
        retrieval_top_k=settings.retrieval_top_k,
        web_search_max_results=settings.web_search_max_results,
        max_tool_rounds=settings.max_tool_rounds,
        memory_top_k=settings.memory_top_k,
    )
    return LumosContainer(
        settings=settings,
        database=database,
        ingestor=ingestor,
        retrieval=retrieval,
        graph=graph,
        web_search=web_search,
        providers=providers,
        tools=tools,
        agent=agent,
    )
