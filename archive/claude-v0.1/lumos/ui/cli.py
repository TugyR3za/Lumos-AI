"""Terminal chat — the primary interface for v0.1.

Uses `rich` for a clean, low-resource UI (no browser, no server). Slash commands
cover the housekeeping you actually need day to day.
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from ..app import App, build_app

HELP = """\
Commands:
  /help              show this help
  /status            show providers, tools, and notes index
  /reindex           scan notes for new/changed files
  /reindex force     rebuild the notes index from scratch
  /remember <text>   save a durable fact about you
  /model <name>      force a provider for this session (ollama|groq|echo|auto)
  /reset             start a fresh conversation session
  /quit              exit
"""

console = Console()


def _print_status(app: App) -> None:
    table = Table(title="Lumos status", show_header=True, header_style="bold")
    table.add_column("Subsystem")
    table.add_column("State")
    for name, state in app.router.status().items():
        table.add_row(f"provider:{name}", state)
    table.add_row("tools", ", ".join(app.tools.names()) or "none")
    table.add_row("notes indexed", str(app.retriever.store.count()) + " chunks")
    console.print(table)


def run() -> None:
    app = build_app()
    session = "cli"
    prefer: str | None = None

    console.print(
        Panel.fit(
            "[bold]Lumos[/bold] — your private assistant\n"
            "Type a message, or /help for commands.",
            border_style="yellow",
        )
    )
    # Index notes on startup so the assistant can use them immediately.
    summary = app.reindex()
    if summary["chunks_added"]:
        console.print(
            f"[dim]Indexed {summary['files_indexed']} note(s), "
            f"{summary['chunks_added']} new chunk(s) via {summary['embedder']}.[/dim]"
        )
    _print_status(app)

    while True:
        try:
            user = console.input("\n[bold cyan]you ›[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            break
        if not user:
            continue

        if user.startswith("/"):
            cmd, _, arg = user[1:].partition(" ")
            arg = arg.strip()
            if cmd in ("quit", "exit"):
                console.print("[dim]bye[/dim]")
                break
            elif cmd == "help":
                console.print(HELP)
            elif cmd == "status":
                _print_status(app)
            elif cmd == "reindex":
                summary = app.reindex(force=(arg == "force"))
                console.print(summary)
            elif cmd == "remember":
                if arg:
                    app.assistant.remember(arg)
                    console.print("[green]Saved.[/green]")
                else:
                    console.print("[yellow]Usage: /remember <text>[/yellow]")
            elif cmd == "model":
                prefer = None if arg in ("", "auto") else arg
                console.print(f"[dim]provider preference: {prefer or 'auto'}[/dim]")
            elif cmd == "reset":
                session = f"cli-{__import__('uuid').uuid4().hex[:6]}"
                console.print("[dim]new session started[/dim]")
            else:
                console.print(f"[yellow]Unknown command: /{cmd}[/yellow]")
            continue

        with console.status("[dim]thinking…[/dim]", spinner="dots"):
            answer = app.assistant.ask(user, session=session, prefer=prefer)
        console.print("[bold yellow]lumos ›[/bold yellow]")
        console.print(Markdown(answer))


if __name__ == "__main__":
    run()
