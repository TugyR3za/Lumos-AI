from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.core.container import LumosContainer
from app.providers.base import ProviderError
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
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
