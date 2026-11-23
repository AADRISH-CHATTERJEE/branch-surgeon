"""`refactory references <symbol>` — find references."""

from __future__ import annotations

import time

import typer

from refactory.cli.commands._codesearch_render import render_code_search
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.progress import loading


def references_cmd(
    symbol: str = typer.Argument(..., help="Symbol name to find references for"),
) -> None:
    """Find files that reference a symbol."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading(f"Finding references to {symbol}…"):
            result = container.code_search_service.find_references(symbol)
        render_code_search("References", result, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
