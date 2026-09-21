"""Terminal chat for Lumos — the lightest way to run it on a weak machine.

No browser, no web server: one process talking to the same orchestrator the
web UI uses. Slash commands cover day-to-day housekeeping; anything else is
sent to the model.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lumos.config import get_settings
from lumos.core.container import LumosContainer, build_container
from lumos.core.logging import configure_logging
from lumos.graph.service import GRAPH_DISABLED_DETAIL
from lumos.memory.export import ExportError, export_memories
from lumos.providers.base import ProviderError
from lumos.schemas import ChatResponse

Route = Literal["auto", "local", "cloud"]
VALID_ROUTES: tuple[Route, ...] = ("auto", "local", "cloud")

QUIT = object()

# A question put to whoever is at the keyboard, answered with what they typed — or
# None when there is nobody there (EOF) or they gave up (Ctrl-C). Deliberately not
# a bool: what counts as a yes is a rule about deleting someone's memories, and it
# belongs beside the delete, not inside a console adapter. Only `run()` can build
# one of these, which is what keeps a delete a thing a person did.
Confirm = Callable[[str], str | None]

HELP = """\
Commands:
  /help               show this help
  /status             providers, web search, notes index, graph, and database
  /reindex            rescan the notes folder for new or changed files
  /graph <note>       links, tags, and related notes for a note path or slug
  /remember <text>    save a durable personal memory
  /memories [limit]   list saved memories, newest first (1-200, default 20)
  /memory show <id>   one saved memory in full
  /memory delete <id> delete one saved memory, after confirming
  /memory export      write every saved memory to a JSON file
  /model <route>      auto | local (primary: Ollama) | cloud (fallback: OpenRouter)
  /notes on|off       permit note retrieval and search_notes (default on)
  /web on|off         permit web retrieval and search_web (default off)
  /reset              start a new conversation
  /quit               exit
