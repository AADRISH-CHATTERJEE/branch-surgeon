"""CLI commands for the Recommendation Engine."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading


def recommend_cmd(
    top: int = typer.Option(15, "--top", "-n", help="Number of recommendations"),
    category: str = typer.Option("", "--category", "-c", help="Filter by category"),
    priority: str = typer.Option("", "--priority", "-p", help="Filter by priority"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Generate ranked engineering recommendations."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Generating recommendations..."):
            report = container.recommendation_engine.generate_recommendations(
                root, category=category or None, priority=priority or None, top=top,
            )
        if json_output:
            console.print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        else:
            lines = [
                "", "Engineering Recommendations", "===========================", "",
                f"Repository Score: {report.repository_score:.0f}/100",
                f"Recommendations: {report.total_recommendations}", "",
                f"  Critical: {report.critical_count}",
                f"  High:     {report.high_count}",
                f"  Medium:   {report.medium_count}",
                f"  Low:      {report.low_count}", "",
            ]
            if report.recommendations:
                lines.append("Top Recommendations:")
                lines.append("")
                for r in report.recommendations[:top]:
                    lines.append(f"  [{r.id}] {r.title}")
                    lines.append(f"    Priority: {r.priority.value.upper()}  Confidence: {r.confidence:.0%}  Effort: {r.estimated_effort}")
                    if r.affected_files:
                        lines.append(f"    Files: {', '.join(r.affected_files[:3])}")
                    lines.append("")
            if report.bundles:
                lines.append("Bundles:")
                for b in report.bundles[:5]:
                    lines.append(f"  [{b.id}] {b.title} ({len(b.recommendations)} items, {b.estimated_total_effort})")
                lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def health_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show repository health dashboard."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Calculating health..."):
            report = container.recommendation_engine.calculate_health(root)
        if json_output:
            console.print(json.dumps(report.model_dump(), indent=2, default=str))
        else:
            s = report.scores
            lines = [
                "", "Repository Health", "=================", "",
                f"Overall Score: {s.overall:.0f}/100", "",
                f"  Architecture:    {s.architecture:.0f}",
                f"  Maintainability: {s.maintainability:.0f}",
                f"  Security:        {s.security:.0f}",
                f"  Performance:     {s.performance:.0f}",
                f"  Testing:         {s.testing:.0f}",
                f"  Documentation:   {s.documentation:.0f}",
                f"  Technical Debt:  {s.technical_debt:.0f}", "",
            ]
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def debt_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Analyze technical debt."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Analyzing technical debt..."):
            report = container.recommendation_engine.analyze_technical_debt(root)
        if json_output:
            console.print(json.dumps(report.model_dump(), indent=2, default=str))
        else:
            lines = [
                "", "Technical Debt Analysis", "======================", "",
                f"Total Score: {report.total_score:.1f}",
                f"Items: {len(report.items)}", "",
                "Categories:",
            ]
            for cat, count in sorted(report.categories.items(), key=lambda x: -x[1]):
                lines.append(f"  {cat.replace('_', ' ').title()}: {count}")
            lines.append("")
            if report.items:
                lines.append("Top Issues:")
                for item in report.items[:10]:
                    lines.append(f"  [{item.severity.upper()}] {item.file_path}: {item.description}")
                lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def trends_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show historical engineering trends."""
    try:
        container = get_container()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Analyzing trends..."):
            report = container.recommendation_engine.analyze_trends(root)
        if json_output:
            console.print(json.dumps(report.model_dump(), indent=2, default=str))
        else:
            lines = ["", "Engineering Trends", "==================", ""]
            if report.trends:
                for t in report.trends:
                    arrow = "↑" if "increas" in t.direction or "improv" in t.direction else "↓" if "decreas" in t.direction or "degrad" in t.direction else "→"
                    lines.append(f"  {arrow} {t.metric_name}: {t.description}")
            else:
                lines.append("  No historical data available yet. Run analyses to build history.")
            lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
