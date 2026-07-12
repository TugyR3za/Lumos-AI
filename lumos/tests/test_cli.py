import io
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from rich.table import Table

from lumos.cli import QUIT, CliState, chat_once, handle_command, status_summary
from lumos.config import Settings
from lumos.core.container import LumosContainer, build_container


def build(tmp_path: Path, *, graph_enabled: bool = False) -> LumosContainer:
    """A fully wired app with no network dependencies: echo provider only."""
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "lumos.db",
        notes_path=tmp_path / "notes",
        ollama_enabled=False,
        cloud_enabled=False,
        web_search_provider="disabled",
        ingest_notes_on_startup=False,
        graph_enabled=graph_enabled,
    )
    settings.ensure_directories()
    return build_container(settings)


@pytest.fixture
def container(tmp_path: Path) -> LumosContainer:
    return build(tmp_path)


def render(renderable: Any) -> str:
    """What the user would actually see in the terminal."""
    stream = io.StringIO()
    Console(width=100, file=stream).print(renderable)
    return stream.getvalue()


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
    assert providers["echo"]["available"] is True
    assert providers["echo"]["state"] == "available"
    assert providers["primary"]["configured"] is False
    assert providers["primary"]["state"] == "not_configured"

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


def write_linked_notes(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    (notes / "a.md").write_text("Tagged #home, see [[b]].", encoding="utf-8")
    (notes / "b.md").write_text("The target.", encoding="utf-8")


@pytest.mark.asyncio
async def test_graph_command_by_slug_and_by_path(tmp_path: Path):
    container = build(tmp_path, graph_enabled=True)
    write_linked_notes(tmp_path)
    container.ingestor.ingest_all()
    state = CliState()

    by_slug = render(await handle_command(container, state, "graph", "a"))
    by_path = render(await handle_command(container, state, "graph", "a.md"))

    assert by_slug == by_path  # a slug and its note path are the same node
    assert "→ links_to" in by_slug and "tag:home" in by_slug
    assert "related notes: b (b.md)" in by_slug

    # b never mentions a, but the backlink is still one hop away.
    backlink = render(await handle_command(container, state, "graph", "b"))
    assert "← links_to" in backlink and "related notes: a (a.md)" in backlink


@pytest.mark.asyncio
async def test_graph_command_handles_isolated_and_unknown_notes(tmp_path: Path):
    container = build(tmp_path, graph_enabled=True)
    (tmp_path / "notes" / "solo.md").write_text("No links, no tags.", encoding="utf-8")
    container.ingestor.ingest_all()
    state = CliState()

    solo = render(await handle_command(container, state, "graph", "solo"))
    assert "nothing links here" in solo and "related notes: none" in solo

    assert "No graph node" in str(await handle_command(container, state, "graph", "ghost"))
    assert "Usage" in str(await handle_command(container, state, "graph", ""))


@pytest.mark.asyncio
async def test_graph_command_is_disabled_by_default(container: LumosContainer, tmp_path: Path):
    write_linked_notes(tmp_path)
    container.ingestor.ingest_all()  # the graph is still written…

    out = str(await handle_command(container, CliState(), "graph", "a"))

    assert "disabled" in out and "LUMOS_GRAPH_ENABLED" in out  # …but reads are off


@pytest.mark.asyncio
async def test_status_reports_the_graph(tmp_path: Path):
    container = build(tmp_path, graph_enabled=True)
    write_linked_notes(tmp_path)
    container.ingestor.ingest_all()

    summary = await status_summary(container)
    assert summary["graph"] == {"enabled": True}
    assert summary["counts"]["nodes"] == 3  # notes a and b, tag home
    assert summary["counts"]["edges"] == 2  # a links_to b, a tagged home

    table = render(await handle_command(container, CliState(), "status", ""))
    assert "enabled · 3 nodes · 2 edges" in table

    off = render(await handle_command(build(tmp_path), CliState(), "status", ""))
    assert "disabled · 3 nodes · 2 edges" in off  # counts stay honest when reads are off
