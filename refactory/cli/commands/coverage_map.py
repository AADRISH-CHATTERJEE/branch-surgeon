"""`refactory coverage-map` — production ↔ test coverage overview."""

from __future__ import annotations

import time

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.testing.models import TestCoverageMap


def coverage_map_cmd() -> None:
    """Show repository test coverage map summary."""
    try:
        container = get_container()
        warn_if_index_stale(container)
        started = time.perf_counter()
        with loading("Building coverage map…"):
            mapping = container.test_intelligence_service.compute_test_coverage_map()
        _render(mapping, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(mapping: TestCoverageMap, *, elapsed_ms: float) -> None:
    covered = sum(1 for item in mapping.production_files if item.covered)
    lines = [
        "====================================",
        "",
        "Coverage Map",
        "",
        "====================================",
        "",
        f"Production files: {len(mapping.production_files)}",
        f"Covered:          {covered}",
        f"Uncovered:        {len(mapping.uncovered_files)}",
        f"Test files:       {len(mapping.test_files)}",
        f"Orphan tests:     {len(mapping.orphan_tests)}",
        f"Multi-module:     {len(mapping.multi_module_tests)}",
        f"Duplicate groups: {len(mapping.duplicate_groups)}",
        f"Coverage ratio:   {mapping.coverage_ratio:.2%}",
        f"Elapsed:          {format_ms(elapsed_ms)}",
        "",
        "====================================",
        "",
        "Sample covered files",
        "",
    ]
    samples = [item for item in mapping.production_files if item.covered][:15]
    if samples:
        for item in samples:
            tests = ", ".join(t.path for t in item.tests[:3])
            lines.append(f"  {item.path}  conf={item.coverage_confidence:.2f}  <- {tests}")
    else:
        lines.append("  (none)")

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))
