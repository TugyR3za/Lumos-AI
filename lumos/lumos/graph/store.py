"""Graph persistence over SQLite (Graph V1, slice 2).

All graph SQL lives in this module. Every function operates on an already
open :class:`sqlite3.Connection` supplied by ``Database``, so graph writes
share the transaction of the document write that caused them: either both
land or neither does.

The graph is a derived index over the notes folder. Nodes are notes (backed
by a document row), tags (slug prefixed ``tag:``), or entities — link
targets no note backs yet. When a matching note arrives its entity node is
upgraded in place and incoming ``mentions`` edges flip to ``links_to``;
deleting a note that other notes still reference performs the symmetric
downgrade. Both run inline at write time, so the final graph does not
depend on file order within a batch. The single post-pass is
:func:`prune_orphans`, which drops extracted tag/entity nodes that no edge
touches anymore.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import PurePosixPath

from lumos.core.time import utc_now_iso
from lumos.graph.extract import NoteRefs, slugify

TAG_SLUG_PREFIX = "tag:"


def _inserted_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:  # pragma: no cover - an INSERT always sets lastrowid
        raise sqlite3.DataError("INSERT returned no rowid")
    return row_id


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (kind IN ('note', 'tag', 'entity')),
            slug TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            source TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_nodes_document ON nodes(document_id);

        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            dst INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            rel TEXT NOT NULL CHECK (rel IN ('links_to', 'mentions', 'tagged')),
            weight REAL NOT NULL DEFAULT 1.0,
            provenance TEXT NOT NULL DEFAULT 'extracted',
            source TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (src, dst, rel)
        );

        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
        """
    )


def sync_note(
    db: sqlite3.Connection,
    *,
    document_id: int,
    path: str,
    title: str,
    refs: NoteRefs,
) -> int:
    """Create or refresh the note node for one document, inside the caller's
    transaction, and rebuild its outgoing edges from ``refs``."""
    now = utc_now_iso()
    metadata = json.dumps(
        {"aliases": list(refs.aliases)} if refs.aliases else {}, ensure_ascii=False
    )
    node_id = _claim_note_node(
        db, document_id=document_id, path=path, title=title, metadata=metadata, now=now
    )

    # Outgoing edges are rebuilt from scratch: the note's current text is the
    # only truth about what it declares.
    db.execute("DELETE FROM edges WHERE src = ?", (node_id,))

    for link in refs.links:
        dst_id, rel = _resolve_link_target(db, slug=link.slug, title=link.target, now=now)
        if dst_id == node_id:
            continue  # a note citing itself says nothing about the graph
        _insert_edge(db, src=node_id, dst=dst_id, rel=rel, source=path, now=now)

    for tag in refs.tags:
        dst_id = _ensure_tag_node(db, tag=tag, now=now)
        _insert_edge(db, src=node_id, dst=dst_id, rel="tagged", source=path, now=now)

    return node_id


def downgrade_note(db: sqlite3.Connection, document_id: int) -> None:
    """Retire the note node of a deleted document, inside the caller's transaction.

    Outgoing edges die with the note. If other notes still point at it, the
    node lives on as an entity and incoming ``links_to`` edges flip back to
    ``mentions``; otherwise the node is deleted outright.
    """
    row = db.execute("SELECT id FROM nodes WHERE document_id = ?", (document_id,)).fetchone()
    if row is None:
        return
    node_id = int(row["id"])
    db.execute("DELETE FROM edges WHERE src = ?", (node_id,))
    incoming = db.execute("SELECT COUNT(*) FROM edges WHERE dst = ?", (node_id,)).fetchone()
    if int(incoming[0]) == 0:
        db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        return
    db.execute(
        """
        UPDATE nodes
        SET kind = 'entity', document_id = NULL, source = 'extracted',
            metadata_json = '{}', updated_at = ?
        WHERE id = ?
        """,
        (utc_now_iso(), node_id),
    )
    _flip_incoming(db, node_id=node_id, old="links_to", new="mentions")


def prune_orphans(db: sqlite3.Connection) -> int:
    """Drop extracted tag/entity nodes no edge touches (the batch post-pass)."""
    cursor = db.execute(
        """
        DELETE FROM nodes
        WHERE kind IN ('tag', 'entity')
          AND source = 'extracted'
          AND NOT EXISTS (SELECT 1 FROM edges WHERE edges.src = nodes.id)
          AND NOT EXISTS (SELECT 1 FROM edges WHERE edges.dst = nodes.id)
        """
    )
    return int(cursor.rowcount)


def graph_counts(db: sqlite3.Connection) -> dict[str, int]:
    """Node and edge totals for status displays."""
    return {
        "nodes": int(db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]),
        "edges": int(db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]),
    }


