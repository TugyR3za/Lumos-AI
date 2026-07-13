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
from lumos.retrieval.relevance import above_floor


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
        score_floor: float = 0.40,
    ) -> None:
        self.database = database
        self.graph = graph
        self.expand = expand
        self.max_linked = max_linked
        self.max_linked_chars = max_linked_chars
        self.score_floor = score_floor

    def search_notes(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        """The notes that match, minus the ones that only look like they do.

        The floor only ever removes. A search that found five notes can come back
        with one, but never with a note the search did not rank — so the seeds the
        graph expands from are a subset of the seeds it had before, and a question
        that used to reach its answer still reaches it.
        """
        rows = self.database.search_chunks(query=query, limit=limit)
        return above_floor(rows, self.score_floor)

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

        # Seeds are chunks and one note can contribute several, so the paths collapse
        # to one entry a note — the first, which is that note's best-ranked chunk. The
        # order is BM25's, and it is the ranking: related_notes breaks its ties on it,
        # so a note the top hit links to outranks one the last hit merely mentions.
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
        """The notes as the model will see them: one block each, filename first.

        One block a *note*, not a chunk. A long note can win several chunks in the
        same search, and each used to arrive under its own ``[NOTE n]`` header — the
        same note three times over, wearing three different numbers, as though the
        folder agreed with itself three times.

        And no numbers. A bracketed index is shaped exactly like a citation key, so a
        model reaches for it as one: 43% of the eval's answers quoted ``[NOTE 1]`` at
        a reader who has never seen this prompt and cannot know what it means. The
        filename is the only name a note has that means anything outside this string,
        so it is the only handle left to reach for.

        The header is a word and not a rule of dashes, because a note may well open
        with ``---`` — YAML frontmatter survives into the indexed text, and Obsidian
        writes it as a matter of course. A delimiter a note can forge is no delimiter.
        """
        chunks: dict[str, list[str]] = {}
        titles: dict[str, str] = {}
        for result in results:
            path = str(result["path"])
            titles.setdefault(path, str(result["title"]))
            chunks.setdefault(path, []).append(str(result["content"]))

        blocks = [
            f"NOTE {path} · {titles[path]}\n" + "\n\n".join(parts)
            for path, parts in chunks.items()
        ]
        # Linked notes come last and say where they came from. The question did not
        # match them; a note it did match points at them, and the model is told so
        # plainly enough to judge them rather than either trust or dismiss them.
        blocks.extend(
            f"NOTE {note.path} · {note.title} · not a search hit; "
            f"linked from {', '.join(note.via)}\n{note.content}"
            for note in linked
        )
        return "\n\n".join(blocks)


def _clip(text: str, limit: int) -> str:
    """Cut to the cap, and say so — a silently truncated note reads as a finished
    one, and the model would take the missing half for absence."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
