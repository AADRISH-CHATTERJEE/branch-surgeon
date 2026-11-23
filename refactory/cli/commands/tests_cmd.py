"""`refactory tests <target>` — related tests for a file or symbol."""

from __future__ import annotations

import time

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.testing.models import RelatedTestsReport, TestImpactReport


def tests_cmd(
    target: str = typer.Argument(..., help="File path or symbol (e.g. auth.py, User)"),
    impact: bool = typer.Option(
        False,
        "--impact",
        help="Also estimate test impact / skip risk for the target.",
    ),
) -> None:
    """Find related tests for a production file or symbol."""
    try:
        container = get_container()
        warn_if_index_stale(container)
        service = container.test_intelligence_service
        started = time.perf_counter()
        with loading(f"Finding tests for {target}…"):
            report = service.find_related_tests(target)
            impact_report = service.estimate_test_impact(target) if impact else None
        elapsed = (time.perf_counter() - started) * 1000.0
        _render(report, impact_report=impact_report, elapsed_ms=elapsed)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(
    report: RelatedTestsReport,
    *,
    impact_report: TestImpactReport | None,
    elapsed_ms: float,
) -> None:
    lines = [
        "====================================",
        "",
        "Related Tests",
        "",
        "====================================",
        "",
        "Target:",
        report.target,
        "",
        "Coverage confidence:",
        f"{report.coverage_confidence:.4f}",
        "",
        "Framework hint:",
        report.framework_hint.value,
        "",
        f"Elapsed: {format_ms(elapsed_ms)}",
        "",
        "====================================",
        "",
        "Tests",
        "",
    ]
    if report.tests:
        for item in report.tests:
            sym = f"::{item.symbol}" if item.symbol else ""
            why = ",".join(item.reasons[:3])
            lines.append(
                f"  {item.path}{sym}  conf={item.confidence:.2f}  "
                f"[{item.framework.value}]  {why}"
            )
    elif not report.target_found:
        lines.append(f"Target '{report.target}' was not found.")
    else:
        lines.append("(none)")

    if report.notes and report.target_found:
        lines.extend(["", "Notes", ""])
        lines.extend(f"  - {note}" for note in report.notes)

    if impact_report is not None:
        lines.extend(
            [
                "",
                "====================================",
                "",
                "Test Impact",
                "",
                f"Risk if skipped: {impact_report.risk_if_skipped.value.upper()}",
                f"Coverage confidence: {impact_report.coverage_confidence:.4f}",
                "",
                "Missing critical tests:",
            ]
        )
        if impact_report.missing_critical_tests:
            lines.extend(f"  {path}" for path in impact_report.missing_critical_tests[:20])
        else:
            lines.append("  (none)")

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))
