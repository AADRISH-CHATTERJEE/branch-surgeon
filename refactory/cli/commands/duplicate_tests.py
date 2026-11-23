"""`refactory duplicate-tests` — likely duplicate test groups."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms


def duplicate_tests_cmd() -> None:
    """List likely duplicate tests (shared names or shared targets)."""
    try:
        container = get_container()
        warn_if_index_stale(container)
        started = time.perf_counter()
        with loading("Finding duplicate tests…"):
            groups = container.test_intelligence_service.find_duplicate_tests()
        lines = [
            "====================================",
            "",
            "Duplicate Tests",
            "",
            "====================================",
            "",
            f"Groups: {len(groups)}",
            f"Elapsed: {format_ms((time.perf_counter() - started) * 1000.0)}",
            "",
        ]
        if groups:
            for group in groups:
                lines.append(f"{group.key}  conf={group.confidence:.2f}")
                for item in group.tests:
                    sym = f"::{item.symbol}" if item.symbol else ""
                    lines.append(f"  - {item.path}{sym}")
                lines.append("")
        else:
            lines.append("(none)")
            lines.append("")
        lines.append("====================================")
        console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
