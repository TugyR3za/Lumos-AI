from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    kind: Literal["note", "web"]
    title: str
    location: str
    snippet: str
    score: float | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=50_000)
    conversation_id: str | None = None
    route: Literal["auto", "local", "cloud"] = "auto"
    use_notes: bool = True
    use_web: bool = False


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    provider: str
    model: str
    sources: list[SourceItem] = Field(default_factory=list)
    tool_events: list[dict[str, Any]] = Field(default_factory=list)


class MessageItem(BaseModel):
    role: str
    content: str
    provider: str | None = None
    model: str | None = None
    created_at: str


class ConversationResponse(BaseModel):
    conversation_id: str
    messages: list[MessageItem]


class ReindexResponse(BaseModel):
    scanned: int
    indexed: int
    skipped: int
    removed: int
    chunks: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=5, ge=1, le=20)


class HealthResponse(BaseModel):
    status: str
    database: str
    notes_path: str
    providers: dict[str, dict[str, Any]]
    web_search: dict[str, Any]
