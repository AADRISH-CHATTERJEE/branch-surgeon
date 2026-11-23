"""`refactory search` / `refactory related` — code search presentation adapters."""

from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.table import Table

from refactory.cli.commands._codesearch_render import render_code_search
from refactory.cli.commands._common import (
    get_container,
    handle_error,
    warn_if_index_stale,
    warm_backend_client,
)
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.cli.ui.tables import key_value_table


def search(
    query: str = typer.Argument(..., help="Natural language or symbol query"),
    top_k: int = typer.Option(8, "--top-k", "-k", min=1, max=50),
) -> None:
    """Hybrid local search (structural index/graph + semantic embeddings)."""
    try:
        container = get_container()
        warm_backend_client(container)
        warn_if_index_stale(container)
        started = time.perf_counter()
        with loading("Searching…"):
            result = container.code_search_service.search(query, top_k=top_k)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        render_code_search("Code Search", result, elapsed_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def related(
    path: str = typer.Argument(..., help="Relative file path (e.g. auth.py)"),
    top_k: int = typer.Option(8, "--top-k", "-k", min=1, max=50),
) -> None:
    """Show files related to ``path`` (graph first, then embedding similarity)."""
    try:
        container = get_container()
        warm_backend_client(container)
        warn_if_index_stale(container)
        started = time.perf_counter()
        with loading(f"Finding files related to {path}…"):
            result = container.code_search_service.find_related(path, top_k=top_k)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        _render_related(path, result, elapsed_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render_related(path: str, result, *, elapsed_ms: float) -> None:
    hits = result.hits
    console.print(
        key_value_table(
            "Related files",
            {
                "Seed path": path,
                "Hits": len(hits),
                "Graph hits": result.structural_hits,
                "Semantic hits": result.semantic_hits,
                "Elapsed": format_ms(elapsed_ms),
            },
        )
    )
    console.print()
    table = Table(title=f"Related to {path}", expand=True)
    table.add_column("Result", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("File")
    table.add_column("Reasons")

    if not hits:
        console.print(table)
        console.print("[dim]No related files found.[/dim]")
    else:
        for hit in hits:
            symbol = hit.symbol or Path(hit.file).stem
            table.add_row(
                f"{hit.type}:{symbol}",
                f"{hit.score:.4f}",
                hit.file,
                ",".join(hit.reasons[:3]),
            )
        console.print(table)

    for note in getattr(result, "notes", []) or []:
        console.print(f"[yellow]{note}[/yellow]")
