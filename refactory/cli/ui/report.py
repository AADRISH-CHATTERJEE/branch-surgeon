"""Rich report rendering for review results (presentation only)."""

from __future__ import annotations

from rich.table import Table

from refactory.cli.ui.console import console
from refactory.cli.ui.panels import metadata_table, section_panel, warnings_table
from refactory.cli.ui.style import (
    colored_severity,
    format_cache_hit,
    format_cost_usd,
    format_ms,
    risk_style,
    severity_style,
)
from refactory.cli.ui.tables import key_value_table
from refactory.review.models import ReviewResult


def render_review_report(result: ReviewResult) -> None:
    """Render a professional review report with telemetry and warnings.

    Each finding displays all 8 Sprint-5 acceptance-criteria fields:
    Severity, Category, File, Line, Explanation, Suggested Fix,
    Confidence, Estimated Impact.
    """
    if result.risk_level == "blocked":
        console.print()
        console.print("[bold red]❌ REVIEW BLOCKED[/bold red] — company rules failed")
        console.print()
        console.print(section_panel("Company Rules", result.summary or "(empty)", border_style="red"))
        if result.suggestions:
            console.print()
            for idx, sug in enumerate(result.suggestions, start=1):
                console.print(f"[bold red]{idx}. {sug.title}[/bold red]")
                console.print(f"   {sug.detail}")
                if sug.suggested_fix:
                    console.print(f"   [dim]Fix:[/dim] {sug.suggested_fix}")
        warn = warnings_table(result.warnings, title="Warnings")
        if warn is not None:
            console.print()
            console.print(warn)
        return

    risk = result.risk_level or "unknown"
    style = risk_style(risk)
    summary_rows = {
        "Risk level": f"[{style}]{risk}[/{style}]",
        "Confidence": f"{result.confidence:.2f}",
        "Suggestions": len(result.suggestions),
        "Provider": result.provider or "n/a",
        "Model": result.model or "n/a",
        "Cache": format_cache_hit(result.cache_hit),
        "AI latency": format_ms(result.latency_ms),
        "Total elapsed": format_ms(result.elapsed_ms),
        "Prompt tokens": result.prompt_tokens if result.prompt_tokens is not None else "n/a",
        "Completion tokens": (
            result.completion_tokens if result.completion_tokens is not None else "n/a"
        ),
        "Est. cost": format_cost_usd(result.estimated_cost_usd),
    }
    console.print(key_value_table(f"Review PR #{result.pull_request_number}", summary_rows))
    console.print()
    console.print(section_panel("Summary", result.summary or "(empty)", border_style="green"))

    if result.suggestions:
        table = Table(title="Suggestions", show_lines=True, expand=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Severity", width=10)
        table.add_column("Category", width=16)
        table.add_column("File", width=28)
        table.add_column("Line", width=5, justify="right")
        table.add_column("Confidence", width=10, justify="right")
        for idx, sug in enumerate(result.suggestions, start=1):
            table.add_row(
                str(idx),
                colored_severity(sug.severity),
                _format_category(sug.category),
                sug.file_path or "—",
                str(sug.line) if sug.line else "—",
                f"{sug.confidence:.0%}" if sug.confidence else "—",
            )
        console.print()
        console.print(table)

        _SEV_COLOR = {
            "critical": "bold red", "high": "red",
            "medium": "yellow", "low": "cyan", "info": "dim",
        }

        for idx, sug in enumerate(result.suggestions, start=1):
            console.print()
            sev_color = _SEV_COLOR.get(sug.severity, "white")
            console.print(f"[bold]Finding {idx}: {sug.title}[/bold]")
            console.print(f"  Severity:         [{sev_color}]{sug.severity.upper()}[/{sev_color}]")
            console.print(f"  Category:         {_format_category(sug.category)}")
            console.print(f"  File:             {sug.file_path or '—'}")
            console.print(f"  Line:             {sug.line or '—'}")
            console.print(f"  Explanation:      {sug.detail or '—'}")
            console.print(f"  Suggested Fix:    {sug.suggested_fix or '—'}")
            if sug.confidence is not None:
                console.print(f"  Confidence:       {sug.confidence:.0%}")
            else:
                console.print("  Confidence:       —")
            console.print(f"  Estimated Impact: {sug.estimated_impact or '—'}")

    warn = warnings_table(result.warnings, title="Warnings")
    if warn is not None:
        console.print()
        console.print(warn)

    meta = {
        "PR": result.pull_request_number,
        "Risk": result.risk_level,
        "Provider": result.provider or "n/a",
        "Model": result.model or "n/a",
        "Cache": "hit" if result.cache_hit is True else ("miss" if result.cache_hit is False else "n/a"),
        "Source format": result.metadata.get("source_format", "n/a"),
        "Partial parse": result.metadata.get("is_partial", False),
        "Suggestion count": len(result.suggestions),
    }
    for key, value in sorted(result.metadata.items()):
        if key in meta or key in {"source_format", "is_partial"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            meta[key] = value if value is not None else "n/a"
    console.print()
    console.print(metadata_table(meta, title="Review metadata"))


def _format_category(category: str | None) -> str:
    if not category:
        return "—"
    return category.replace("_", " ").title()
