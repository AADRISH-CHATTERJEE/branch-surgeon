"""CLI table helpers — presentation only, no business logic."""

from __future__ import annotations

from typing import Mapping

from rich.table import Table


def key_value_table(title: str, rows: Mapping[str, object]) -> Table:
    table = Table(title=title, show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for key, value in rows.items():
        table.add_row(str(key), str(value))
    return table
