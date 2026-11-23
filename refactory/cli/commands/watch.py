"""`refactory watch` — monitor repository and auto-update analysis."""

from __future__ import annotations

import signal
import time
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.watch.watcher import FileWatcher, WatchEvent, WatchEventType


def watch_cmd(
    path: str = typer.Argument(".", help="Repository path to watch"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="Poll interval in seconds"),
) -> None:
    """Watch repository for changes and automatically update parser/graph/embeddings."""
    try:
        from loguru import logger

        root = Path(path).resolve()
        if not root.is_dir():
            console.print(f"[red]Error:[/red] Directory not found: {root}")
            raise typer.Exit(1)

        console.print(f"[bold cyan]Watching[/bold cyan] {root}")
        console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

        event_count = 0

        def on_changes(events: list[WatchEvent]) -> None:
            nonlocal event_count
            for ev in events:
                icon = {"created": "+", "modified": "~", "deleted": "-"}.get(ev.event_type.value, "?")
                rel = str(Path(ev.path).relative_to(root)) if Path(ev.path).is_relative_to(root) else ev.path
                console.print(f"  [{_color(ev.event_type)}]{icon}[/] {rel}")
                event_count += 1

        watcher = FileWatcher(
            root,
            logger,
            poll_interval=interval,
        )
        watcher.on_change(on_changes)
        watcher.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()
            console.print(f"\n[dim]Watch stopped. {event_count} event(s) detected.[/dim]")

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _color(event_type: WatchEventType) -> str:
    return {
        WatchEventType.CREATED: "green",
        WatchEventType.MODIFIED: "yellow",
        WatchEventType.DELETED: "red",
    }.get(event_type, "white")
