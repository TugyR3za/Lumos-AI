from pathlib import Path

import pytest
from rich.table import Table

from lumos.cli import QUIT, CliState, chat_once, handle_command, status_summary
from lumos.config import Settings
from lumos.core.container import LumosContainer, build_container


@pytest.fixture
def container(tmp_path: Path) -> LumosContainer:
    """A fully wired app with no network dependencies: echo provider only."""
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "lumos.db",
        notes_path=tmp_path / "notes",
        ollama_enabled=False,
        cloud_enabled=False,
        web_search_provider="disabled",
        ingest_notes_on_startup=False,
    )
    settings.ensure_directories()
    return build_container(settings)


@pytest.mark.asyncio
async def test_echo_chat_end_to_end(container: LumosContainer):
    state = CliState()
    response = await chat_once(container, state, "hello lumos")
    assert response.provider == "echo"
    assert "hello lumos" in response.answer
    assert state.conversation_id  # carried forward for the next turn

    followup = await chat_once(container, state, "second turn")
    assert followup.conversation_id == response.conversation_id


@pytest.mark.asyncio
async def test_remember_and_status(container: LumosContainer):
    state = CliState()
    out = await handle_command(container, state, "remember", "Family pizza night is Friday")
    assert "Saved" in str(out)

    summary = await status_summary(container)
    counts = summary["counts"]
    assert counts["memories"] == 1
    providers = summary["providers"]
    assert providers["fallback"]["available"] is True
    assert providers["local"]["configured"] is False

    table = await handle_command(container, state, "status", "")
    assert isinstance(table, Table)


@pytest.mark.asyncio
async def test_command_dispatch(container: LumosContainer):
    state = CliState()
    assert await handle_command(container, state, "quit", "") is QUIT
    assert await handle_command(container, state, "exit", "") is QUIT

    await handle_command(container, state, "model", "local")
    assert state.route == "local"
    await handle_command(container, state, "model", "bogus")
    assert state.route == "local"  # invalid input leaves the route unchanged

    await handle_command(container, state, "web", "on")
    assert state.use_web is True
    await handle_command(container, state, "notes", "off")
    assert state.use_notes is False

    state.conversation_id = "abc"
    await handle_command(container, state, "reset", "")
    assert state.conversation_id is None

    out = await handle_command(container, state, "nonsense", "")
    assert "/help" in str(out)

    out = await handle_command(container, state, "remember", "")
    assert "Usage" in str(out)


@pytest.mark.asyncio
async def test_reindex_command(container: LumosContainer, tmp_path: Path):
    (tmp_path / "notes" / "idea.md").write_text("Lumos is a private assistant", encoding="utf-8")
    out = await handle_command(container, CliState(), "reindex", "")
    assert "1 indexed" in str(out)
