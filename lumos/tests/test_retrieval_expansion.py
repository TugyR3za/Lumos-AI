"""Graph-aware retrieval expansion (Graph V1, slice 6).

The notes folder below is built so that one search can exercise every rule:

* ``kitchen.md`` and ``utility.md`` both say "quartz", so both are seeds — and
  utility links to kitchen, so a seed is reachable from a seed.
* ``pantry.md`` is linked from both seeds; ``appliances.md`` from one. That is
  the ranking.
* ``garden.md`` shares only the ``#home`` tag with kitchen, and ``people.md``
  shares only the unresolved ``[[Marta]]`` mention. Neither may be traversed.
* No linked note repeats the word "quartz", so BM25 cannot reach any of them.
"""

from pathlib import Path

import pytest

from lumos.graph.service import GraphService
from lumos.memory.database import Database
from lumos.notes.ingestor import NotesIngestor
from lumos.retrieval.service import RetrievalService

NOTES = {
    "kitchen.md": "# Kitchen\n\nQuartz counter budget. #home\nSee [[pantry]] and "
    "[[appliances]]. Ask [[Marta]] about the fitting.",
    "utility.md": "# Utility\n\nQuartz sink and taps.\nNext to the [[kitchen]], "
    "spares in the [[pantry]].",
    "pantry.md": "# Pantry\n\nShelving and jars.\nFollows from [[kitchen]].",
    "appliances.md": "# Appliances\n\nOven and fridge shortlist.",
    "garden.md": "# Garden\n\nHerb beds. #home",
    "people.md": "# People\n\nThe fitter is [[Marta]].",
}


def build(
    tmp_path: Path,
    *,
    graph_enabled: bool = True,
    expand: bool = True,
    max_linked: int = 3,
    max_linked_chars: int = 800,
) -> tuple[Database, RetrievalService]:
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    for name, text in NOTES.items():
        (notes / name).write_text(text, encoding="utf-8")

    database = Database(tmp_path / "lumos.db")
    database.initialize()
    NotesIngestor(
        database,
        notes,
        max_file_bytes=1_000_000,
        chunk_size_chars=1_200,
        chunk_overlap_chars=160,
    ).ingest_all()

    graph = GraphService(database, enabled=graph_enabled)
    return database, RetrievalService(
        database,
        graph=graph,
        expand=expand,
        max_linked=max_linked,
        max_linked_chars=max_linked_chars,
    )


def expand_query(retrieval: RetrievalService, query: str = "quartz") -> list[str]:
    seeds = retrieval.search_notes(query, limit=5)
    return [note.path for note in retrieval.linked_notes(seeds)]


def test_bm25_alone_never_reaches_the_linked_notes(tmp_path: Path):
    _, retrieval = build(tmp_path)

    hits = {str(row["path"]) for row in retrieval.search_notes("quartz", limit=5)}

    # This is the whole premise: the seeds are found by their words, and the
    # notes they link to share none of them.
    assert hits == {"kitchen.md", "utility.md"}


def test_linked_notes_are_ranked_by_how_many_seeds_reach_them(tmp_path: Path):
    _, retrieval = build(tmp_path)

    linked = retrieval.linked_notes(retrieval.search_notes("quartz", limit=5))

    assert [note.path for note in linked] == ["pantry.md", "appliances.md"]
    assert linked[0].connections == 2  # both seeds link to the pantry
    assert linked[0].via == ("kitchen.md", "utility.md")
    assert linked[1].connections == 1  # only the kitchen mentions the appliances
    assert linked[0].title == "Pantry"
    assert "Shelving and jars" in linked[0].content


def test_a_seed_is_never_its_own_expansion(tmp_path: Path):
    _, retrieval = build(tmp_path)

    # utility.md links to kitchen.md and both are seeds: the question is not its
    # own answer, so kitchen must not come back as something it found.
    assert "kitchen.md" not in expand_query(retrieval)


def test_a_shared_tag_is_not_a_link(tmp_path: Path):
    _, retrieval = build(tmp_path)

    # garden.md carries #home, exactly as kitchen.md does. A tag is a hub of
    # unbounded degree; expanding through it would drag in the whole folder.
    assert "garden.md" not in expand_query(retrieval)


def test_a_shared_unresolved_mention_is_not_a_link(tmp_path: Path):
    _, retrieval = build(tmp_path)

    # people.md mentions [[Marta]] and so does kitchen.md, but no note backs her:
    # they sit two hops apart through an entity, which is not one links_to hop.
    assert "people.md" not in expand_query(retrieval)


