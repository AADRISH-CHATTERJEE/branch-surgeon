"""`refactory callers <symbol>` — find callers."""

from __future__ import annotations

import time

import typer

from refactory.cli.commands._codesearch_render import render_code_search
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.progress import loading


def callers_cmd(
    symbol: str = typer.Argument(..., help="Callee symbol name"),
) -> None:
    """Find callers of a symbol via the local call graph."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading(f"Finding callers of {symbol}…"):
            result = container.code_search_service.find_callers(symbol)
        render_code_search("Callers", result, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
