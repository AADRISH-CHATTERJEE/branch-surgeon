"""`refactory todos` — list TODO / FIXME markers from the local index."""

from __future__ import annotations

import time

from refactory.cli.commands._codesearch_render import render_code_search
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.progress import loading


def todos_cmd() -> None:
    """List TODO / FIXME / HACK / NOTE markers from the cached repository index."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading("Collecting TODOs…"):
            result = container.code_search_service.search_todos()
        render_code_search("TODOs", result, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