Anything else is sent to Lumos."""


@dataclass
class CliState:
    conversation_id: str | None = None
    route: Route = "auto"
    use_notes: bool = True
    use_web: bool = False


async def status_summary(container: LumosContainer) -> dict[str, object]:
    """Plain-data status used by /status (and tests)."""
    return {
        "providers": await container.providers.status(),
        "web_search": {
            "provider": container.web_search.name,
            "available": await container.web_search.is_available(),
        },
        "counts": await asyncio.to_thread(container.database.stats),
        "graph": {"enabled": container.graph.enabled},
        "database": str(container.settings.resolved_database_path),
        "notes_path": str(container.settings.resolved_notes_path),
    }


_STATE_STYLES = {
    "available": "[green]available[/green]",
    "reachable": "[yellow]reachable[/yellow]",
    "auth_failed": "[red]auth failed[/red]",
    "unreachable": "[red]unreachable[/red]",
    "error": "[red]error[/red]",
}


def _status_table(summary: dict[str, object]) -> Table:
    table = Table(title="Lumos status", show_header=True, header_style="bold")
    table.add_column("Subsystem")
    table.add_column("State")
    providers = cast("dict[str, dict[str, object]]", summary["providers"])
    for label, info in providers.items():
        if not info.get("configured"):
            table.add_row(f"provider:{label}", "not configured")
            continue
        state = str(info.get("state", ""))
        state_text = _STATE_STYLES.get(state, state)
        row = f"{info.get('provider')} · {info.get('model')} · {state_text}"
        if info.get("detail"):
            row += f" [dim]({escape(str(info['detail']))})[/dim]"
        table.add_row(f"provider:{label}", row)
    web = cast("dict[str, object]", summary["web_search"])
    web_state = "available" if web.get("available") else "unavailable"
    table.add_row("web search", f"{web.get('provider')} · {web_state}")
    counts = cast("dict[str, int]", summary["counts"])
    table.add_row("notes index", f"{counts['documents']} documents · {counts['chunks']} chunks")
    graph = cast("dict[str, bool]", summary["graph"])
    # The graph is written at ingest whether or not reads are on, so show the
    # counts either way — "disabled" here means nothing queries them yet.
    graph_state = "[green]enabled[/green]" if graph["enabled"] else "[dim]disabled[/dim]"
    table.add_row(
        "graph",
        f"{graph_state} · {counts['nodes']} nodes · {counts['edges']} edges",
    )
    table.add_row("memories", str(counts["memories"]))
    table.add_row("database", str(summary["database"]))
    table.add_row("notes folder", str(summary["notes_path"]))
    return table


_ARROWS = {"out": "→", "in": "←"}


async def graph_view(container: LumosContainer, target: str) -> object:
    """One hop around a note, by path (`ideas/kitchen.md`) or slug (`kitchen`)."""
    graph = container.graph
    if not graph.enabled:
        return GRAPH_DISABLED_DETAIL

    node = await asyncio.to_thread(graph.node, target)
    if node is None:
        node = await asyncio.to_thread(graph.note_for_path, target)
    if node is None:
        return f"No graph node for '{target}'. Pass a note path or a slug."

    neighbors = await asyncio.to_thread(graph.neighbors, node.slug)
    where = f"{node.kind} · {node.path}" if node.path else node.kind
    table = Table(title=f"graph · {node.slug} ({where})", show_header=True, header_style="bold")
    table.add_column("Edge")
    table.add_column("Node")
    table.add_column("Kind")
    if not neighbors:
        table.add_row("[dim]—[/dim]", "[dim]nothing links here, no tags[/dim]", "")
    for neighbor in neighbors:
        table.add_row(
            f"{_ARROWS[neighbor.direction]} {neighbor.rel}",
            escape(neighbor.node.slug),
            neighbor.node.kind,
        )

    # Same graph, retrieval's question: seeded with this note, what else comes up?
    related = await asyncio.to_thread(graph.related_notes, [node.path]) if node.path else []
    if related:
        names = ", ".join(f"{note.slug} ({note.path})" for note in related)
        footer = f"related notes: {names}"
    else:
        footer = "related notes: none"
    return Group(table, Text(footer, style="dim"))


MEMORY_LIST_DEFAULT = 20
MEMORY_LIST_MAX = 200
# A listing shows enough of a memory to recognise it and no more. Bounded here in
# the data rather than by a column width, because how wide a terminal happens to be
# is a rendering detail and this is not: it decides how much of a private sentence
# is on screen when someone else walks past.
MEMORY_PREVIEW_CHARS = 60

MEMORIES_USAGE = "Usage: /memories [limit]  (1-200, default 20)."
MEMORIES_EMPTY = "No memories saved yet. Use /remember <text> to save one."
MEMORIES_FOOTER = "/memory show <id> for one in full · /memories 50 for more"
MEMORY_USAGE = "Usage: /memory show <id> | /memory delete <id> | /memory export"
MEMORY_SHOW_USAGE = "Usage: /memory show <id> — ids are numbers, see /memories"
MEMORY_DELETE_USAGE = "Usage: /memory delete <id> — ids are numbers, see /memories"
MEMORY_DELETE_NO_TERMINAL = "Delete needs an interactive terminal; nothing was deleted."
MEMORY_DELETE_CANCELLED = "Cancelled. Nothing was deleted."
MEMORY_DELETE_PROMPT = "Delete this memory permanently? Type yes to confirm: "

_DASH = "[dim]—[/dim]"


def _memory_preview(value: str) -> str:
    """One line of a memory, bounded, with its markup defused.

    A memory is whatever the user typed: it can run to paragraphs, and it can
    contain `[bold]`, which rich would otherwise read as an instruction rather
    than as part of the sentence someone saved.
    """
    single_line = " ".join(value.split())
    if len(single_line) > MEMORY_PREVIEW_CHARS:
        single_line = single_line[: MEMORY_PREVIEW_CHARS - 1] + "…"
    return escape(single_line)


def _short_time(stamp: str) -> str:
    """`2026-09-19T21:14:02.108+00:00` → `2026-09-19 21:14`, whatever it is."""
    head, _, _ = stamp.partition(".")
    return head.replace("T", " ")[:16]


def _short_date(stamp: str) -> str:
    """The day alone, which is all a listing has the width for.

    The exact stamp is a keystroke away in `/memory show`; a column squeezed until
    `2026-09-21 00:20` reads `2026-09-2…` tells you neither the date nor the time.
    """
    return stamp.partition("T")[0][:10]


def _memory_field(value: object) -> str:
    return escape(str(value)) if value not in (None, "") else _DASH


def _plain_field(value: object) -> str:
    """The same, for a line that is not a table cell — an em dash, not a style."""
    return escape(str(value)) if value not in (None, "") else "—"


def _memories_table(rows: list[dict[str, object]], total: int) -> Table:
    shown = len(rows)
    title = f"Saved memories ({shown} of {total})" if shown < total else f"Saved memories ({total})"
    table = Table(title=title, show_header=True, header_style="bold")
    # Every column but the preview keeps its full width. A narrow terminal then
    # takes what it needs out of the preview, which is the one column that is
    # already an abridgement — rather than out of the timestamp, where losing the
    # last four characters turns a date into nothing at all.
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("Key", no_wrap=True)
    table.add_column("Imp", justify="right", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Updated", no_wrap=True)
    # The one column rich is allowed to shrink, and the only one that can afford
    # it: it is an abridgement already, so it ellipsises rather than losing a field.
    table.add_column("Preview", overflow="ellipsis")
    for row in rows:
        table.add_row(
            str(row["id"]),
            _memory_field(row["memory_key"]),
            f"{float(cast('float', row['importance'])):.2f}",
            _memory_field(row["source"]),
            _short_date(str(row["updated_at"])),
            _memory_preview(str(row["value"])),
        )
    return table


def _memory_panel(row: dict[str, object]) -> Panel:
    """One memory in full — the only view that prints all of a memory."""
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="dim")
    facts.add_column()
    facts.add_row("namespace", _memory_field(row["namespace"]))
    facts.add_row("key", _memory_field(row["memory_key"]))
    facts.add_row("importance", f"{float(cast('float', row['importance'])):.2f}")
    facts.add_row("source", _memory_field(row["source"]))
    facts.add_row("created", str(row["created_at"]))
    facts.add_row("updated", str(row["updated_at"]))
    # Text(), not markup: a memory reading "[bold]£40 to the window cleaner" is a
    # memory about £40, not a style.
    body = Group(Text(str(row["value"])), Text(""), facts)
    return Panel(body, title=f"memory #{row['id']}", border_style="yellow", expand=False)


def _memory_id(argument: str) -> int | None:
    text = argument.strip()
    return int(text) if text.isdigit() else None


async def memories_view(container: LumosContainer, argument: str) -> object:
    """`/memories [limit]` — what is saved, newest first, previewed not printed."""
    limit = MEMORY_LIST_DEFAULT
    if argument:
        if not argument.isdigit():
            return MEMORIES_USAGE
        limit = int(argument)
        if not 1 <= limit <= MEMORY_LIST_MAX:
            return MEMORIES_USAGE

    total = await asyncio.to_thread(container.database.count_memories)
    if not total:
        return MEMORIES_EMPTY
    rows = await asyncio.to_thread(container.database.list_memories, limit=limit)
    return Group(_memories_table(rows, total), Text(MEMORIES_FOOTER, style="dim"))


async def _memory_show(container: LumosContainer, argument: str) -> object:
    memory_id = _memory_id(argument)
    if memory_id is None:
        return MEMORY_SHOW_USAGE
    row = await asyncio.to_thread(container.database.get_memory, memory_id)
    if row is None:
        return f"No memory #{memory_id}."
    return _memory_panel(row)


async def _memory_delete(
    container: LumosContainer, argument: str, *, confirm: Confirm | None
) -> object:
    """`/memory delete <id>` — never on the first keystroke, never without a person.

    The memory is fetched before anyone is asked anything, so the prompt is always
    about something real and shows the text being destroyed; being asked to confirm
    the deletion of a memory that was never there teaches you to answer yes without
    reading. And with no way to ask — no terminal, a programmatic caller, a model
    somehow reaching this function — the answer is no. Deleting is irreversible and
    there is no undo here, so the absence of a person means the absence of consent.
    """
    memory_id = _memory_id(argument)
    if memory_id is None:
        return MEMORY_DELETE_USAGE
    row = await asyncio.to_thread(container.database.get_memory, memory_id)
    if row is None:
        return f"No memory #{memory_id}."
    if confirm is None:
        return MEMORY_DELETE_NO_TERMINAL

    prompt = (
        f"\n  #{row['id']} · {_plain_field(row['memory_key'])}"
        f" · {_plain_field(row['source'])} · {_short_time(str(row['updated_at']))}\n"
        f"  {_memory_preview(str(row['value']))}\n"
        f"{MEMORY_DELETE_PROMPT}"
    )
    answer = await asyncio.to_thread(confirm, prompt)
    # Exactly "yes". Not "y", not an empty line, not a shrug — this is the one
    # command in Lumos that destroys something a user asked it to keep.
    if (answer or "").strip().casefold() != "yes":
        return MEMORY_DELETE_CANCELLED

    deleted = await asyncio.to_thread(container.database.delete_memory, memory_id)
    return f"Deleted memory #{memory_id}." if deleted else f"No memory #{memory_id}."


async def _memory_export(container: LumosContainer) -> str:
    directory = container.settings.resolved_memory_export_path
    try:
        result = await asyncio.to_thread(
            export_memories, container.database, directory=directory
        )
    except ExportError as exc:
        return str(exc)
    if result.path is None:
        return "No memories to export."
    return f"Exported {result.count} memories to {result.path}"


async def memory_command(
    container: LumosContainer, argument: str, *, confirm: Confirm | None
) -> object:
    """`/memory <verb> …` — the sub-verbs, since the dispatcher only splits once."""
    verb, _, rest = argument.partition(" ")
    verb = verb.strip().lower()
    if verb == "show":
        return await _memory_show(container, rest)
    if verb == "delete":
        return await _memory_delete(container, rest, confirm=confirm)
    if verb == "export":
        return await _memory_export(container)
    return MEMORY_USAGE


async def handle_command(
    container: LumosContainer,
    state: CliState,
    command: str,
    argument: str,
    *,
    confirm: Confirm | None = None,
) -> object:
    """Execute one slash command. Returns QUIT, a string, or a rich renderable."""
    if command in ("quit", "exit"):
        return QUIT
    if command == "help":
        return HELP
    if command == "status":
        return _status_table(await status_summary(container))
    if command == "reindex":
        stats = await asyncio.to_thread(container.ingestor.ingest_all)
        return (
            f"Scanned {stats.scanned} files: {stats.indexed} indexed, "
            f"{stats.skipped} unchanged, {stats.removed} removed, "
            f"{stats.chunks} new chunks."
        )
    if command == "graph":
        if not argument:
            return "Usage: /graph <note path or slug>"
        return await graph_view(container, argument)
    if command == "remember":
        if not argument:
            return "Usage: /remember <text to keep>"
        memory_id = await asyncio.to_thread(
            container.database.save_memory, argument, source="user_cli"
        )
        return f"Saved memory #{memory_id}."
    if command == "memories":
        return await memories_view(container, argument)
    if command == "memory":
        return await memory_command(container, argument, confirm=confirm)
    if command == "model":
        if argument in VALID_ROUTES:
            state.route = cast("Route", argument)
            return f"Provider route: {state.route}"
        return f"Current route: {state.route}. Usage: /model auto|local|cloud"
    if command in ("notes", "web"):
        if argument not in ("on", "off"):
            return f"Usage: /{command} on|off"
        enabled = argument == "on"
        if command == "notes":
            state.use_notes = enabled
        else:
            state.use_web = enabled
        return f"{command} permission: {argument}"
    if command == "reset":
        state.conversation_id = None
        return "Started a new conversation."
    return f"Unknown command: /{command} — try /help"


async def chat_once(container: LumosContainer, state: CliState, text: str) -> ChatResponse:
    """Run one turn and carry the conversation id forward."""
    response = await container.agent.chat(
        user_message=text,
        conversation_id=state.conversation_id,
        route=state.route,
        use_notes=state.use_notes,
        use_web=state.use_web,
    )
    state.conversation_id = response.conversation_id
    return response


def _print_response(console: Console, response: ChatResponse) -> None:
    console.print("\n[bold yellow]lumos ›[/bold yellow]")
    console.print(Markdown(response.answer))
    console.print(Text(f"({response.provider} · {response.model})", style="dim"))
    for index, source in enumerate(response.sources[:4], start=1):
        console.print(Text(f"  [{index}] {source.title} — {source.location}", style="dim"))
    # Which tools ran, and whether each one worked. Names and errors only: a
    # call's arguments and its result carry note text, web pages, or a memory,
    # and a one-line receipt is not the place to repeat any of them.
    for event in response.tool_events:
        name = str(event.get("tool") or "unknown")
        if event.get("ok"):
            console.print(Text(f"  tool: {name} ✓", style="dim"))
            continue
        error = str(event.get("error") or "unknown error")
        console.print(Text(f"  tool: {name} ✗ — {error}", style="dim"))


def _console_confirm(console: Console) -> Confirm:
    """Ask the person at the keyboard, in the terminal they are already typing in.

    The one place in Lumos that reads stdin outside the chat loop, and the only
    source of a `Confirm`. Giving up — Ctrl-C, or a closed stdin — answers None,
    which is not a yes.
    """

    def ask(prompt: str) -> str | None:
        try:
            return console.input(prompt)
        except (EOFError, KeyboardInterrupt):
            console.print()
            return None

    return ask


def run() -> None:
    console = Console()
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keep request logs out of the chat

    container = build_container(settings)
    state = CliState()

    console.print(
        Panel.fit(
            "[bold]Lumos[/bold] — private personal AI · v0.1\n"
            "Type a message, or /help for commands.",
            border_style="yellow",
        )
    )

    if settings.ingest_notes_on_startup:
        with console.status("[dim]Indexing notes…[/dim]"):
            stats = container.ingestor.ingest_all()
        console.print(
            f"[dim]Notes: {stats.indexed} indexed, {stats.skipped} unchanged, "
            f"{stats.chunks} new chunks.[/dim]"
        )

    while True:
        try:
            line = console.input("\n[bold cyan]you ›[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            return
        if not line:
            continue

        if line.startswith("/"):
            command, _, argument = line[1:].partition(" ")
            result = asyncio.run(
                handle_command(
                    container,
                    state,
                    command.lower(),
                    argument.strip(),
                    confirm=_console_confirm(console),
                )
            )
            if result is QUIT:
                console.print("[dim]bye[/dim]")
                return
            console.print(Text(result) if isinstance(result, str) else result)
            continue

        try:
            with console.status("[dim]thinking…[/dim]", spinner="dots"):
                response = asyncio.run(chat_once(container, state, line))
        except ProviderError as exc:
            console.print(f"[red]Provider error:[/red] {exc}")
            continue
        except KeyboardInterrupt:
            console.print("[dim]cancelled[/dim]")
            continue
        _print_response(console, response)


if __name__ == "__main__":
    run()
