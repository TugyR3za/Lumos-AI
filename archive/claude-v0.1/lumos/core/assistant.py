"""The Assistant: the conductor that wires every subsystem together.

One public method, `ask()`, does the full turn:
  1. load recent history + relevant long-term facts from memory
  2. assemble the message list (system prompt + context + history + new turn)
  3. call the router (local model, else cloud, else echo) with the tool schemas
  4. run any tools the model asked for, feed results back, and loop
  5. persist the exchange to memory and return the final answer

Every collaborator is injected, so tests and future UIs can swap any part.
"""

from __future__ import annotations

from ..memory.base import MemoryStore
from ..providers.router import Router
from ..tools.registry import ToolRegistry
from .schemas import Message

DEFAULT_SYSTEM_PROMPT = (
    "You are Lumos, a private and helpful personal assistant for a family. "
    "You are warm, direct, and concise. You can call tools to search the web "
    "and the user's private notes. Prefer the user's notes for personal or "
    "project questions, and web search for current facts. If you use a tool, "
    "base your answer on its results. You understand English, Farsi, and Turkish."
)


class Assistant:
    def __init__(
        self,
        router: Router,
        memory: MemoryStore,
        tools: ToolRegistry,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tool_rounds: int = 4,
        history_limit: int = 12,
    ) -> None:
        self.router = router
        self.memory = memory
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_tool_rounds = max_tool_rounds
        self.history_limit = history_limit

    def _build_messages(self, session: str, user_text: str) -> list[Message]:
        messages: list[Message] = [Message(role="system", content=self.system_prompt)]

        # Long-term facts relevant to this question.
        facts = self.memory.search_facts(user_text, limit=5)
        if facts:
            block = "\n".join(f"- {f['text']}" for f in facts)
            messages.append(
                Message(role="system", content=f"Known facts about the user:\n{block}")
            )

        # Recent conversation history.
        messages.extend(self.memory.recent_messages(session, limit=self.history_limit))
        # The new user turn.
        messages.append(Message(role="user", content=user_text))
        return messages

    def ask(self, user_text: str, session: str = "default", prefer: str | None = None) -> str:
        """Run one full turn and return the assistant's final text."""
        self.memory.add_message(session, Message(role="user", content=user_text))
        messages = self._build_messages(session, user_text)
        tool_schemas = self.tools.schemas() or None

        final_text = ""
        for _ in range(self.max_tool_rounds):
            response = self.router.chat(messages, tools=tool_schemas, prefer=prefer)

            if not response.wants_tools:
                final_text = response.content
                break

            # Record the assistant's tool-call turn.
            messages.append(
                Message(role="assistant", content=response.content, tool_calls=response.tool_calls)
            )
            # Execute each requested tool and feed the result back.
            for call in response.tool_calls:
                result = self.tools.run(call.name, call.arguments)
                messages.append(
                    Message(
                        role="tool",
                        content=result,
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
        else:
            # Ran out of tool rounds — ask once more for a plain answer.
            response = self.router.chat(messages, tools=None, prefer=prefer)
            final_text = response.content

        self.memory.add_message(session, Message(role="assistant", content=final_text))
        return final_text

    def remember(self, text: str) -> int:
        """Store a durable fact the user wants kept."""
        return self.memory.add_fact(text, source="user")
