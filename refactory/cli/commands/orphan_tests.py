"""`refactory orphan-tests` — tests with no production links."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms


def orphan_tests_cmd() -> None:
    """List orphan tests (no import/name/graph link to production code)."""
    try:
        container = get_container()
        warn_if_index_stale(container)
        started = time.perf_counter()
        with loading("Finding orphan tests…"):
            orphans = container.test_intelligence_service.find_orphan_tests()
        lines = [
            "====================================",
            "",
            "Orphan Tests",
            "",
            "====================================",
            "",
            f"Count: {len(orphans)}",
            f"Elapsed: {format_ms((time.perf_counter() - started) * 1000.0)}",
            "",
        ]
        if orphans:
            for item in orphans:
                lines.append(
                    f"  {item.path}  conf={item.confidence:.2f}  [{item.framework.value}]"
                )
        else:
            lines.append("  (none)")
        lines.extend(["", "===================================="])
        console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
