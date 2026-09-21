import io
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from rich.table import Table

from lumos.cli import (
    QUIT,
    CliState,
    _memory_preview,
    _print_response,
    chat_once,
    handle_command,
    status_summary,
)
from lumos.config import Settings
from lumos.core.container import LumosContainer, build_container
from lumos.schemas import ChatResponse, SourceItem


def build(tmp_path: Path, *, graph_enabled: bool = False) -> LumosContainer:
    """A fully wired app with no network dependencies: echo provider only."""
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "lumos.db",
        notes_path=tmp_path / "notes",
        # Without this an export in a test writes into the real data/ folder: the
        # database is redirected here, the export path would not have been.
        memory_export_path=tmp_path / "exports",
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

    out = await handle_command(container, state, "web", "on")
    assert state.use_web is True
    assert out == "web permission: on"
    out = await handle_command(container, state, "notes", "off")
    assert state.use_notes is False
    assert out == "notes permission: off"

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


def print_response(response: ChatResponse) -> str:
    """A whole reply as the terminal would show it, tool lines included."""
    stream = io.StringIO()
    _print_response(Console(width=100, file=stream), response)
    return stream.getvalue()


def reply(
    tool_events: list[dict[str, Any]],
    sources: list[SourceItem] | None = None,
) -> ChatResponse:
    return ChatResponse(
        conversation_id="conversation-1",
        answer="Answered.",
        provider="echo",
        model="echo-model",
        sources=sources or [],
        tool_events=tool_events,
    )


def test_a_successful_tool_is_named_after_the_sources():
    out = print_response(
        reply(
            [
                {
                    "tool": "search_notes",
                    "arguments": {"query": "pizza night"},
                    "ok": True,
                    "result": [{"path": "food/friday.md", "content": "Deep dish, 7pm"}],
                }
            ],
            sources=[
                SourceItem(
                    kind="note",
                    title="Friday",
                    location="food/friday.md",
                    snippet="Deep dish, 7pm",
                )
            ],
        )
    )

    assert "tool: search_notes ✓" in out
    assert out.index("[1] Friday — food/friday.md") < out.index("tool: search_notes")
    # A receipt, not a transcript: neither the query asked nor the note found.
    assert "pizza night" not in out and "Deep dish" not in out


def test_a_failed_tool_is_named_with_its_error():
    out = print_response(
        reply(
            [
                {
                    "tool": "search_web",
                    "arguments": {"query": "anything"},
                    "ok": False,
                    "error": "Tool 'search_web' is not permitted for this request.",
                }
            ]
        )
    )

    failure = "tool: search_web ✗ — Tool 'search_web' is not permitted for this request."
    assert failure in out
    assert "anything" not in out


def test_a_reply_with_no_tool_events_says_nothing_about_tools():
    assert "tool:" not in print_response(reply([]))


# --- memory management: /memories, /memory show|delete|export ------------------


def saved(container: LumosContainer, *values: str) -> list[int]:
    return [container.database.save_memory(value, source="user_cli") for value in values]


@pytest.mark.asyncio
async def test_memories_lists_what_is_saved(container: LumosContainer):
    ids = saved(
        container,
        "Pizza night is Friday",
        "The cat is called Biscuit",
    )

    out = render(await handle_command(container, CliState(), "memories", ""))

    assert "Saved memories (2)" in out
    for memory_id in ids:
        assert str(memory_id) in out
    assert "Pizza night is Friday" in out
    assert "The cat is called Biscuit" in out
    assert "user_cli" in out
    assert "/memory show <id> for one in full" in out


@pytest.mark.asyncio
async def test_memories_says_so_when_there_are_none(container: LumosContainer):
    out = await handle_command(container, CliState(), "memories", "")

    assert out == "No memories saved yet. Use /remember <text> to save one."


@pytest.mark.asyncio
async def test_the_listing_is_bounded_by_default(container: LumosContainer):
    saved(container, *(f"memory {index:02d}" for index in range(1, 26)))

    out = render(await handle_command(container, CliState(), "memories", ""))

    assert "Saved memories (20 of 25)" in out
    # One row per memory, and the source column is on every one of them.
    assert len([line for line in out.splitlines() if "user_cli" in line]) == 20
    assert "memory 25" in out  # newest first
    assert "memory 06" in out
    assert "memory 05" not in out  # …and the oldest five are over the limit


