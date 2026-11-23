"""Loading / progress indicators for long-running CLI commands."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from refactory.cli.ui.console import console


@contextmanager
def loading(message: str) -> Iterator[None]:
    """Show a Rich status spinner while ``message`` work runs."""
    with console.status(f"[bold cyan]{message}[/bold cyan]", spinner="dots"):
        yield


def pipeline_progress() -> Progress:
    """Create a multi-stage progress bar for CLI pipelines."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
