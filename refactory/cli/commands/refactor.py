"""`refactory refactor` — deterministic refactoring analysis."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.refactor.models import RefactorAnalysis


def refactor_cmd(
    file: str = typer.Argument(None, help="Optional file to scope the analysis."),
    json_output: bool = typer.Option(False, "--json", help="Print results as JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Include detailed output."),
    category: str = typer.Option(None, "--category", help="Filter by category (e.g. dead_code, duplicate_logic)."),
    severity: str = typer.Option(None, "--severity", help="Filter by severity (low, medium, high, critical)."),
    ai: bool = typer.Option(False, "--ai", help="Include AI-powered refactoring suggestions."),
) -> None:
    """Analyze the repository for deterministic refactoring opportunities."""
    try:
        container = get_container()
        warn_if_index_stale(container)

        root = Path(container.git_service.get_root_path()).resolve()
        started = time.perf_counter()

        with loading("Analyzing refactoring opportunities…"):
            result = container.refactoring_service.analyze(
                root,
                target_file=file,
                category_filter=category,
                severity_filter=severity,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if ai:
            with loading("Generating AI suggestions…"):
                file_content = ""
                if file:
                    target = root / file
                    if target.exists():
                        file_content = target.read_text(encoding="utf-8", errors="replace")
                ai_result = container.ai_intelligence_service.ai_refactor(
                    result, file_content=file_content, target_file=file or "",
                )
            if json_output:
                combined = result.model_dump()
                combined["ai_suggestions"] = ai_result.model_dump()
                console.print(json.dumps(combined, indent=2, default=str))
            else:
                _render(result, verbose=verbose, elapsed_ms=elapsed_ms)
                _render_ai_suggestions(ai_result, verbose=verbose)
        elif json_output:
            console.print(json.dumps(result.model_dump(), indent=2, default=str))
        else:
            _render(result, verbose=verbose, elapsed_ms=elapsed_ms)

    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render_ai_suggestions(ai_result, *, verbose: bool = False) -> None:
    from refactory.intelligence.models import AIRefactorResult

    if not isinstance(ai_result, AIRefactorResult) or not ai_result.suggestions:
        return

    lines: list[str] = [
        "",
        "------------------------------------",
        "",
        "AI Suggestions",
        "",
        "------------------------------------",
        "",
    ]
    for s in ai_result.suggestions:
        lines.append(f"[{s.kind.value.upper()}] {s.title}")
        if verbose:
            if s.description:
                lines.append(f"       {s.description}")
            if s.why:
                lines.append(f"       Why: {s.why}")
            if s.benefits:
                lines.append(f"       Benefits: {s.benefits}")
            if s.risk:
                lines.append(f"       Risk: {s.risk}")
            if s.estimated_effort:
                lines.append(f"       Effort: {s.estimated_effort}")
            if s.confidence.score > 0:
                lines.append(f"       Confidence: {s.confidence.score:.0%}")
        lines.append("")

    lines.append(f"Total AI suggestions: {len(ai_result.suggestions)}")
    lines.append(f"Model: {ai_result.model}")
    lines.append("")
    console.print("\n".join(lines))


def _render(
    result: RefactorAnalysis,
    *,
    verbose: bool = False,
    elapsed_ms: float = 0.0,
) -> None:
    m = result.metrics
    lines: list[str] = [
        "",
        "====================================",
        "",
        "Refactoring Analysis",
        "",
        "====================================",
        "",
        f"Scope:     {result.scope}",
        f"Target:    {result.target}",
        f"Elapsed:   {format_ms(elapsed_ms)}",
        "",
        "------------------------------------",
        "",
        "Repository Health",
        "",
        "------------------------------------",
        "",
        f"Health Score:  {m.health_score}/100  (Grade: {m.grade})",
        f"Files:         {m.files_analyzed}",
        f"Total Issues:  {m.total_issues}",
        f"  Critical:    {m.critical_issues}",
        f"  High:        {m.high_issues}",
        f"  Medium:      {m.medium_issues}",
        f"  Low:         {m.low_issues}",
        "",
    ]

    if m.largest_file_lines:
        lines.append(f"Largest file:          {m.largest_file_lines} lines")
    if m.longest_function_lines:
        lines.append(f"Longest function:      {m.longest_function_lines} lines")
    if m.circular_dependency_count:
        lines.append(f"Circular dependencies: {m.circular_dependency_count}")
    if m.dead_code_count:
        lines.append(f"Dead code candidates:  {m.dead_code_count}")
    if m.unused_import_count:
        lines.append(f"Unused imports:        {m.unused_import_count}")
    if m.duplicate_candidate_count:
        lines.append(f"Duplicate candidates:  {m.duplicate_candidate_count}")

    if result.issues:
        lines.extend([
            "",
            "------------------------------------",
            "",
            "Issues",
            "",
            "------------------------------------",
            "",
        ])
        for issue in result.issues:
            sev = issue.severity.value.upper()
            lines.append(f"[{sev}] {issue.title}")
            if verbose and issue.detail:
                lines.append(f"       {issue.detail}")
            if verbose and issue.file:
                loc = issue.file
                if issue.line:
                    loc += f":{issue.line}"
                lines.append(f"       Location: {loc}")
            lines.append("")

    if result.recommendations:
        lines.extend([
            "------------------------------------",
            "",
            "Recommendations",
            "",
            "------------------------------------",
            "",
        ])
        if verbose:
            for rec in result.recommendations:
                lines.append(f"[{rec.priority.value.upper()}] {rec.title}")
                if rec.detail:
                    lines.append(f"       {rec.detail}")
                if rec.estimated_effort:
                    lines.append(f"       Effort: {rec.estimated_effort}")
                lines.append("")
        else:
            from collections import Counter as _Counter
            grouped = _Counter(rec.kind.value for rec in result.recommendations)
            for kind, count in grouped.most_common():
                label = kind.replace("_", " ").title()
                lines.append(f"  {label}: {count}")
            lines.append("")
            lines.append(f"  Total: {len(result.recommendations)} (use --verbose for details)")
            lines.append("")

    if result.plan.steps:
        lines.extend([
            "------------------------------------",
            "",
            "Refactoring Plan",
            "",
            "------------------------------------",
            "",
        ])
        for step in result.plan.steps:
            lines.append(f"  {step}")
        lines.extend([
            "",
            f"Estimated Effort: {result.plan.estimated_effort}",
            f"Risk:             {result.plan.estimated_risk}",
            f"Confidence:       {result.plan.confidence:.0%}",
        ])

    if result.notes:
        lines.extend(["", "Notes:"])
        for note in result.notes:
            lines.append(f"  - {note}")

    lines.extend(["", "====================================", ""])
    console.print("\n".join(lines))
