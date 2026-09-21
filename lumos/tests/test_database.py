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


# --- memory management (list / get / delete) ---------------------------------


def memories(tmp_path: Path) -> Database:
    database = Database(tmp_path / "lumos.db")
    database.initialize()
    return database


def test_list_memories_is_newest_first_and_bounded(tmp_path: Path):
    database = memories(tmp_path)
    for value in ("first", "second", "third"):
        database.save_memory(value, source="test")

    listed = database.list_memories(limit=2)

    assert [row["value"] for row in listed] == ["third", "second"]
    assert database.count_memories() == 3
    # limit=None is what an export asks for: everything, still newest first.
    assert [row["value"] for row in database.list_memories(limit=None)] == [
        "third",
        "second",
        "first",
    ]


def test_list_and_get_return_only_the_intended_fields(tmp_path: Path):
    # A column added to `memories` later must be added to the field list on
    # purpose, rather than arriving in every listing and export the same day.
    database = memories(tmp_path)
    memory_id = database.save_memory("Bin day is Thursday", memory_key="bins", source="test")
    expected = {
        "id",
        "namespace",
        "memory_key",
        "value",
        "importance",
        "source",
        "created_at",
        "updated_at",
    }

    assert set(database.list_memories()[0]) == expected
    assert set(database.get_memory(memory_id) or {}) == expected


def test_get_memory_returns_a_row_or_none(tmp_path: Path):
    database = memories(tmp_path)
    memory_id = database.save_memory("The cat is called Biscuit", source="test")

    row = database.get_memory(memory_id)
    assert row is not None
    assert row["id"] == memory_id
    assert row["value"] == "The cat is called Biscuit"
    assert row["namespace"] == "personal"

    assert database.get_memory(9_999) is None


def test_delete_memory_removes_it_and_lowers_the_count(tmp_path: Path):
    database = memories(tmp_path)
    memory_id = database.save_memory("The mortgage is with Nationwide", source="test")

    assert database.delete_memory(memory_id) is True
    assert database.get_memory(memory_id) is None
    assert database.count_memories() == 0


def test_deleting_an_unknown_id_changes_nothing(tmp_path: Path):
    database = memories(tmp_path)
    database.save_memory("Mum's birthday is on 12 November", source="test")

    assert database.delete_memory(9_999) is False
    assert database.count_memories() == 1


def test_a_deleted_memory_is_gone_from_the_search_index(tmp_path: Path):
    """The point of deleting: the sentence goes, not just the row.

    `memories_fts` holds a second copy of the text and no trigger keeps it in
    step, so a delete that skipped it would drop the memory out of every listing
    while leaving what it said sitting in the database file.
    """
    database = memories(tmp_path)
    memory_id = database.save_memory("The wifi password is SALTMARSH-42", source="test")
    assert database.search_memories("wifi password") != []

    database.delete_memory(memory_id)

    assert database.search_memories("wifi password") == []
    with database.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE memory_id = ?", (memory_id,)
        ).fetchone()[0] == 0
        # And the word itself is no longer in the index, under any row.
        assert db.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE memories_fts MATCH ?", ("SALTMARSH",)
        ).fetchone()[0] == 0


def test_deleting_one_memory_leaves_its_neighbours_alone(tmp_path: Path):
    database = memories(tmp_path)
    doomed = database.save_memory("The bins go out on Thursday night", source="test")
    kept = database.save_memory("Family pizza night is every Friday", source="test")

    database.delete_memory(doomed)

    assert [row["id"] for row in database.list_memories()] == [kept]
    assert [row["value"] for row in database.search_memories("pizza night")] == [
        "Family pizza night is every Friday"
    ]


def test_delete_is_safe_when_fts5_is_unavailable(tmp_path: Path):
    # Some SQLite builds have no FTS5; the memory still has to be deletable.
    database = memories(tmp_path)
    database.fts5_enabled = False
    memory_id = database.save_memory("The spare key is at number 14", source="test")

    assert database.delete_memory(memory_id) is True
    assert database.count_memories() == 0
