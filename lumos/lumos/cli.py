"""Terminal chat for Lumos — the lightest way to run it on a weak machine.

No browser, no web server: one process talking to the same orchestrator the
web UI uses. Slash commands cover day-to-day housekeeping; anything else is
sent to the model.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, cast

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lumos.config import get_settings
from lumos.core.container import LumosContainer, build_container
from lumos.core.logging import configure_logging
from lumos.providers.base import ProviderError
from lumos.schemas import ChatResponse

Route = Literal["auto", "local", "cloud"]
VALID_ROUTES: tuple[Route, ...] = ("auto", "local", "cloud")

QUIT = object()

HELP = """\
Commands:
  /help               show this help
  /status             providers, web search, notes index, and database
  /reindex            rescan the notes folder for new or changed files
  /remember <text>    save a durable personal memory
  /model <route>      auto | local (primary: Ollama) | cloud (fallback: OpenRouter)
  /notes on|off       include local notes context (default on)
  /web on|off         include web search context (default off)
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
    table.add_row("memories", str(counts["memories"]))
    table.add_row("database", str(summary["database"]))
    table.add_row("notes folder", str(summary["notes_path"]))
    return table


async def handle_command(
    container: LumosContainer,
    state: CliState,
    command: str,
    argument: str,
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
    if command == "remember":
        if not argument:
            return "Usage: /remember <text to keep>"
        memory_id = await asyncio.to_thread(
            container.database.save_memory, argument, source="user_cli"
        )
        return f"Saved memory #{memory_id}."
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
        return f"{command} context: {argument}"
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
                handle_command(container, state, command.lower(), argument.strip())
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
