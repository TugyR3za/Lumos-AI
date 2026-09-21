"""What a memory export contains — and, more to the point, what it does not.

An export is every private fact a family has saved, in one plaintext file they
may well hand to someone else. So the shape is pinned exactly: the keys are
asserted as whole sets rather than checked for presence, because the failure mode
worth catching is not a missing field, it is a field nobody meant to include.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lumos.cli import CliState, handle_command
from lumos.config import Settings
from lumos.core.container import LumosContainer, build_container
from lumos.memory import export as export_module
from lumos.memory.database import Database
from lumos.memory.export import ExportError, ExportResult, export_memories

TOP_LEVEL_KEYS = {"format", "version", "exported_at", "count", "memories"}
MEMORY_KEYS = {
    "id",
    "namespace",
    "key",
    "value",
    "importance",
    "source",
    "created_at",
    "updated_at",
}

FARSI = "چای مورد علاقه رضا ارل گری است"


@dataclass
class FrozenClock:
    """Stands in for `datetime` so an export's filename is predictable in a test."""

    moment: datetime

    def now(self, tz: object = None) -> datetime:
        return self.moment


def freeze(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> str:
    monkeypatch.setattr(export_module, "datetime", FrozenClock(moment))
    return "lumos-memories-" + moment.strftime("%Y%m%dT%H%M%SZ") + ".json"


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "lumos.db")
    db.initialize()
    return db


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_an_export_writes_every_memory(database: Database, tmp_path: Path):
    for value in ("Family pizza night is every Friday", "The cat is called Biscuit"):
        database.save_memory(value, source="user_cli")

    result = export_memories(database, directory=tmp_path / "exports")

    assert result.count == 2
    assert result.path is not None and result.path.exists()
    payload = read(result.path)
    assert payload["count"] == 2
    assert {entry["value"] for entry in payload["memories"]} == {
        "Family pizza night is every Friday",
        "The cat is called Biscuit",
    }


def test_the_top_level_shape_is_exactly_this(database: Database, tmp_path: Path):
    database.save_memory("The mortgage is with Nationwide", source="user_cli")

    result = export_memories(database, directory=tmp_path / "exports")

    payload = read(result.path)
    assert set(payload) == TOP_LEVEL_KEYS
    assert payload["format"] == "lumos.memories"
    assert payload["version"] == 1
    # A stamp that reads back as a real moment, in UTC.
    stamp = datetime.fromisoformat(payload["exported_at"])
    assert stamp.tzinfo is not None
    assert stamp.utcoffset().total_seconds() == 0


def test_each_memory_carries_exactly_these_keys(database: Database, tmp_path: Path):
    memory_id = database.save_memory(
        "Reza is allergic to penicillin",
        memory_key="allergy",
        importance=0.8,
        source="user_cli",
    )

    result = export_memories(database, directory=tmp_path / "exports")

    entry = read(result.path)["memories"][0]
    assert set(entry) == MEMORY_KEYS
    assert entry["id"] == memory_id
    assert entry["key"] == "allergy"
    assert entry["importance"] == 0.8
    assert entry["namespace"] == "personal"
    assert entry["source"] == "user_cli"
    assert entry["created_at"] and entry["updated_at"]


def test_non_ascii_memories_survive_the_round_trip(database: Database, tmp_path: Path):
    database.save_memory(FARSI, source="user_cli")

    result = export_memories(database, directory=tmp_path / "exports")

    raw = result.path.read_text(encoding="utf-8")
    assert FARSI in raw  # ensure_ascii=False, so it is readable and not escaped
    assert read(result.path)["memories"][0]["value"] == FARSI


def test_the_export_directory_is_made_when_it_is_missing(database: Database, tmp_path: Path):
    database.save_memory("The bins go out on Thursday night", source="user_cli")
    directory = tmp_path / "nowhere" / "yet"
    assert not directory.exists()

    result = export_memories(database, directory=directory)

    assert result.path is not None and result.path.parent == directory


def test_an_empty_database_writes_no_file(database: Database, tmp_path: Path):
    directory = tmp_path / "exports"

    result = export_memories(database, directory=directory)

    assert result == ExportResult(path=None, count=0)
    assert not directory.exists()  # nothing to put in it, so it is never made


