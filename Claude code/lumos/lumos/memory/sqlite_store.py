"""SQLite memory: conversation turns + long-term facts.

SQLite is a single file, needs no server, and is plenty for a family-sized
assistant. Facts use a keyword search in v0.1; you can upgrade `search_facts`
to embeddings later without touching callers.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..core.schemas import Message, ToolCall
from .base import MemoryStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    tool_calls TEXT,
    name       TEXT,
    ts         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session, id);

CREATE TABLE IF NOT EXISTS facts (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    text   TEXT NOT NULL,
    source TEXT,
    tags   TEXT,
    ts     REAL NOT NULL
);
"""


class SQLiteMemory(MemoryStore):
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- conversation history ---
    def add_message(self, session: str, message: Message) -> None:
        tool_calls = (
            json.dumps([{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in message.tool_calls])
            if message.tool_calls else None
        )
        self.conn.execute(
            "INSERT INTO messages (session, role, content, tool_calls, name, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session, message.role, message.content, tool_calls, message.name, time.time()),
        )
        self.conn.commit()

    def recent_messages(self, session: str, limit: int = 20) -> list[Message]:
        rows = self.conn.execute(
            "SELECT * FROM (SELECT * FROM messages WHERE session = ? "
            "ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
            (session, limit),
        ).fetchall()
        out: list[Message] = []
        for r in rows:
            tcs = []
            if r["tool_calls"]:
                for t in json.loads(r["tool_calls"]):
                    tcs.append(ToolCall(id=t["id"], name=t["name"], arguments=t["arguments"]))
            out.append(
                Message(role=r["role"], content=r["content"], tool_calls=tcs, name=r["name"])
            )
        return out

    # --- long-term facts ---
    def add_fact(self, text: str, source: str = "user", tags: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO facts (text, source, tags, ts) VALUES (?, ?, ?, ?)",
            (text, source, tags, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def search_facts(self, query: str, limit: int = 5) -> list[dict]:
        # Simple keyword scoring: count query words that appear in each fact.
        words = [w for w in query.lower().split() if len(w) > 2]
        rows = self.conn.execute("SELECT * FROM facts ORDER BY id DESC LIMIT 500").fetchall()
        scored = []
        for r in rows:
            text = r["text"].lower()
            score = sum(1 for w in words if w in text)
            if score:
                scored.append((score, dict(r)))
        scored.sort(key=lambda x: (-x[0], -x[1]["ts"]))
        return [d for _, d in scored[:limit]]

    def close(self) -> None:
        self.conn.close()
