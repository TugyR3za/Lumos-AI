from pathlib import Path

from lumos.memory.database import Database
from lumos.notes.ingestor import NotesIngestor


def test_ingestor_indexes_changed_files(tmp_path: Path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "idea.md").write_text("A private local-first personal AI.", encoding="utf-8")

    database = Database(tmp_path / "lumos.db")
    database.initialize()
    ingestor = NotesIngestor(
        database,
        notes,
        max_file_bytes=100_000,
        chunk_size_chars=200,
        chunk_overlap_chars=20,
    )

    first = ingestor.ingest_all()
    second = ingestor.ingest_all()

    assert first.indexed == 1
    assert first.chunks == 1
    assert second.skipped == 1
    assert database.search_chunks("local-first")
