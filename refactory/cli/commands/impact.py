"""`refactory impact <target>` — local blast-radius analysis."""

from __future__ import annotations

import time

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.impact.models import ImpactReport


def impact_cmd(
    target: str = typer.Argument(
        ...,
        help="File path or symbol (e.g. auth.py, User, login, validate_token)",
    ),
) -> None:
    """Estimate impacted files/symbols for a local file or symbol."""
    try:
        container = get_container()
        warn_if_index_stale(container)
        started = time.perf_counter()
        with loading(f"Analyzing impact of {target}…"):
            report = container.impact_analysis_service.analyze(target)
        _render(report, elapsed_ms=(time.perf_counter() - started) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(report: ImpactReport, *, elapsed_ms: float) -> None:
    lines = [
        "====================================",
        "",
        "Impact Analysis",
        "",
        "====================================",
        "",
        "Target:",
        report.target,
        "",
        "Kind:",
        report.target_kind.value,
        "",
        "Resolved paths:",
        ", ".join(report.resolved_paths) if report.resolved_paths else "(none)",
        "",
        "Resolved symbols:",
        ", ".join(report.resolved_symbols) if report.resolved_symbols else "(none)",
        "",
        "====================================",
        "",
        "Risk Level:",
        report.risk_level.value.upper(),
        "",
        "Confidence:",
        f"{report.confidence:.4f}",
        "",
        f"Elapsed: {format_ms(elapsed_ms)}",
        "",
        "====================================",
        "",
        "Direct Impact",
        "",
    ]
    if report.direct_impact:
        for item in report.direct_impact:
            lines.append(_fmt(item.path, item.symbol, item.confidence, item.reasons))
    else:
        lines.append("(none)")

    lines.extend(["", "Indirect Impact", ""])
    if report.indirect_impact:
        for item in report.indirect_impact[:40]:
            lines.append(_fmt(item.path, item.symbol, item.confidence, item.reasons))
    else:
        lines.append("(none)")

    lines.extend(["", "Dependency Chain", ""])
    if report.dependency_chains:
        for chain in report.dependency_chains[:20]:
            lines.append(f"{' -> '.join(chain.nodes)}  [{chain.relationship}]")
    else:
        lines.append("(none)")

    lines.extend(["", "Files", ""])
    if report.impacted_files:
        lines.extend(f"  {path}" for path in report.impacted_files)
    else:
        lines.append("(none)")

    lines.extend(["", "Symbols", ""])
    if report.impacted_symbols:
        lines.extend(f"  {symbol}" for symbol in report.impacted_symbols)
    else:
        lines.append("(none)")

    if report.callers:
        lines.extend(["", "Callers", ""])
        for item in report.callers:
            lines.append(_fmt(item.path, item.symbol, item.confidence, item.reasons))

    if report.callees:
        lines.extend(["", "Callees", ""])
        for item in report.callees:
            lines.append(_fmt(item.path, item.symbol, item.confidence, item.reasons))

    if report.inheritance:
        lines.extend(["", "Inheritance", ""])
        for item in report.inheritance:
            lines.append(
                f"  {item.kind}: {item.symbol or '-'}  "
                f"conf={item.confidence:.2f}"
            )

    if report.semantic_neighbors:
        lines.extend(["", "Semantic Neighbors", ""])
        for item in report.semantic_neighbors[:15]:
            lines.append(_fmt(item.path, item.symbol, item.confidence, item.reasons))

    if report.in_cycle:
        lines.extend(["", "Cycle:", ", ".join(report.cycle_files)])
    if report.orphan_target:
        lines.extend(["", "Note: target looks like an orphan module"])
    if report.notes:
        lines.extend(["", "Notes", ""])
        lines.extend(f"  - {note}" for note in report.notes)

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))


def _fmt(path: str, symbol: str | None, confidence: float, reasons: list[str]) -> str:
    sym = f"::{symbol}" if symbol else ""
    why = ",".join(reasons[:3]) if reasons else ""
    return f"  {path}{sym}  conf={confidence:.2f}  {why}".rstrip()