def test_an_export_never_overwrites_what_is_already_there(
    database: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    database.save_memory("The spare key is at number 14", source="user_cli")
    directory = tmp_path / "exports"
    directory.mkdir()
    name = freeze(monkeypatch, datetime(2026, 9, 20, 14, 22, 33, tzinfo=UTC))
    (directory / name).write_text("an earlier backup", encoding="utf-8")

    with pytest.raises(ExportError, match="already exists"):
        export_memories(database, directory=directory)

    assert (directory / name).read_text(encoding="utf-8") == "an earlier backup"


def test_a_second_export_leaves_the_first_alone(
    database: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    database.save_memory("Our anniversary is on 8 June", source="user_cli")
    directory = tmp_path / "exports"

    freeze(monkeypatch, datetime(2026, 9, 20, 14, 22, 33, tzinfo=UTC))
    first = export_memories(database, directory=directory).path
    before = first.read_bytes()

    database.save_memory("The lawnmower is a Hayter", source="user_cli")
    freeze(monkeypatch, datetime(2026, 9, 20, 14, 22, 34, tzinfo=UTC))
    second = export_memories(database, directory=directory).path

    assert second != first
    assert first.read_bytes() == before  # the older backup is untouched
    assert read(second)["count"] == 2
    assert sorted(path.name for path in directory.iterdir()) == sorted([first.name, second.name])


def container_with_secrets(tmp_path: Path) -> LumosContainer:
    """A fully wired app holding provider keys — and no way to reach the network."""
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "lumos.db",
        notes_path=tmp_path / "notes",
        memory_export_path=tmp_path / "exports",
        ollama_enabled=False,
        ollama_api_key="sk-ollama-secret-do-not-export",
        cloud_enabled=False,
        cloud_api_key="sk-cloud-secret-do-not-export",
        web_search_provider="disabled",
        ingest_notes_on_startup=False,
    )
    settings.ensure_directories()
    return build_container(settings)


def test_an_export_holds_memories_and_nothing_else(tmp_path: Path):
    """Everything else in that database stays in that database.

    The exporter is handed a Database and a directory and never a Settings, so a
    provider key is not merely left out of the file — it is out of reach of the
    code that writes it. This walks the wired path anyway, with a conversation, a
    note and a tool event sitting in the same database.
    """
    container = container_with_secrets(tmp_path)
    database = container.database

    conversation_id = database.create_conversation("secret-conversation")
    database.add_message(conversation_id, "user", "what did the accountant say about the flat?")
    database.add_message(
        conversation_id,
        "assistant",
        "She said to keep the completion statement.",
        provider="openrouter",
        model="openai/gpt-4o-mini",
        metadata={"tool_events": [{"tool": "search_notes", "arguments": {"query": "accountant"}}]},
    )
    database.replace_document(
        path="finance/flat.md",
        title="Flat",
        sha256="abc",
        mtime_ns=1,
        chunks=["The completion statement is in the blue folder."],
    )
    database.save_memory("Family pizza night is every Friday", source="user_cli")

    result = export_memories(database, directory=container.settings.resolved_memory_export_path)

    raw = result.path.read_text(encoding="utf-8")
    for secret in ("sk-ollama-secret-do-not-export", "sk-cloud-secret-do-not-export"):
        assert secret not in raw
    for leaked in (
        "accountant",  # conversation content
        "completion statement",  # message text, and the note's text
        "finance/flat.md",  # note paths
        "search_notes",  # tool events
        "openrouter",  # provider configuration
        "gpt-4o-mini",
        "secret-conversation",
    ):
        assert leaked not in raw
    payload = json.loads(raw)
    assert set(payload) == TOP_LEVEL_KEYS
    assert payload["count"] == 1
    assert set(payload["memories"][0]) == MEMORY_KEYS


@pytest.mark.asyncio
async def test_the_cli_reports_the_path_and_the_count(tmp_path: Path):
    container = container_with_secrets(tmp_path)
    container.database.save_memory("The boiler is serviced by Kavanagh", source="user_cli")
    container.database.save_memory("Bedtime is half past seven", source="user_cli")

    out = str(await handle_command(container, CliState(), "memory", "export"))

    assert out.startswith("Exported 2 memories to ")
    written = Path(out.removeprefix("Exported 2 memories to "))
    assert written.exists()
    assert written.parent == container.settings.resolved_memory_export_path
    assert read(written)["count"] == 2


@pytest.mark.asyncio
async def test_the_cli_exports_nothing_when_there_is_nothing(tmp_path: Path):
    container = container_with_secrets(tmp_path)

    out = str(await handle_command(container, CliState(), "memory", "export"))

    assert out == "No memories to export."
    assert not container.settings.resolved_memory_export_path.exists()
