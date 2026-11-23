"""`refactory definition <symbol>` — locate symbol definitions."""

from __future__ import annotations

import time

import typer

from refactory.cli.commands._codesearch_render import render_code_search
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.progress import loading


def definition_cmd(
    symbol: str = typer.Argument(..., help="Symbol name (supports Class.method)"),
) -> None:
    """Find definition sites for a local symbol."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading(f"Finding definition of {symbol}…"):
            result = container.code_search_service.find_definition(symbol)
        render_code_search("Definition", result, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
