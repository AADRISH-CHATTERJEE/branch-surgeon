"""Rich panels and section helpers for CLI reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from rich.panel import Panel
from rich.table import Table

from refactory.cli.ui.console import console
from refactory.cli.ui.tables import key_value_table


def section_panel(title: str, body: str, *, border_style: str = "cyan") -> Panel:
    return Panel(
        body or "[dim](empty)[/dim]",
        title=title,
        border_style=border_style,
        expand=True,
    )


def warnings_table(warnings: Sequence[str], *, title: str = "Warnings") -> Table | None:
    if not warnings:
        return None
    table = Table(title=title, show_header=False, expand=True)
    table.add_column("Warning", style="yellow")
    for warning in warnings:
        table.add_row(str(warning))
    return table


def metadata_table(rows: Mapping[str, object], *, title: str = "Metadata") -> Table:
    return key_value_table(title, rows)


def print_banner(title: str) -> None:
    """Lightweight section divider replacing ad-hoc ASCII banners."""
    console.print()
    console.rule(f"[bold]{title}[/bold]")