def _claim_note_node(
    db: sqlite3.Connection,
    *,
    document_id: int,
    path: str,
    title: str,
    metadata: str,
    now: str,
) -> int:
    row = db.execute("SELECT id FROM nodes WHERE document_id = ?", (document_id,)).fetchone()
    if row is not None:
        # Same document re-ingested: its slug is already settled, refresh the rest.
        node_id = int(row["id"])
        db.execute(
            "UPDATE nodes SET title = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
            (title, metadata, now, node_id),
        )
        return node_id

    for slug in _slug_candidates(path, document_id):
        owner = db.execute("SELECT id, kind FROM nodes WHERE slug = ?", (slug,)).fetchone()
        if owner is None:
            cursor = db.execute(
                """
                INSERT INTO nodes(
                    kind, slug, title, document_id, source, metadata_json, created_at, updated_at
                ) VALUES ('note', ?, ?, ?, ?, ?, ?, ?)
                """,
                (slug, title, document_id, path, metadata, now, now),
            )
            return _inserted_id(cursor)
        if owner["kind"] == "entity":
            node_id = int(owner["id"])
            _upgrade_entity_to_note(
                db,
                node_id=node_id,
                document_id=document_id,
                path=path,
                title=title,
                metadata=metadata,
                now=now,
            )
            return node_id
        # Another note owns this slug (duplicate basename): try the next candidate.
    raise sqlite3.IntegrityError(f"could not assign a graph slug for {path!r}")


def _slug_candidates(path: str, document_id: int) -> list[str]:
    """Slug ladder for a new note: stem, then path-qualified, then id-suffixed."""
    parts = PurePosixPath(path).with_suffix("").parts
    stem_slug = slugify(parts[-1])
    path_slug = "/".join(s for s in (slugify(part) for part in parts) if s)
    fallback = f"{stem_slug or 'note'}-{document_id}"
    candidates: list[str] = []
    for candidate in (stem_slug, path_slug, fallback):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _upgrade_entity_to_note(
    db: sqlite3.Connection,
    *,
    node_id: int,
    document_id: int,
    path: str,
    title: str,
    metadata: str,
    now: str,
) -> None:
    db.execute(
        """
        UPDATE nodes
        SET kind = 'note', title = ?, document_id = ?, source = ?, metadata_json = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (title, document_id, path, metadata, now, node_id),
    )
    _flip_incoming(db, node_id=node_id, old="mentions", new="links_to")


def _flip_incoming(db: sqlite3.Connection, *, node_id: int, old: str, new: str) -> None:
    """Rewrite this node's incoming edges from one rel to another.

    UPDATE OR IGNORE leaves rows that would collide with an existing
    ``(src, dst, new)`` edge untouched; the follow-up DELETE clears those
    leftovers so no edge with the old rel survives.
    """
    db.execute(
        "UPDATE OR IGNORE edges SET rel = ? WHERE dst = ? AND rel = ?",
        (new, node_id, old),
    )
    db.execute("DELETE FROM edges WHERE dst = ? AND rel = ?", (node_id, old))


def _resolve_link_target(
    db: sqlite3.Connection, *, slug: str, title: str, now: str
) -> tuple[int, str]:
    """Find or mint the node a wikilink points at; rel depends on its kind."""
    row = db.execute("SELECT id, kind FROM nodes WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        cursor = db.execute(
            """
            INSERT INTO nodes(
                kind, slug, title, document_id, source, metadata_json, created_at, updated_at
            ) VALUES ('entity', ?, ?, NULL, 'extracted', '{}', ?, ?)
            """,
            (slug, title, now, now),
        )
        return _inserted_id(cursor), "mentions"
    rel = "links_to" if row["kind"] == "note" else "mentions"
    return int(row["id"]), rel


def _ensure_tag_node(db: sqlite3.Connection, *, tag: str, now: str) -> int:
    slug = TAG_SLUG_PREFIX + tag
    row = db.execute("SELECT id FROM nodes WHERE slug = ?", (slug,)).fetchone()
    if row is not None:
        return int(row["id"])
    cursor = db.execute(
        """
        INSERT INTO nodes(
            kind, slug, title, document_id, source, metadata_json, created_at, updated_at
        ) VALUES ('tag', ?, ?, NULL, 'extracted', '{}', ?, ?)
        """,
        (slug, tag, now, now),
    )
    return _inserted_id(cursor)


def _insert_edge(
    db: sqlite3.Connection, *, src: int, dst: int, rel: str, source: str, now: str
) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO edges(src, dst, rel, weight, provenance, source, created_at)
        VALUES (?, ?, ?, 1.0, 'extracted', ?, ?)
        """,
        (src, dst, rel, source, now),
    )
