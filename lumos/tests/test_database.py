from pathlib import Path

from lumos.memory.database import Database


def test_conversation_and_note_retrieval(tmp_path: Path):
    database = Database(tmp_path / "lumos.db")
    database.initialize()

    conversation_id = database.create_conversation("test-conversation")
    database.add_message(conversation_id, "user", "hello")
    database.add_message(conversation_id, "assistant", "hi", "mock", "mock-model")

    messages = database.get_messages(conversation_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]

    database.replace_document(
        path="project.md",
        title="Project",
        sha256="abc",
        mtime_ns=1,
        chunks=["Lumos uses a modular provider router and SQLite retrieval."],
    )
    results = database.search_chunks("provider router", limit=3)
    assert results
    assert results[0]["path"] == "project.md"


def test_fts5_index_is_actually_created(tmp_path: Path):
    """Regression: tokenize='unicode61 porter' was invalid FTS5 syntax, so the
    index silently failed to build and every search degraded to LIKE."""
    database = Database(tmp_path / "lumos.db")
    database.initialize()
    assert database.fts5_enabled is True


def test_memory_search_matches_any_query_word(tmp_path: Path):
    # Would fail under the LIKE fallback, which only matches the first word.
    database = Database(tmp_path / "lumos.db")
    database.initialize()
    database.save_memory("Family pizza night is every Friday", source="test")

    results = database.search_memories("When is pizza night?")
    assert results
    assert results[0]["value"] == "Family pizza night is every Friday"


def test_search_handles_farsi_text(tmp_path: Path):
    # unicode61 must tokenize non-Latin scripts; the family uses Farsi notes.
    database = Database(tmp_path / "lumos.db")
    database.initialize()
    database.replace_document(
        path="fa.md",
        title="Farsi",
        sha256="fa1",
        mtime_ns=1,
        chunks=["چای مورد علاقه رضا ارل گری است"],
    )
    results = database.search_chunks("چای ارل گری")
    assert results
    assert results[0]["path"] == "fa.md"
