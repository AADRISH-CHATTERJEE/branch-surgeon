"""Shared rendering for code-search CLI commands."""

from __future__ import annotations

from rich.table import Table

from refactory.cli.ui.console import console
from refactory.cli.ui.style import format_ms
from refactory.cli.ui.tables import key_value_table
from refactory.codesearch.models import CodeSearchResult


def render_code_search(
    title: str,
    result: CodeSearchResult,
    *,
    elapsed_ms: float,
) -> None:
    console.print(
        key_value_table(
            f"{title} metadata",
            {
                "Query": result.query or "(none)",
                "Hits": len(result.hits),
                "Structural": result.structural_hits,
                "Semantic": result.semantic_hits,
                "Elapsed": format_ms(elapsed_ms),
            },
        )
    )
    console.print()
    table = Table(title=title, show_lines=False, expand=True)
    table.add_column("File", style="cyan")
    table.add_column("Line", justify="right")
    table.add_column("Symbol")
    table.add_column("Type")
    table.add_column("Score", justify="right")
    table.add_column("Snippet")

    if not result.hits:
        console.print(table)
        console.print("[dim]No matches found.[/dim]")
    else:
        for hit in result.hits:
            table.add_row(
                hit.file,
                str(hit.line) if hit.line is not None else "-",
                hit.symbol or "-",
                hit.type,
                f"{hit.score:.4f}",
                (hit.snippet or "")[:80],
            )
        console.print(table)

    for note in result.notes:
        console.print(f"[yellow]{note}[/yellow]")
