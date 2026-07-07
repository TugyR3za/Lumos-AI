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
