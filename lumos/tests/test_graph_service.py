"""Read-only graph queries (Graph V1, slice 3).

Builds a real graph through the ingestor, then asks GraphService the two
questions Slice 4 will ask it.
"""

from pathlib import Path

from lumos.graph.service import GraphService
from lumos.memory.database import Database
from lumos.notes.ingestor import NotesIngestor


def build(
    tmp_path: Path, *, max_related: int = 5, max_neighbors: int = 50
) -> tuple[Path, NotesIngestor, GraphService]:
    notes = tmp_path / "notes"
    notes.mkdir()
    database = Database(tmp_path / "lumos.db")
    database.initialize()
    ingestor = NotesIngestor(
        database,
        notes,
        max_file_bytes=100_000,
        chunk_size_chars=500,
        chunk_overlap_chars=50,
    )
    graph = GraphService(
        database, enabled=True, max_related=max_related, max_neighbors=max_neighbors
    )
    return notes, ingestor, graph


def test_related_notes_follows_links_forward(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("See [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("The target.", encoding="utf-8")
    ingestor.ingest_all()

    related = graph.related_notes(["a.md"])

    assert [(note.slug, note.path, note.via) for note in related] == [("b", "b.md", ("a.md",))]


def test_related_notes_follows_backlinks(tmp_path: Path):
    # b never mentions a, but a links to b: from b, a is still one hop away.
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("See [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("Says nothing about anyone.", encoding="utf-8")
    ingestor.ingest_all()

    assert [note.slug for note in graph.related_notes(["b.md"])] == ["a"]


def test_related_notes_rank_by_how_many_seeds_reach_them(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("See [[hub]] and [[lonely]].", encoding="utf-8")
    (notes / "b.md").write_text("Also see [[hub]].", encoding="utf-8")
    (notes / "hub.md").write_text("Popular.", encoding="utf-8")
    (notes / "lonely.md").write_text("Less so.", encoding="utf-8")
    ingestor.ingest_all()

    related = graph.related_notes(["a.md", "b.md"])

    assert [(note.slug, note.connections) for note in related] == [("hub", 2), ("lonely", 1)]
    assert related[0].via == ("a.md", "b.md")  # sorted, so callers can cite the reason


def test_related_notes_break_ties_on_the_best_seed_not_the_alphabet(tmp_path: Path):
    # The defect the Graph V1 eval found. Every candidate tied at one connection, so
    # the alphabet chose, and a note the top hit linked straight to lost its only slot
    # to one an also-ran happened to mention.
    notes, ingestor, graph = build(tmp_path, max_related=1)
    (notes / "estate.md").write_text("See [[policy]].", encoding="utf-8")
    (notes / "budget.md").write_text("See [[compost]].", encoding="utf-8")
    (notes / "policy.md").write_text("The answer.", encoding="utf-8")
    (notes / "compost.md").write_text("Not the answer.", encoding="utf-8")
    ingestor.ingest_all()

    # 'compost' sorts first and used to take the slot. Now the seed that ranked first
    # takes it, and what that seed points at comes along.
    assert [note.slug for note in graph.related_notes(["estate.md", "budget.md"])] == ["policy"]
    # Hand the same two seeds over the other way round and the other note wins: the
    # order is the signal, not anything the notes themselves decide.
    assert [note.slug for note in graph.related_notes(["budget.md", "estate.md"])] == ["compost"]


def test_seeds_agreeing_still_outrank_a_better_seed(tmp_path: Path):
    # Rank only breaks ties. Two seeds agreeing on a note remains the stronger signal
    # than one better seed pointing elsewhere — and here the alphabet would have said
    # otherwise too, so this pins that agreement still comes first.
    notes, ingestor, graph = build(tmp_path, max_related=1)
    (notes / "top.md").write_text("See [[alpha]].", encoding="utf-8")
    (notes / "mid.md").write_text("See [[zulu]].", encoding="utf-8")
    (notes / "low.md").write_text("Also see [[zulu]].", encoding="utf-8")
    (notes / "alpha.md").write_text("One seed, but the best one.", encoding="utf-8")
    (notes / "zulu.md").write_text("Two seeds, both worse.", encoding="utf-8")
    ingestor.ingest_all()

    related = graph.related_notes(["top.md", "mid.md", "low.md"])

    assert [(note.slug, note.connections) for note in related] == [("zulu", 2)]


def test_related_notes_never_return_a_seed(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("See [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("Back to [[a]].", encoding="utf-8")
    ingestor.ingest_all()

    assert graph.related_notes(["a.md", "b.md"]) == []


def test_related_notes_stop_at_one_hop(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("See [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("See [[c]].", encoding="utf-8")
    (notes / "c.md").write_text("Two hops from a.", encoding="utf-8")
    ingestor.ingest_all()

    assert [note.slug for note in graph.related_notes(["a.md"])] == ["b"]


def test_related_notes_ignore_shared_tags_and_unresolved_mentions(tmp_path: Path):
    # Both notes carry #home and mention [[Ghost]], but neither links the other:
    # tag and entity hubs sit two hops apart, and expanding through them is a
    # separate decision (a popular tag would drag in the whole vault).
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("Tagged #home, mentions [[Ghost]].", encoding="utf-8")
    (notes / "b.md").write_text("Also #home, also [[Ghost]].", encoding="utf-8")
    ingestor.ingest_all()

    assert graph.related_notes(["a.md"]) == []


def test_related_notes_are_capped(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path, max_related=2)
    (notes / "a.md").write_text("[[b]] [[c]] [[d]] [[e]]", encoding="utf-8")
    for name in ("b", "c", "d", "e"):
        (notes / f"{name}.md").write_text("Target.", encoding="utf-8")
    ingestor.ingest_all()

    assert len(graph.related_notes(["a.md"])) == 2
    assert len(graph.related_notes(["a.md"], limit=3)) == 3


def test_unknown_seed_paths_return_nothing(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("See [[b]].", encoding="utf-8")
    ingestor.ingest_all()

    assert graph.related_notes(["nope.md"]) == []
    assert graph.related_notes([]) == []


def test_neighbors_expose_tags_entities_and_direction(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("Tagged #home, see [[b]], mentions [[Ghost]].", encoding="utf-8")
    (notes / "b.md").write_text("The target.", encoding="utf-8")
    ingestor.ingest_all()

    assert {
        (n.node.slug, n.node.kind, n.rel, n.direction) for n in graph.neighbors("a")
    } == {
        ("b", "note", "links_to", "out"),
        ("ghost", "entity", "mentions", "out"),
        ("tag:home", "tag", "tagged", "out"),
    }
    # b sees the same edge from the other end.
    assert [(n.node.slug, n.rel, n.direction) for n in graph.neighbors("b")] == [
        ("a", "links_to", "in")
    ]


def test_tag_and_entity_neighbors_have_no_path(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("Tagged #home.", encoding="utf-8")
    ingestor.ingest_all()

    tag = graph.neighbors("a")[0].node
    assert (tag.slug, tag.path) == ("tag:home", None)

    note = graph.node("a")
    assert note is not None and note.path == "a.md"


def test_missing_node_is_distinguishable_from_an_isolated_one(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "solo.md").write_text("No links, no tags.", encoding="utf-8")
    ingestor.ingest_all()

    assert graph.neighbors("solo") == [] and graph.node("solo") is not None
    assert graph.neighbors("ghost") == [] and graph.node("ghost") is None


def test_disabled_service_answers_empty(tmp_path: Path):
    notes, ingestor, graph = build(tmp_path)
    (notes / "a.md").write_text("Tagged #home, see [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("The target.", encoding="utf-8")
    ingestor.ingest_all()
    assert graph.related_notes(["a.md"])  # the graph really is there

    off = GraphService(graph.database, enabled=False)

    assert off.related_notes(["a.md"]) == []
    assert off.neighbors("a") == []
    assert off.node("a") is None
