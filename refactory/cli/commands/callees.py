"""`refactory callees <symbol-or-path>` — find callees."""

from __future__ import annotations

import time

import typer

from refactory.cli.commands._codesearch_render import render_code_search
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.progress import loading


def callees_cmd(
    symbol: str = typer.Argument(
        ...,
        help="Symbol (e.g. AuthService.login) or file path whose callees to list",
    ),
) -> None:
    """Find callees of a symbol or file via the local call graph."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading(f"Finding callees of {symbol}…"):
            result = container.code_search_service.find_callees(symbol)
        render_code_search("Callees", result, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
