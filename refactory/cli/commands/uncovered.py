"""`refactory uncovered` — production files/symbols lacking tests."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.testing.models import TestCoverageMap


def uncovered_cmd() -> None:
    """List production files (and sample symbols) with no related tests."""
    try:
        container = get_container()
        warn_if_index_stale(container)
        started = time.perf_counter()
        with loading("Computing uncovered production code…"):
            mapping = container.test_intelligence_service.compute_test_coverage_map()
        _render(mapping, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(mapping: TestCoverageMap, *, elapsed_ms: float) -> None:
    lines = [
        "====================================",
        "",
        "Uncovered Production Code",
        "",
        "====================================",
        "",
        f"Coverage ratio: {mapping.coverage_ratio:.2%}",
        f"Elapsed: {format_ms(elapsed_ms)}",
        "",
        "Files",
        "",
    ]
    if mapping.uncovered_files:
        lines.extend(f"  {path}" for path in mapping.uncovered_files)
    else:
        lines.append("  (none)")

    lines.extend(["", "Classes (sample)", ""])
    if mapping.uncovered_classes:
        lines.extend(f"  {item}" for item in mapping.uncovered_classes[:40])
    else:
        lines.append("  (none)")

    lines.extend(["", "Functions (sample)", ""])
    if mapping.uncovered_functions:
        lines.extend(f"  {item}" for item in mapping.uncovered_functions[:40])
    else:
        lines.append("  (none)")

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))