def test_the_note_cap_is_hard(tmp_path: Path):
    _, retrieval = build(tmp_path, max_linked=1)

    # Two notes qualify; the cap admits the better-connected one and stops.
    assert expand_query(retrieval) == ["pantry.md"]


def test_a_zero_cap_turns_the_expansion_off(tmp_path: Path):
    _, retrieval = build(tmp_path, max_linked=0)

    assert expand_query(retrieval) == []


def test_a_long_note_is_clipped_and_says_so(tmp_path: Path):
    _, retrieval = build(tmp_path, max_linked_chars=20)

    linked = retrieval.linked_notes(retrieval.search_notes("quartz", limit=5))

    # A silently truncated note reads as a finished one, so the cut is marked.
    assert len(linked[0].content) <= 21
    assert linked[0].content.endswith("…")


def test_expansion_is_off_unless_asked_for(tmp_path: Path):
    database, _ = build(tmp_path)
    plain = RetrievalService(database)  # what the tool and /api/search/notes get

    assert plain.linked_notes(plain.search_notes("quartz", limit=5)) == []


def test_nothing_expands_while_graph_reads_are_off(tmp_path: Path):
    _, retrieval = build(tmp_path, graph_enabled=False)

    # The expansion flag is on; the graph is not. The stricter switch wins.
    assert expand_query(retrieval) == []


def test_no_seeds_no_expansion(tmp_path: Path):
    _, retrieval = build(tmp_path)

    assert retrieval.linked_notes([]) == []


def test_a_note_with_no_text_is_skipped(tmp_path: Path):
    database, retrieval = build(tmp_path)
    # A note can be reachable and yet have nothing to say: emptied out, its edges
    # still stand (refs=None leaves the graph alone) but no chunk remains.
    database.replace_document(
        path="pantry.md", title="Pantry", sha256="emptied", mtime_ns=2, chunks=[]
    )

    assert expand_query(retrieval) == ["appliances.md"]


def test_each_note_gets_one_block_headed_by_its_filename(tmp_path: Path):
    _, retrieval = build(tmp_path)
    seeds = retrieval.search_notes("quartz", limit=5)

    context = retrieval.format_context(seeds)

    # The filename leads, because it is the only name a note has that means anything
    # to whoever reads the answer. There is no [NOTE n] to cite in its place.
    assert context == retrieval.format_context(seeds, [])
    assert context.startswith("NOTE ")
    assert "NOTE kitchen.md · Kitchen\n" in context
    assert "[NOTE" not in context


def test_a_note_that_wins_several_chunks_is_still_one_note():
    rows: list[dict[str, object]] = [
        {"title": "Kitchen", "path": "kitchen.md", "content": "Quartz counters."},
        {"title": "Kitchen", "path": "kitchen.md", "content": "And a new sink."},
        {"title": "Pantry", "path": "pantry.md", "content": "Shelving and jars."},
    ]

    context = RetrievalService.format_context(rows)

    # Two chunks of one note used to arrive as two notes under two numbers, and the
    # folder appeared to agree with itself twice.
    assert context.count("NOTE kitchen.md") == 1
    assert "Quartz counters.\n\nAnd a new sink." in context
    assert context.count("NOTE ") == 2


def test_a_note_cannot_forge_the_header_that_introduces_it():
    # Obsidian writes YAML frontmatter as a matter of course and it survives into the
    # indexed text, so a note's own first line is very often `---`. A rule of dashes
    # would be a delimiter any note could counterfeit.
    rows: list[dict[str, object]] = [
        {"title": "Boiler", "path": "boiler.md", "content": "---\ntitle: Boiler\n---\n# Boiler"}
    ]

    context = RetrievalService.format_context(rows)

    assert context.startswith("NOTE boiler.md · Boiler\n")
    assert not context.startswith("---")


def test_linked_notes_follow_the_hits_and_say_how_they_got_there(tmp_path: Path):
    _, retrieval = build(tmp_path)
    seeds = retrieval.search_notes("quartz", limit=5)

    context = retrieval.format_context(seeds, retrieval.linked_notes(seeds))

    assert context.index("NOTE kitchen.md") < context.index("NOTE pantry.md")
    assert (
        "NOTE pantry.md · Pantry · not a search hit; linked from kitchen.md, utility.md\n"
        "# Pantry" in context
    )


@pytest.mark.parametrize("query", ["quartz", "quartz counter", "sink"])
def test_the_same_question_builds_the_same_prompt(tmp_path: Path, query: str):
    _, retrieval = build(tmp_path)

    once = expand_query(retrieval, query)
    twice = expand_query(retrieval, query)

    assert once == twice  # ties break on slug, so the ranking cannot wobble
