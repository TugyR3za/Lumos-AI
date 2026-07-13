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
from typing import Literal, cast

from lumos.graph import store
from lumos.memory.database import Database

# What the API and the CLI both say when reads are off, so they cannot drift apart.
GRAPH_DISABLED_DETAIL = (
    "Graph reads are disabled. Set LUMOS_GRAPH_ENABLED=true to turn them on — "
    "ingest already writes the graph, so no reindex is needed."
)

# The database CHECKs these; the casts below are that constraint, restated.
NodeKind = Literal["note", "tag", "entity"]
Rel = Literal["links_to", "mentions", "tagged"]
Direction = Literal["in", "out"]


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: int
    kind: NodeKind
    slug: str
    title: str
    path: str | None  # notes are backed by a file; tags and entities are not


@dataclass(frozen=True, slots=True)
class Neighbor:
    node: GraphNode
    rel: Rel
    direction: Direction  # 'out': this node declares it — 'in': the other points here


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

    def note_for_path(self, path: str) -> GraphNode | None:
        """The note node behind a document path — what note search hands back."""
        if not self.enabled:
            return None
        with self.database.connect() as db:
            rows = store.fetch_note_nodes_by_path(db, [path])
        return _node(rows[0]) if rows else None

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
            Neighbor(
                node=_node(row),
                rel=cast("Rel", row["rel"]),
                direction=cast("Direction", row["direction"]),
            )
            for row in rows[:cap]
        ]

    def related_notes(
        self, seed_paths: Sequence[str], *, limit: int | None = None
    ) -> list[RelatedNote]:
        """Notes one link away from any of ``seed_paths`` — document paths **in
        search order, best match first** — ranked by how many seeds reach them and
        then by the best-ranked seed that does.

        That order is load-bearing. It carries the only relevance signal the graph
        has: a note linked from the first hit is a better bet than one linked from
        the fifth. Without it the cap falls back on the alphabet, and a note the top
        hit points straight at loses its place to one an also-ran happened to mention.
        """
        cap = self.max_related if limit is None else limit
        if not self.enabled or not seed_paths or cap <= 0:
            return []

        # One entry per note, first occurrence winning: a seed's position is its rank.
        rank = {path: position for position, path in enumerate(dict.fromkeys(seed_paths))}

        with self.database.connect() as db:
            seed_rows = store.fetch_note_nodes_by_path(db, list(rank))
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
        # Agreement first: a note two seeds both reach beats one a single seed
        # mentions in passing. Then the best seed that reached it, so search rank
        # decides which survives the cap. The slug settles nothing but a true tie —
        # two notes of equal standing — and is there only to keep the prompt stable.
        related.sort(
            key=lambda note: (-note.connections, min(rank[seed] for seed in note.via), note.slug)
        )
        return related[:cap]


def _node(row: sqlite3.Row) -> GraphNode:
    path = row["path"]
    return GraphNode(
        id=int(row["id"]),
        kind=cast("NodeKind", row["kind"]),
        slug=str(row["slug"]),
        title=str(row["title"]),
        path=str(path) if path is not None else None,
    )
