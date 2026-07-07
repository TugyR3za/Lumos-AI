from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from lumos.agent.prompts import build_system_prompt
from lumos.memory.database import Database
from lumos.providers.base import ProviderResponse
from lumos.providers.router import ProviderRouter
from lumos.retrieval.service import RetrievalService
from lumos.schemas import ChatResponse, SourceItem
from lumos.tools.registry import ToolRegistry
from lumos.web.service import WebSearchService

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(
        self,
        *,
        database: Database,
        providers: ProviderRouter,
        retrieval: RetrievalService,
        web_search: WebSearchService,
        tools: ToolRegistry,
        history_limit: int,
        retrieval_top_k: int,
        web_search_max_results: int,
        max_tool_rounds: int,
    ) -> None:
        self.database = database
        self.providers = providers
        self.retrieval = retrieval
        self.web_search = web_search
        self.tools = tools
        self.history_limit = history_limit
        self.retrieval_top_k = retrieval_top_k
        self.web_search_max_results = web_search_max_results
        self.max_tool_rounds = max_tool_rounds

    async def chat(
        self,
        *,
        user_message: str,
        conversation_id: str | None,
        route: Literal["auto", "local", "cloud"],
        use_notes: bool,
        use_web: bool,
    ) -> ChatResponse:
        conversation_id = await asyncio.to_thread(
            self.database.create_conversation, conversation_id
        )
        await asyncio.to_thread(
            self.database.add_message,
            conversation_id,
            "user",
            user_message,
        )

        note_rows = (
            await asyncio.to_thread(
                self.retrieval.search_notes,
                user_message,
                self.retrieval_top_k,
            )
            if use_notes
            else []
        )
        note_context = self.retrieval.format_context(note_rows)

        web_rows = []
        if use_web:
            try:
                web_rows = await self.web_search.search(
                    user_message, limit=self.web_search_max_results
                )
            except Exception as exc:  # Search must not take the whole chat down.
                logger.warning("Proactive web search failed: %s", exc)
        web_context = self._format_web_context(web_rows)

        stored = await asyncio.to_thread(
            self.database.get_messages,
            conversation_id,
            self.history_limit,
        )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": build_system_prompt(note_context, web_context)}
        ]
        messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in stored
            if item["role"] in {"user", "assistant"}
        )

        tool_events: list[dict[str, object]] = []
        response: ProviderResponse | None = None

        for _ in range(self.max_tool_rounds + 1):
            response = await self.providers.chat(
                messages=messages,
                tools=self.tools.schemas(),
                route=route,
            )
            if not response.tool_calls:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "arguments": call.arguments}
                        for call in response.tool_calls
                    ],
                }
            )

            for call in response.tool_calls:
                try:
                    result = await self.tools.execute(call.name, call.arguments)
                    event = {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "ok": True,
                        "result": result,
                    }
                except Exception as exc:
                    result = {"error": str(exc)}
                    event = {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "ok": False,
                        "error": str(exc),
                    }
                tool_events.append(event)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:
            raise RuntimeError("Tool loop exceeded its configured limit")

        if response is None:
            raise RuntimeError("Provider returned no response")

        answer = response.content.strip() or "I could not produce a text response."
        await asyncio.to_thread(
            self.database.add_message,
            conversation_id,
            "assistant",
            answer,
            response.provider,
            response.model,
            {"tool_events": tool_events},
        )

        sources = [
            SourceItem(
                kind="note",
                title=str(row["title"]),
                location=str(row["path"]),
                snippet=str(row["content"])[:400],
                score=float(row["score"]),
            )
            for row in note_rows
        ]
        sources.extend(
            SourceItem(
                kind="web",
                title=row.title,
                location=row.url,
                snippet=row.snippet[:400],
            )
            for row in web_rows
        )
        self._add_tool_sources(sources, tool_events)

        return ChatResponse(
            conversation_id=conversation_id,
            answer=answer,
            provider=response.provider,
            model=response.model,
            sources=sources,
            tool_events=tool_events,
        )

    @staticmethod
    def _format_web_context(rows) -> str:
        blocks = []
        for index, row in enumerate(rows, start=1):
            blocks.append(f"[WEB {index}] {row.title}\nURL: {row.url}\n{row.snippet}")
        return "\n\n".join(blocks)

    @staticmethod
    def _add_tool_sources(
        sources: list[SourceItem], tool_events: list[dict[str, object]]
    ) -> None:
        existing = {(source.kind, source.location) for source in sources}
        for event in tool_events:
            if not event.get("ok") or not isinstance(event.get("result"), list):
                continue
            kind = "web" if event.get("tool") == "search_web" else "note"
            for item in event["result"]:
                if not isinstance(item, dict):
                    continue
                location = str(item.get("url") or item.get("path") or "")
                key = (kind, location)
                if not location or key in existing:
                    continue
                sources.append(
                    SourceItem(
                        kind=kind,
                        title=str(item.get("title") or "Source"),
                        location=location,
                        snippet=str(item.get("snippet") or "")[:400],
                        score=item.get("score"),
                    )
                )
                existing.add(key)
