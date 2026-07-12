from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from lumos.core.time import utc_now_iso
from lumos.graph import store as graph_store
from lumos.graph.extract import NoteRefs


class Database:
    """Small SQLite persistence layer with one connection per operation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fts5_enabled = True

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, id);

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    UNIQUE(document_id, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_document
                    ON chunks(document_id, chunk_index);

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL DEFAULT 'personal',
                    memory_key TEXT,
                    value TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_namespace
                    ON memories(namespace, updated_at DESC);
                """
            )
            graph_store.create_tables(db)
            try:
                db.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                        content,
                        chunk_id UNINDEXED,
                        document_id UNINDEXED,
                        tokenize='porter unicode61'
                    )
                    """
                )
                db.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        value,
                        memory_id UNINDEXED,
                        namespace UNINDEXED,
                        tokenize='porter unicode61'
                    )
                    """
                )
                self.fts5_enabled = True
            except sqlite3.OperationalError:
                self.fts5_enabled = False

    def stats(self) -> dict[str, int]:
        """Row counts for status displays."""
        counts: dict[str, int] = {}
        with self.connect() as db:
            for table in ("conversations", "messages", "documents", "chunks", "memories"):
                counts[table] = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            counts.update(graph_store.graph_counts(db))
        return counts

    def create_conversation(self, conversation_id: str | None = None) -> str:
        conversation_id = conversation_id or uuid.uuid4().hex
        now = utc_now_iso()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO conversations(id, created_at, updated_at) VALUES (?, ?, ?)",
                (conversation_id, now, now),
            )
        return conversation_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now_iso()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO messages(
                    conversation_id, role, content, provider, model, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    provider,
                    model,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                ),
            )
            db.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )

    def get_messages(self, conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT role, content, provider, model, metadata_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def get_document_state(self, path: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT id, sha256, mtime_ns FROM documents WHERE path = ?",
                (path,),
            ).fetchone()
        return dict(row) if row else None

    def replace_document(
        self,
        *,
        path: str,
        title: str,
        sha256: str,
        mtime_ns: int,
        chunks: list[str],
        metadata: dict[str, Any] | None = None,
        refs: NoteRefs | None = None,
    ) -> int:
        now = utc_now_iso()
        with self.connect() as db:
            row = db.execute("SELECT id FROM documents WHERE path = ?", (path,)).fetchone()
            if row:
                document_id = int(row["id"])
                if self.fts5_enabled:
                    db.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))
                db.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
                db.execute(
                    """
                    UPDATE documents
                    SET title = ?, sha256 = ?, mtime_ns = ?, metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        sha256,
                        mtime_ns,
                        json.dumps(metadata or {}, ensure_ascii=False),
                        now,
                        document_id,
                    ),
                )
            else:
                cursor = db.execute(
                    """
                    INSERT INTO documents(
                        path, title, sha256, mtime_ns, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        path,
                        title,
                        sha256,
                        mtime_ns,
                        json.dumps(metadata or {}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                document_id = int(cursor.lastrowid)

            for index, content in enumerate(chunks):
                cursor = db.execute(
                    """
                    INSERT INTO chunks(document_id, chunk_index, content, char_count)
                    VALUES (?, ?, ?, ?)
                    """,
                    (document_id, index, content, len(content)),
                )
                chunk_id = int(cursor.lastrowid)
                if self.fts5_enabled:
                    db.execute(
                        "INSERT INTO chunks_fts(content, chunk_id, document_id) VALUES (?, ?, ?)",
                        (content, chunk_id, document_id),
                    )

            if refs is not None:
                graph_store.sync_note(
                    db, document_id=document_id, path=path, title=title, refs=refs
                )
        return len(chunks)

    def remove_documents_not_in(self, active_paths: set[str]) -> int:
        with self.connect() as db:
            rows = db.execute("SELECT id, path FROM documents").fetchall()
            stale = [
                (int(row["id"]), row["path"])
                for row in rows
                if row["path"] not in active_paths
            ]
            for document_id, _ in stale:
                if self.fts5_enabled:
                    db.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))
                graph_store.downgrade_note(db, document_id)
                db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            graph_store.prune_orphans(db)
        return len(stale)

    def fetch_note_leads(self, paths: Sequence[str]) -> dict[str, dict[str, Any]]:
        """The opening chunk of each note, keyed by path.

        A note reached through the graph was reached by structure, not by a term
        match, so no chunk of it answers the question better than any other: its
        opening is what the note is about. A note with no chunks — an empty file —
        is simply absent from the result, having nothing to contribute.
        """
        if not paths:
            return {}
        placeholders = ", ".join("?" * len(paths))
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT d.path AS path, d.title AS title, c.content AS content
                FROM documents d
                JOIN chunks c ON c.document_id = d.id AND c.chunk_index = 0
                WHERE d.path IN ({placeholders})
                """,
                tuple(paths),
            ).fetchall()
        return {str(row["path"]): dict(row) for row in rows}

    def search_chunks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not terms:
            return []

        with self.connect() as db:
            if self.fts5_enabled:
                escaped_terms = [term.replace(chr(34), chr(34) * 2) for term in terms[:12]]
                expression = " OR ".join(f'"{term}"' for term in escaped_terms)
                try:
                    rows = db.execute(
                        """
                        SELECT
                            c.id AS chunk_id,
                            d.title,
                            d.path,
                            c.content,
                            bm25(chunks_fts) AS rank
                        FROM chunks_fts
                        JOIN chunks c ON c.id = CAST(chunks_fts.chunk_id AS INTEGER)
                        JOIN documents d ON d.id = c.document_id
                        WHERE chunks_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (expression, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            else:
                rows = []

            if not rows:
                like = f"%{terms[0]}%"
                rows = db.execute(
                    """
                    SELECT c.id AS chunk_id, d.title, d.path, c.content, 1.0 AS rank
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE c.content LIKE ?
                    LIMIT ?
                    """,
                    (like, limit),
                ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            rank = float(row["rank"])
            results.append(
                {
                    "chunk_id": int(row["chunk_id"]),
                    "title": row["title"],
                    "path": row["path"],
                    "content": row["content"],
                    "score": 1.0 / (1.0 + abs(rank)),
                }
            )
        return results

    def save_memory(
        self,
        value: str,
        *,
        namespace: str = "personal",
        memory_key: str | None = None,
        importance: float = 0.5,
        source: str | None = None,
    ) -> int:
        now = utc_now_iso()
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO memories(
                    namespace, memory_key, value, importance, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (namespace, memory_key, value, importance, source, now, now),
            )
            memory_id = int(cursor.lastrowid)
            if self.fts5_enabled:
                db.execute(
                    "INSERT INTO memories_fts(value, memory_id, namespace) VALUES (?, ?, ?)",
                    (value, memory_id, namespace),
                )
        return memory_id

    def search_memories(
        self,
        query: str,
        *,
        namespace: str = "personal",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not terms:
            return []
        with self.connect() as db:
            if self.fts5_enabled:
                expression = " OR ".join(f'"{term}"' for term in terms[:12])
                rows = db.execute(
                    """
                    SELECT m.id, m.value, m.memory_key, m.importance, m.source, m.updated_at,
                           bm25(memories_fts) AS rank
                    FROM memories_fts
                    JOIN memories m ON m.id = CAST(memories_fts.memory_id AS INTEGER)
                    WHERE memories_fts MATCH ? AND m.namespace = ?
                    ORDER BY rank, m.importance DESC
                    LIMIT ?
                    """,
                    (expression, namespace, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT id, value, memory_key, importance, source, updated_at, 1.0 AS rank
                    FROM memories
                    WHERE namespace = ? AND value LIKE ?
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (namespace, f"%{terms[0]}%", limit),
                ).fetchall()
        return [dict(row) for row in rows]
