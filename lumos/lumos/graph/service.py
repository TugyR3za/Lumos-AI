"""Read-only graph queries (Graph V1, slice 3).

The graph is written at ingest time by :mod:`lumos.graph.store`; this service is
how the rest of Lumos *reads* it. Two questions are answered here:

* ``related_notes`` — given the notes a search already found, which other notes
  are one ``[[wikilink]]`` away, forwards or backwards? This is the expansion
  BM25 cannot do: a note that never repeats the query's vocabulary but is
  linked from a note that does.
* ``neighbors`` — the full one-hop neighbourhood of any node, tags and entities
  included, for an ego view.

Both are inert until ``graph_enabled`` is set: disabled, they return empty
without opening a connection, so nothing that consumes this service can change
behaviour by accident.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from lumos.graph import store
from lumos.memory.database import Database


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: int
    kind: str
    slug: str
    title: str
    path: str | None  # notes are backed by a file; tags and entities are not


@dataclass(frozen=True, slots=True)
class Neighbor:
    node: GraphNode
    rel: str
    direction: str  # 'out': this node declares it — 'in': the other node points here


@dataclass(frozen=True, slots=True)
class RelatedNote:
    slug: str
    title: str
    path: str
    connections: int  # how many of the seeds link to (or from) this note
    via: tuple[str, ...]  # the seed paths it connects to, so callers can say why


class GraphService:
    """Read-only view over nodes/edges. Writes stay in the ingest path."""

    def __init__(
        self,
        database: Database,
        *,
        enabled: bool = False,
        max_related: int = 5,
        max_neighbors: int = 50,
    ) -> None:
        self.database = database
        self.enabled = enabled
        self.max_related = max_related
        self.max_neighbors = max_neighbors

    def node(self, slug: str) -> GraphNode | None:
        if not self.enabled:
            return None
        with self.database.connect() as db:
            row = store.fetch_node_by_slug(db, slug)
        return _node(row) if row is not None else None

    def neighbors(self, slug: str, *, limit: int | None = None) -> list[Neighbor]:
        """Every node one edge from ``slug``. Empty when the node has no edges
        *or* does not exist — call :meth:`node` to tell those apart."""
        cap = self.max_neighbors if limit is None else limit
        if not self.enabled or cap <= 0:
            return []
        with self.database.connect() as db:
            center = store.fetch_node_by_slug(db, slug)
            if center is None:
                return []
            rows = store.fetch_neighbors(db, int(center["id"]))
        return [
            Neighbor(node=_node(row), rel=str(row["rel"]), direction=str(row["direction"]))
            for row in rows[:cap]
        ]

    def related_notes(
        self, seed_paths: Sequence[str], *, limit: int | None = None
    ) -> list[RelatedNote]:
        """Notes one link away from any of ``seed_paths`` (document paths, as
        returned by note search), ranked by how many seeds reach them."""
        cap = self.max_related if limit is None else limit
        if not self.enabled or not seed_paths or cap <= 0:
            return []

        with self.database.connect() as db:
            seed_rows = store.fetch_note_nodes_by_path(db, list(dict.fromkeys(seed_paths)))
            if not seed_rows:
                return []
            seeds = {int(row["id"]): str(row["path"]) for row in seed_rows}
            rows = store.fetch_linked_notes(db, list(seeds))

        # One note can be reached from several seeds; each arrival is a vote for it.
        found: dict[int, sqlite3.Row] = {}
        via: dict[int, set[str]] = {}
        for row in rows:
            node_id = int(row["id"])
            if node_id in seeds:
                continue  # the seeds are the question, not the answer
            found.setdefault(node_id, row)
            via.setdefault(node_id, set()).add(seeds[int(row["seed_id"])])

        related = [
            RelatedNote(
                slug=str(found[node_id]["slug"]),
                title=str(found[node_id]["title"]),
                path=str(found[node_id]["path"]),
                connections=len(seed_paths_hit),
                via=tuple(sorted(seed_paths_hit)),
            )
            for node_id, seed_paths_hit in via.items()
        ]
        related.sort(key=lambda note: (-note.connections, note.slug))
        return related[:cap]


def _node(row: sqlite3.Row) -> GraphNode:
    path = row["path"]
    return GraphNode(
        id=int(row["id"]),
        kind=str(row["kind"]),
        slug=str(row["slug"]),
        title=str(row["title"]),
        path=str(path) if path is not None else None,
    )