@pytest.mark.asyncio
async def test_the_limit_can_be_raised_within_reason(container: LumosContainer):
    saved(container, *(f"memory {index:02d}" for index in range(1, 26)))

    out = render(await handle_command(container, CliState(), "memories", "25"))

    assert "Saved memories (25)" in out
    assert "memory 01" in out


@pytest.mark.asyncio
async def test_a_bad_limit_is_rejected(container: LumosContainer):
    saved(container, "Pizza night is Friday")
    usage = "Usage: /memories [limit]  (1-200, default 20)."

    for argument in ("abc", "0", "201", "-1", "1.5", "20 please"):
        assert await handle_command(container, CliState(), "memories", argument) == usage


@pytest.mark.asyncio
async def test_a_long_memory_is_previewed_not_printed(container: LumosContainer):
    long_memory = "The vet is on Mill Road " + ("and it goes on and on " * 80) + "ENDMARKER"
    saved(container, long_memory)

    out = render(await handle_command(container, CliState(), "memories", ""))

    assert "The vet is on Mill Road" in out
    assert "ENDMARKER" not in out  # the far end of the memory never reaches the screen
    assert out.count("and it goes on and on") <= 2  # 60 characters does not hold a third
    assert len(out) < len(long_memory) // 2  # table furniture included
    # The bound lives in the data, not in however wide the terminal happens to be.
    assert len(_memory_preview(long_memory)) <= 60


@pytest.mark.asyncio
async def test_a_squeezed_listing_gives_up_preview_and_nothing_else(container: LumosContainer):
    """Regression: every column shrank together, so `user_cli` came out `user_c…`.

    When the table is wider than the terminal, rich takes the difference out of
    whichever columns it may. The preview is the only one that can afford it — it
    is an abridgement already — while a date cut to `2026-09-2…` says neither
    the date nor the time, and a truncated id cannot be typed into /memory show.
    """
    memory_id = container.database.save_memory(
        "The boiler is serviced by Kavanagh every fourteen months, booked by telephone",
        memory_key="boiler",
        source="user_cli",
    )
    saved_row = container.database.get_memory(memory_id)

    out = render(await handle_command(container, CliState(), "memories", ""))

    row = next(line for line in out.splitlines() if "user_cli" in line)
    assert str(memory_id) in row
    assert "boiler" in row  # not "boil…"
    assert str(saved_row["updated_at"])[:10] in row  # the whole date
    assert "0.50" in row


@pytest.mark.asyncio
async def test_a_memory_full_of_newlines_stays_on_one_line(container: LumosContainer):
    saved(container, "Gas meter reading\n\n  0421\tunder the stairs")

    out = render(await handle_command(container, CliState(), "memories", ""))

    assert "Gas meter reading 0421 under the stairs" in out


@pytest.mark.asyncio
async def test_markup_in_a_memory_is_shown_not_obeyed(container: LumosContainer):
    memory_id = saved(container, "Pay [bold]£40[/bold] weekly")[0]

    listed = render(await handle_command(container, CliState(), "memories", ""))
    shown = render(await handle_command(container, CliState(), "memory", f"show {memory_id}"))

    assert "Pay [bold]£40[/bold] weekly" in listed
    assert "Pay [bold]£40[/bold] weekly" in shown


@pytest.mark.asyncio
async def test_memory_show_prints_one_memory_in_full(container: LumosContainer):
    memory_id = container.database.save_memory(
        "Reza is allergic to penicillin",
        memory_key="allergy",
        importance=0.8,
        source="user_cli",
    )

    out = render(await handle_command(container, CliState(), "memory", f"show {memory_id}"))

    assert f"memory #{memory_id}" in out
    assert "Reza is allergic to penicillin" in out
    assert "allergy" in out
    assert "0.80" in out
    assert "user_cli" in out
    assert "personal" in out
    assert out.count("2") >= 1  # the created and updated stamps are both rendered
    assert "created" in out and "updated" in out


@pytest.mark.asyncio
async def test_memory_show_handles_bad_and_unknown_ids(container: LumosContainer):
    usage = "Usage: /memory show <id> — ids are numbers, see /memories"

    assert await handle_command(container, CliState(), "memory", "show abc") == usage
    assert await handle_command(container, CliState(), "memory", "show") == usage
    assert await handle_command(container, CliState(), "memory", "show -3") == usage
    assert await handle_command(container, CliState(), "memory", "show 999") == "No memory #999."


