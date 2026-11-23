"""`refactory parse-review` — parse an on-disk AI review response (no LLM calls)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.tables import key_value_table
from refactory.response.models import PartialReviewResult, ParsedReview


def parse_review(
    path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to a file containing raw AI review text (e.g. review.md).",
    ),
) -> None:
    """Read AI response text from disk, parse it, and print structured tables."""
    try:
        container = get_container()
        text = path.read_text(encoding="utf-8")
        result = container.review_response_parser.parse(text)
        _render(result, source=str(path))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(result: ParsedReview, *, source: str) -> None:
    kind = "PartialReviewResult" if isinstance(result, PartialReviewResult) else "ReviewResult"
    console.print(
        key_value_table(
            "Parsed Review",
            {
                "Source": source,
                "Result type": kind,
                "Overall risk": result.overall_risk,
                "Confidence": result.confidence
                if result.confidence is not None
                else "(n/a)",
                "Suggestions": len(result.suggestions),
                "Format": result.metadata.source_format,
                "Partial": "yes" if result.is_partial else "no",
            },
        )
    )

    console.print("")
    console.print("[bold]Summary[/bold]")
    console.print(result.summary or "(empty)")

    if result.suggestions:
        table = Table(title="Suggestions", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Severity", style="magenta")
        table.add_column("Title")
        table.add_column("File")
        table.add_column("Line", justify="right")
        table.add_column("Category")
        table.add_column("Confidence", justify="right")
        for idx, sug in enumerate(result.suggestions, start=1):
            table.add_row(
                str(idx),
                sug.severity,
                sug.title or "(untitled)",
                sug.file or "—",
                str(sug.line) if sug.line is not None else "—",
                sug.category or "—",
                f"{sug.confidence:.2f}" if sug.confidence is not None else "—",
            )
        console.print("")
        console.print(table)

        for idx, sug in enumerate(result.suggestions, start=1):
            console.print("")
            console.print(f"[bold]Finding {idx}: {sug.title or '(untitled)'}[/bold]")
            if sug.explanation:
                console.print(f"  Explanation: {sug.explanation}")
            if sug.recommendation:
                console.print(f"  Recommendation: {sug.recommendation}")
            if sug.code_snippet:
                console.print("  Code snippet:")
                console.print(sug.code_snippet)

    warnings = result.warnings
    if warnings:
        console.print("")
        warn_table = Table(title="Parse Warnings", show_header=False)
        warn_table.add_column("Warning", style="yellow")
        for warning in warnings:
            warn_table.add_row(warning)
        console.print(warn_table)
