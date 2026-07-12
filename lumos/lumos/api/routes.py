from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from lumos.core.container import LumosContainer
from lumos.graph.service import GRAPH_DISABLED_DETAIL, GraphNode
from lumos.providers.base import ProviderError
from lumos.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    GraphNeighborItem,
    GraphNodeItem,
    GraphRelatedItem,
    GraphResponse,
    HealthResponse,
    MessageItem,
    ReindexResponse,
    SearchRequest,
    SourceItem,
)

router = APIRouter(prefix="/api")


def container_from(request: Request) -> LumosContainer:
    return request.app.state.container


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    container = container_from(request)
    return HealthResponse(
        status="ok",
        database=str(container.settings.resolved_database_path),
        notes_path=str(container.settings.resolved_notes_path),
        providers=await container.providers.status(),
        web_search={
            "provider": container.web_search.name,
            "available": await container.web_search.is_available(),
        },
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    container = container_from(request)
    try:
        return await container.agent.chat(
            user_message=payload.message,
            conversation_id=payload.conversation_id,
            route=payload.route,
            use_notes=payload.use_notes,
            use_web=payload.use_web,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def conversation(conversation_id: str, request: Request) -> ConversationResponse:
    container = container_from(request)
    rows = await asyncio.to_thread(
        container.database.get_messages,
        conversation_id,
        200,
    )
    return ConversationResponse(
        conversation_id=conversation_id,
        messages=[
            MessageItem(
                role=row["role"],
                content=row["content"],
                provider=row["provider"],
                model=row["model"],
                created_at=row["created_at"],
            )
            for row in rows
        ],
    )


@router.post("/notes/reindex", response_model=ReindexResponse)
async def reindex_notes(request: Request) -> ReindexResponse:
    container = container_from(request)
    stats = await asyncio.to_thread(container.ingestor.ingest_all)
    return ReindexResponse(
        scanned=stats.scanned,
        indexed=stats.indexed,
        skipped=stats.skipped,
        removed=stats.removed,
        chunks=stats.chunks,
    )


@router.post("/search/notes", response_model=list[SourceItem])
async def search_notes(payload: SearchRequest, request: Request) -> list[SourceItem]:
    container = container_from(request)
    rows = await asyncio.to_thread(
        container.retrieval.search_notes,
        payload.query,
        payload.limit,
    )
    return [
        SourceItem(
            kind="note",
            title=str(row["title"]),
            location=str(row["path"]),
            snippet=str(row["content"])[:600],
            score=float(row["score"]),
        )
        for row in rows
    ]


@router.get("/graph", response_model=GraphResponse)
async def graph(
    request: Request,
    slug: str | None = None,
    path: Annotated[list[str] | None, Query()] = None,
) -> GraphResponse:
    """One hop around the note graph.

    A *centre* — `slug`, or a lone `path` — comes back as `node` plus its
    `neighbors` (links, backlinks, tags, mentions). Every `path` given, however
    many, is a seed for `related`: the notes one link away from the seed set,
    which is what a graph-aware retrieval would pull in.
    """
    container = container_from(request)
    service = container.graph
    if not service.enabled:
        return GraphResponse(enabled=False, detail=GRAPH_DISABLED_DETAIL)

    paths = path or []
    if not slug and not paths:
        raise HTTPException(status_code=400, detail="Pass slug=<node> or path=<note path>.")

    centre: GraphNode | None = None
    if slug:
        centre = await asyncio.to_thread(service.node, slug)
    elif len(paths) == 1:
        centre = await asyncio.to_thread(service.note_for_path, paths[0])

    neighbors: list[GraphNeighborItem] = []
    if centre is not None:
        neighbors = [
            GraphNeighborItem(
                node=_graph_node_item(neighbor.node),
                rel=neighbor.rel,
                direction=neighbor.direction,
            )
            for neighbor in await asyncio.to_thread(service.neighbors, centre.slug)
        ]

    related = [
        GraphRelatedItem(
            slug=note.slug,
            title=note.title,
            path=note.path,
            connections=note.connections,
            via=list(note.via),
        )
        for note in await asyncio.to_thread(service.related_notes, paths)
    ]

    detail = None
    if centre is None and (slug or len(paths) == 1):
        detail = f"No graph node for {slug or paths[0]!r}."
    return GraphResponse(
        enabled=True,
        detail=detail,
        node=_graph_node_item(centre) if centre else None,
        neighbors=neighbors,
        related=related,
    )


def _graph_node_item(node: GraphNode) -> GraphNodeItem:
    return GraphNodeItem(kind=node.kind, slug=node.slug, title=node.title, path=node.path)


@router.post("/search/web", response_model=list[SourceItem])
async def search_web(payload: SearchRequest, request: Request) -> list[SourceItem]:
    container = container_from(request)
    try:
        rows = await container.web_search.search(payload.query, payload.limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Web search failed: {exc}") from exc
    return [
        SourceItem(
            kind="web",
            title=row.title,
            location=row.url,
            snippet=row.snippet[:600],
        )
        for row in rows
    ]
