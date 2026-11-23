"""`refactory stale-docs` — documentation older than related source."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms


def stale_docs_cmd() -> None:
    """List documentation that appears stale relative to source changes."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading("Finding stale documentation…"):
            stale = container.documentation_service.find_stale_documentation()
        lines = [
            "====================================",
            "",
            "Stale Documentation",
            "",
            "====================================",
            "",
            f"Count: {len(stale)}",
            f"Elapsed: {format_ms((time.perf_counter() - started) * 1000.0)}",
            "",
        ]
        if stale:
            for item in stale:
                related = item.related_source or "-"
                lines.append(
                    f"  {item.path}  ← {related}  conf={item.confidence:.2f}  {item.reason}"
                )
        else:
            lines.append("  (none)")
        lines.extend(["", "===================================="])
        console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