@pytest.mark.asyncio
async def test_an_unknown_memory_subcommand_shows_usage(container: LumosContainer):
    usage = "Usage: /memory show <id> | /memory delete <id> | /memory export"

    assert await handle_command(container, CliState(), "memory", "") == usage
    assert await handle_command(container, CliState(), "memory", "forget everything") == usage


@pytest.mark.asyncio
async def test_delete_removes_the_memory_once_it_is_confirmed(container: LumosContainer):
    memory_id = saved(container, "The wifi password is SALTMARSH-42")[0]
    asked: list[str] = []

    def confirm(prompt: str) -> str:
        asked.append(prompt)
        return "yes"

    out = await handle_command(
        container, CliState(), "memory", f"delete {memory_id}", confirm=confirm
    )

    assert out == f"Deleted memory #{memory_id}."
    assert container.database.get_memory(memory_id) is None
    assert container.database.search_memories("wifi password") == []
    # The prompt showed what was about to go, and said what a yes means.
    assert "SALTMARSH-42" in asked[0]
    assert "Delete this memory permanently? Type yes to confirm: " in asked[0]


@pytest.mark.asyncio
async def test_a_cancelled_delete_changes_nothing(container: LumosContainer):
    memory_id = saved(container, "The wifi password is SALTMARSH-42")[0]

    for answer in ("y", "Y", "no", "", "yes please", "ye", None):
        out = await handle_command(
            container,
            CliState(),
            "memory",
            f"delete {memory_id}",
            confirm=lambda _prompt, reply=answer: reply,
        )

        assert out == "Cancelled. Nothing was deleted."
        assert container.database.get_memory(memory_id) is not None
        # Still in the search index too, not merely still in the table.
        assert container.database.search_memories("wifi password") != []


@pytest.mark.asyncio
async def test_only_an_exact_yes_deletes(container: LumosContainer):
    for answer in ("yes", "YES", "  yes  ", "Yes"):
        memory_id = saved(container, "The wifi password is SALTMARSH-42")[0]

        out = await handle_command(
            container,
            CliState(),
            "memory",
            f"delete {memory_id}",
            confirm=lambda _prompt, reply=answer: reply,
        )

        assert out == f"Deleted memory #{memory_id}."
        assert container.database.get_memory(memory_id) is None


@pytest.mark.asyncio
async def test_delete_refuses_when_there_is_nobody_to_ask(container: LumosContainer):
    # No confirmation callback is what a non-interactive caller looks like, and
    # deleting is irreversible: no person, no consent, no delete.
    memory_id = saved(container, "The spare key is at number 14")[0]

    out = await handle_command(container, CliState(), "memory", f"delete {memory_id}")

    assert out == "Delete needs an interactive terminal; nothing was deleted."
    assert container.database.get_memory(memory_id) is not None


@pytest.mark.asyncio
async def test_deleting_an_unknown_id_never_asks(container: LumosContainer):
    def confirm(prompt: str) -> str:
        raise AssertionError("asked to confirm a memory that does not exist")

    out = await handle_command(
        container, CliState(), "memory", "delete 999", confirm=confirm
    )

    assert out == "No memory #999."


@pytest.mark.asyncio
async def test_delete_handles_a_non_numeric_id(container: LumosContainer):
    usage = "Usage: /memory delete <id> — ids are numbers, see /memories"

    assert await handle_command(container, CliState(), "memory", "delete all") == usage
    assert await handle_command(container, CliState(), "memory", "delete") == usage


@pytest.mark.asyncio
async def test_managing_memories_is_never_part_of_the_conversation(container: LumosContainer):
    """Looking at your memories does not put them in front of a provider.

    These commands return renderables straight to the terminal: nothing they
    print is written to `messages`, so nothing they print can come back as
    history on the next turn.
    """
    memory_id = saved(container, "The wifi password is SALTMARSH-42")[0]
    state = CliState()

    await handle_command(container, state, "memories", "")
    await handle_command(container, state, "memory", f"show {memory_id}")
    await handle_command(container, state, "memory", "export")

    assert container.database.stats()["messages"] == 0
    assert state.conversation_id is None


@pytest.mark.asyncio
async def test_help_lists_the_memory_commands(container: LumosContainer):
    out = str(await handle_command(container, CliState(), "help", ""))

    assert "/memories" in out
    assert "/memory show" in out
    assert "/memory delete" in out
    assert "/memory export" in out
