"""`refactory api-docs` — public API documentation gaps."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms


def api_docs_cmd() -> None:
    """List public APIs that lack documentation."""
    try:
        container = get_container()
        started = time.perf_counter()
        with loading("Finding undocumented public APIs…"):
            gaps = container.documentation_service.find_public_api_without_docs()
            coverage = container.documentation_service.find_documentation_coverage()
        lines = [
            "====================================",
            "",
            "Public API Documentation",
            "",
            "====================================",
            "",
            f"Public API coverage: {coverage.public_api_coverage:.2%}",
            f"Undocumented: {len(gaps)}",
            f"Elapsed: {format_ms((time.perf_counter() - started) * 1000.0)}",
            "",
        ]
        if gaps:
            for gap in gaps[:60]:
                sym = f"::{gap.symbol}" if gap.symbol else ""
                lines.append(f"  {gap.path}{sym}  [{gap.kind.value}]")
        else:
            lines.append("  (none)")
        lines.extend(["", "===================================="])
        console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
