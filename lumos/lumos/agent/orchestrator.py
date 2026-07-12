from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from lumos.agent.prompts import build_system_prompt
from lumos.graph.service import GraphService
from lumos.memory.database import Database
from lumos.providers.base import ProviderResponse
from lumos.providers.echo import EchoProvider
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
        memory_top_k: int = 4,
        graph: GraphService | None = None,
    ) -> None:
        self.database = database
        self.providers = providers
        self.retrieval = retrieval
        self.web_search = web_search
        self.tools = tools
        # Held, not read: the moment context assembly consults the graph the
        # prompt changes, and that is its own slice.
        self.graph = graph
        self.history_limit = history_limit
        self.retrieval_top_k = retrieval_top_k
        self.web_search_max_results = web_search_max_results
        self.max_tool_rounds = max_tool_rounds
        self.memory_top_k = memory_top_k

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

        memory_rows = await asyncio.to_thread(
            self.database.search_memories,
            user_message,
            limit=self.memory_top_k,
        )
        memory_context = self._format_memory_context(memory_rows)

        stored = await asyncio.to_thread(
            self.database.get_messages,
            conversation_id,
            self.history_limit,
        )
        messages: list[dict[str, object]] = [
            {
                "role": "system",
                "content": build_system_prompt(note_context, web_context, memory_context),
            }
        ]
        messages.extend(
            {"role": item["role"], "content": item["content"]}
            for item in stored
            if item["role"] in {"user", "assistant"}
        )

        tool_events: list[dict[str, object]] = []
        response: ProviderResponse | None = None

        for _ in range(self.max_tool_rounds):
            candidate = await self.providers.chat(
                messages=messages,
                tools=self.tools.schemas(),
                route=route,
            )
            if not candidate.tool_calls:
                response = candidate
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": candidate.content,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "arguments": call.arguments}
                        for call in candidate.tool_calls
                    ],
                }
            )

            for call in candidate.tool_calls:
                event: dict[str, object]
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
        if response is None:
            # Tool budget exhausted (or tools disabled): ask once more without
            # offering tools so the user still gets a plain final answer.
            response = await self.providers.chat(messages=messages, tools=None, route=route)

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

        # The echo fallback never reads the gathered context, so citing notes or
        # web results under its canned reply would misrepresent them as used.
        sources: list[SourceItem] = []
        if response.provider != EchoProvider.name:
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
    def _format_memory_context(rows: list[dict[str, object]]) -> str:
        lines = []
        for row in rows:
            key = row.get("memory_key")
            prefix = f"{key}: " if key else ""
            lines.append(f"- {prefix}{row['value']}")
        return "\n".join(lines)

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
