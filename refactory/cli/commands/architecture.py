"""`refactory architecture` — architectural summary and analysis."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms


def architecture_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Include detailed output."),
) -> None:
    """Generate an architectural summary of the repository."""
    try:
        container = get_container()
        warn_if_index_stale(container)

        root = Path(container.git_service.get_root_path()).resolve()
        started = time.perf_counter()

        with loading("Analyzing architecture…"):
            index = container.indexer_service.load_index(root)
            if index is None:
                index = container.indexer_service.build_index(root)
            container.graph_service.build_graph(index)

            summary = container.ai_intelligence_service.architecture_summary(root)
            violations = container.ai_intelligence_service.detect_architecture_violations(root)
            patterns = container.ai_intelligence_service.detect_patterns(root)
            advice = container.ai_intelligence_service.architecture_advice(root)

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if json_output:
            data = {
                "summary": summary.model_dump(),
                "violations": violations.model_dump(),
                "patterns": patterns.model_dump(),
                "advice": advice.model_dump(),
            }
            console.print(json.dumps(data, indent=2, default=str))
        else:
            _render(summary, violations, patterns, advice, verbose, elapsed_ms)

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(summary, violations, patterns, advice, verbose, elapsed_ms):
    lines: list[str] = [
        "",
        "====================================",
        "Architectural Summary",
        "====================================",
        "",
        summary.summary,
        "",
    ]

    if summary.components:
        lines.append("Components")
        lines.append("----------")
        for comp in summary.components:
            lines.append(f"  {comp.name}: {comp.responsibility}")
            if verbose and comp.dependencies:
                lines.append(f"    Dependencies: {', '.join(comp.dependencies[:5])}")
        lines.append("")

    if summary.critical_paths:
        lines.append("Critical Paths")
        lines.append("--------------")
        for path in summary.critical_paths:
            lines.append(f"  {path}")
        lines.append("")

    if violations.violations:
        lines.append(f"Architecture Violations ({len(violations.violations)})")
        lines.append("-" * 40)
        for v in violations.violations:
            lines.append(f"  [{v.severity.upper()}] {v.title}")
            if verbose and v.fix_suggestion:
                lines.append(f"    Fix: {v.fix_suggestion}")
        lines.append(f"  Health Score: {violations.health_score}/100")
        lines.append("")

    if patterns.patterns:
        lines.append(f"Design Patterns ({len(patterns.patterns)})")
        lines.append("-" * 40)
        for p in patterns.patterns:
            lines.append(f"  {p.kind.value}: {p.symbol} in {p.file} ({p.confidence:.0%})")
        lines.append("")

    if advice.split_suggestions or advice.dependency_cleanup:
        lines.append("Architecture Advice")
        lines.append("-------------------")
        for s in advice.split_suggestions[:5]:
            lines.append(f"  Split: {s}")
        for s in advice.dependency_cleanup[:5]:
            lines.append(f"  Cleanup: {s}")
        for s in advice.modularization[:5]:
            lines.append(f"  Modularize: {s}")
        lines.append("")

    lines.append(f"Completed in {format_ms(elapsed_ms)}")
    lines.append("")
    console.print("\n".join(lines))
