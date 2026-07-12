"""What the model is shown about the notes folder.

Two questions, asked in that order:

* ``search_notes`` — which chunks match the words of the question? That is BM25,
  and it is untouched here: the ``search_notes`` tool and ``/api/search/notes``
  both call it, and neither wants a graph in the loop.
* ``linked_notes`` — which notes did BM25 miss because they never repeat the
  question's vocabulary, yet sit one ``[[link]]`` from a note it found? That is
  the graph, and it stays silent unless ``graph_expand_retrieval`` says otherwise.

The two never compete. Search hits keep their places and linked notes follow
them, because being linked to an answer is weaker evidence than being one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from lumos.graph.service import GraphService
from lumos.memory.database import Database


@dataclass(frozen=True, slots=True)
class LinkedNote:
    """A note the search never matched, reached one link from one that it did."""

    title: str
    path: str
    content: str  # the note's opening, clipped to the character cap
    connections: int  # how many of the seeds reach it
    via: tuple[str, ...]  # and which ones, so the prompt can say why it is here


class RetrievalService:
    def __init__(
        self,
        database: Database,
        *,
        graph: GraphService | None = None,
        expand: bool = False,
        max_linked: int = 3,
        max_linked_chars: int = 800,
    ) -> None:
        self.database = database
        self.graph = graph
        self.expand = expand
        self.max_linked = max_linked
        self.max_linked_chars = max_linked_chars

    def search_notes(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        return self.database.search_chunks(query=query, limit=limit)

    def linked_notes(self, seed_rows: Sequence[dict[str, object]]) -> list[LinkedNote]:
        """The notes one ``links_to`` hop from the search hits, forwards or back.

        Ranked by how many of the seeds reach each one: a note that two hits both
        link to is likelier to be about the subject than one a single hit mentions
        in passing. Ties break on slug, so the same question builds the same
        prompt twice running.

        Only ``links_to`` is followed. Notes that merely share a tag, or share an
        unresolved mention, sit two hops apart through a hub node whose degree is
        unbounded — one popular tag would drag the whole notes folder into the
        context. Expanding through hubs needs a degree guard, and that is not this.

        The caps are hard: at most ``max_linked`` notes, each clipped to
        ``max_linked_chars``, so the context can grow by a known ceiling and no
        single sprawling note can crowd out the hits it followed.
        """
        graph = self.graph
        if not self.expand or graph is None or not seed_rows:
            return []
        if self.max_linked <= 0 or self.max_linked_chars <= 0:
            return []

        # Seeds are chunks, and one note can contribute several of them; the graph
        # is asked about notes, so the paths collapse to a set (order preserved).
        seeds = list(dict.fromkeys(str(row["path"]) for row in seed_rows))

        # Inert while graph reads are off: it answers empty without a connection,
        # so an expansion nobody enabled costs one dict comprehension.
        related = graph.related_notes(seeds, limit=self.max_linked)
        leads = self.database.fetch_note_leads([note.path for note in related])

        linked: list[LinkedNote] = []
        for note in related:
            lead = leads.get(note.path)
            if lead is None:  # an empty note has nothing to add to the prompt
                continue
            linked.append(
                LinkedNote(
                    title=str(lead["title"]),
                    path=note.path,
                    content=_clip(str(lead["content"]), self.max_linked_chars),
                    connections=note.connections,
                    via=note.via,
                )
            )
        return linked

    @staticmethod
    def format_context(
        results: list[dict[str, object]],
        linked: Sequence[LinkedNote] = (),
    ) -> str:
        blocks = [
            f"[NOTE {index}] {result['title']} ({result['path']})\n{result['content']}"
            for index, result in enumerate(results, start=1)
        ]
        # Labelled apart from the hits, and last: the model is told plainly that a
        # link put these here, not the question, so it can weigh them accordingly.
        blocks.extend(
            f"[LINKED NOTE {index}] {note.title} ({note.path}) — "
            f"linked with {', '.join(note.via)}; not a search match\n{note.content}"
            for index, note in enumerate(linked, start=1)
        )
        return "\n\n".join(blocks)


def _clip(text: str, limit: int) -> str:
    """Cut to the cap, and say so — a silently truncated note reads as a finished
    one, and the model would take the missing half for absence."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
