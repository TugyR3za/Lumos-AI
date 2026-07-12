"""Ingest-time graph maintenance (Graph V1, slice 2).

Drives the real NotesIngestor over temp files and asserts on the nodes and
edges tables, because the graph's contract is "derived index over the notes
folder", not individual store calls.
"""

import json
from pathlib import Path

from lumos.memory.database import Database
from lumos.notes.ingestor import NotesIngestor


def build(tmp_path: Path) -> tuple[Path, Database, NotesIngestor]:
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
    return notes, database, ingestor


def nodes_by_slug(database: Database) -> dict[str, dict]:
    with database.connect() as db:
        rows = db.execute("SELECT * FROM nodes").fetchall()
    return {row["slug"]: dict(row) for row in rows}


def edge_triples(database: Database) -> set[tuple[str, str, str]]:
    with database.connect() as db:
        rows = db.execute(
            """
            SELECT s.slug AS src, e.rel AS rel, d.slug AS dst
            FROM edges e
            JOIN nodes s ON s.id = e.src
            JOIN nodes d ON d.id = e.dst
            """
        ).fetchall()
    return {(row["src"], row["rel"], row["dst"]) for row in rows}


def test_notes_linking_each_other_in_one_batch(tmp_path: Path):
    # a.md is ingested first and mints an entity for [[b]]; b.md arriving later
    # in the same batch must upgrade it, leaving no trace of the entity phase.
    notes, database, ingestor = build(tmp_path)
    (notes / "a.md").write_text("Kick off, see [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("Details, back to [[a]].", encoding="utf-8")

    ingestor.ingest_all()

    nodes = nodes_by_slug(database)
    assert {slug: node["kind"] for slug, node in nodes.items()} == {"a": "note", "b": "note"}
    assert edge_triples(database) == {("a", "links_to", "b"), ("b", "links_to", "a")}


def test_link_target_arriving_later_upgrades_entity(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "a.md").write_text("See [[b]].", encoding="utf-8")
    ingestor.ingest_all()

    nodes = nodes_by_slug(database)
    assert nodes["b"]["kind"] == "entity"
    assert nodes["b"]["document_id"] is None
    assert edge_triples(database) == {("a", "mentions", "b")}

    (notes / "b.md").write_text("Now a real note.", encoding="utf-8")
    ingestor.ingest_all()

    nodes = nodes_by_slug(database)
    assert nodes["b"]["kind"] == "note"
    assert nodes["b"]["document_id"] is not None
    assert edge_triples(database) == {("a", "links_to", "b")}


def test_deleting_linked_note_downgrades_it_to_entity(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "a.md").write_text("See [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("Tagged #keep, links [[a]].", encoding="utf-8")
    ingestor.ingest_all()
    assert ("a", "links_to", "b") in edge_triples(database)

    (notes / "b.md").unlink()
    ingestor.ingest_all()

    nodes = nodes_by_slug(database)
    assert nodes["b"]["kind"] == "entity"
    assert nodes["b"]["document_id"] is None
    # b's own declarations died with the file, and the now-edgeless tag was pruned.
    assert edge_triples(database) == {("a", "mentions", "b")}
    assert "tag:keep" not in nodes


def test_deleting_unreferenced_note_prunes_its_whole_neighborhood(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "solo.md").write_text("Loves #cooking, mentions [[Ghost Idea]].", encoding="utf-8")
    ingestor.ingest_all()
    assert set(nodes_by_slug(database)) == {"solo", "tag:cooking", "ghost-idea"}

    (notes / "solo.md").unlink()
    ingestor.ingest_all()

    assert nodes_by_slug(database) == {}
    assert edge_triples(database) == set()


def test_renaming_a_link_target_demotes_the_old_name(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "a.md").write_text("See [[target]].", encoding="utf-8")
    (notes / "target.md").write_text("The target.", encoding="utf-8")
    ingestor.ingest_all()
    assert edge_triples(database) == {("a", "links_to", "target")}

    (notes / "target.md").rename(notes / "renamed.md")
    ingestor.ingest_all()

    nodes = nodes_by_slug(database)
    assert nodes["target"]["kind"] == "entity"
    assert nodes["renamed"]["kind"] == "note"
    assert edge_triples(database) == {("a", "mentions", "target")}


def test_duplicate_basenames_get_path_qualified_slugs(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "idea.md").write_text("Root idea.", encoding="utf-8")
    (notes / "sub").mkdir()
    (notes / "sub" / "idea.md").write_text("Nested idea.", encoding="utf-8")

    ingestor.ingest_all()

    nodes = nodes_by_slug(database)
    assert nodes["idea"]["kind"] == "note"
    assert nodes["sub/idea"]["kind"] == "note"
    assert nodes["idea"]["document_id"] != nodes["sub/idea"]["document_id"]


def test_non_markdown_files_stay_out_of_the_graph(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "script.py").write_text(
        "# not-a-tag\nx = 1  # see [[not-a-link]]\n", encoding="utf-8"
    )
    ingestor.ingest_all()

    assert nodes_by_slug(database) == {}
    assert edge_triples(database) == set()
    assert database.stats()["documents"] == 1  # still indexed for retrieval


def test_reingesting_unchanged_notes_leaves_graph_rows_untouched(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "a.md").write_text("See [[b]], tagged #x.", encoding="utf-8")
    (notes / "b.md").write_text("Plain.", encoding="utf-8")
    ingestor.ingest_all()

    def dump(table: str) -> list[tuple]:
        with database.connect() as db:
            return [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]

    before = (dump("nodes"), dump("edges"))
    ingestor.ingest_all()
    assert (dump("nodes"), dump("edges")) == before


def test_self_links_are_skipped(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "loop.md").write_text("This note cites [[loop]] itself.", encoding="utf-8")
    ingestor.ingest_all()

    assert set(nodes_by_slug(database)) == {"loop"}
    assert edge_triples(database) == set()


def test_aliases_land_in_node_metadata(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "reno.md").write_text(
        "---\naliases: [Kitchen Project, The Reno]\n---\nBody.\n", encoding="utf-8"
    )
    ingestor.ingest_all()

    node = nodes_by_slug(database)["reno"]
    assert json.loads(node["metadata_json"])["aliases"] == ["Kitchen Project", "The Reno"]


def test_tags_become_prefixed_tag_nodes(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "home.md").write_text("Work on #home/kitchen and #cooking.", encoding="utf-8")
    ingestor.ingest_all()

    nodes = nodes_by_slug(database)
    assert nodes["tag:home/kitchen"]["kind"] == "tag"
    assert nodes["tag:cooking"]["kind"] == "tag"
    assert edge_triples(database) == {
        ("home", "tagged", "tag:home/kitchen"),
        ("home", "tagged", "tag:cooking"),
    }


def test_stats_reports_graph_counts(tmp_path: Path):
    notes, database, ingestor = build(tmp_path)
    (notes / "a.md").write_text("See [[b]] and #x.", encoding="utf-8")
    ingestor.ingest_all()

    stats = database.stats()
    assert stats["nodes"] == 3  # note a, entity b, tag x
    assert stats["edges"] == 2
