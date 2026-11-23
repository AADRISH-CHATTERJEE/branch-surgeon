"""CLI commands for PR intelligence features."""

from __future__ import annotations

import json
import time
from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warn_if_index_stale
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading


def _get_pr_service():
    container = get_container()
    return container.pr_intelligence_service, container


def _get_diff(pr_service, root: Path, base: str = "", head: str = ""):
    return pr_service.get_diff(base, head)


# ------------------------------------------------------------------
# refactory pr summary
# ------------------------------------------------------------------

def pr_summary_cmd(
    base: str = typer.Option("", "--base", "-b", help="Base ref (default: HEAD~1)"),
    head: str = typer.Option("", "--head", help="Head ref (default: HEAD)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Generate a PR summary: files, modules, impact, breaking changes."""
    try:
        pr_service, container = _get_pr_service()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Generating PR summary..."):
            diff = _get_diff(pr_service, root, base, head)
            summary = pr_service.pr_summary(diff, root)
        if json_output:
            console.print(json.dumps(summary.model_dump(), indent=2, default=str))
        else:
            lines = [
                "", "PR Summary", "==========", "",
                f"Files Changed: {summary.files_changed}",
                f"Modules: {', '.join(summary.modules_affected[:10]) or 'none'}",
                f"Architectural Impact: {summary.architectural_impact}",
                "",
            ]
            if summary.breaking_changes:
                lines.append(f"Breaking Changes ({len(summary.breaking_changes)}):")
                for bc in summary.breaking_changes[:5]:
                    lines.append(f"  - {bc}")
                lines.append("")
            lines.extend(["Summary:", summary.summary, ""])
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


# ------------------------------------------------------------------
# refactory pr risk
# ------------------------------------------------------------------

def pr_risk_cmd(
    base: str = typer.Option("", "--base", "-b", help="Base ref"),
    head: str = typer.Option("", "--head", help="Head ref"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Analyze merge risk: LOW, MEDIUM, HIGH, CRITICAL."""
    try:
        pr_service, container = _get_pr_service()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Analyzing merge risk..."):
            diff = _get_diff(pr_service, root, base, head)
            risk = pr_service.merge_risk(diff, root)
        if json_output:
            console.print(json.dumps(risk.model_dump(), indent=2, default=str))
        else:
            color = {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}
            c = color.get(risk.overall_risk.value, "white")
            lines = [
                "", "Merge Risk Analysis", "===================", "",
                f"Risk Level: [{c}]{risk.overall_risk.value.upper()}[/{c}]",
                f"Score: {risk.risk_score:.0f}/100", "",
            ]
            if risk.factors:
                lines.append("Risk Factors:")
                for f in risk.factors:
                    lines.append(f"  [{f.severity.value.upper()}] {f.name}: {f.description}")
                lines.append("")
            lines.extend([f"Recommendation: {risk.recommendation}", ""])
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


# ------------------------------------------------------------------
# refactory reviewers
# ------------------------------------------------------------------

def reviewers_cmd(
    base: str = typer.Option("", "--base", "-b", help="Base ref"),
    head: str = typer.Option("", "--head", help="Head ref"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Recommend reviewers based on ownership and expertise."""
    try:
        pr_service, container = _get_pr_service()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Finding reviewers..."):
            diff = _get_diff(pr_service, root, base, head)
            report = pr_service.recommend_reviewers(diff, root)
        if json_output:
            console.print(json.dumps(report.model_dump(), indent=2, default=str))
        else:
            lines = ["", "Recommended Reviewers", "====================", ""]
            if report.reviewers:
                for r in report.reviewers:
                    lines.append(f"  {r.name} ({r.email})  confidence={r.confidence:.0%}")
                    for reason in r.reasons:
                        lines.append(f"    - {reason}")
            else:
                lines.append("  No reviewers found.")
            lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


# ------------------------------------------------------------------
# refactory tests (PR-aware)
# ------------------------------------------------------------------

def pr_tests_cmd(
    base: str = typer.Option("", "--base", "-b", help="Base ref"),
    head: str = typer.Option("", "--head", help="Head ref"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Recommend tests: existing, missing, integration, regression."""
    try:
        pr_service, container = _get_pr_service()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Computing test recommendations..."):
            diff = _get_diff(pr_service, root, base, head)
            report = pr_service.recommend_tests(diff, root)
        if json_output:
            console.print(json.dumps(report.model_dump(), indent=2, default=str))
        else:
            lines = ["", "Test Recommendations", "====================", ""]
            if report.existing_tests:
                lines.append(f"Existing Tests ({len(report.existing_tests)}):")
                for t in report.existing_tests[:10]:
                    lines.append(f"  {t.test_file}")
                lines.append("")
            if report.missing_tests:
                lines.append(f"Missing Tests ({len(report.missing_tests)}):")
                for t in report.missing_tests[:10]:
                    lines.append(f"  {t.test_file} — {t.reason}")
                lines.append("")
            if report.integration_tests:
                lines.append(f"Integration Tests ({len(report.integration_tests)}):")
                for t in report.integration_tests[:5]:
                    lines.append(f"  {t.test_file}")
                lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


# ------------------------------------------------------------------
# refactory review (AI review)
# ------------------------------------------------------------------

def review_ai_cmd(
    base: str = typer.Option("", "--base", "-b", help="Base ref"),
    head: str = typer.Option("", "--head", help="Head ref"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Generate AI review comments (bug risk, performance, security, style)."""
    try:
        pr_service, container = _get_pr_service()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Generating AI review..."):
            diff = _get_diff(pr_service, root, base, head)
            report = pr_service.ai_review(diff, root)
        if json_output:
            console.print(json.dumps(report.model_dump(), indent=2, default=str))
        else:
            _render_ai_review(report)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render_ai_review(report) -> None:
    """Render AI review with all 8 acceptance-criteria fields per finding."""
    from rich.table import Table

    from refactory.cli.ui.style import colored_severity

    _SEVERITY_COLOR = {
        "critical": "bold red",
        "warning": "yellow",
        "info": "dim",
    }
    _CATEGORY_LABEL = {
        "bug_risk": "Bug Risk",
        "performance": "Performance",
        "security": "Security",
        "style": "Style",
        "maintainability": "Maintainability",
        "missing_tests": "Missing Tests",
        "documentation": "Documentation",
    }

    console.print()
    console.print("[bold]AI Review[/bold]")
    console.print("=" * 60)

    if not report.comments:
        console.print("\n  [green]No findings.[/green]\n")
    else:
        table = Table(
            title=f"Findings ({len(report.comments)})",
            show_lines=True, expand=True,
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Severity", width=10)
        table.add_column("Category", width=16)
        table.add_column("File", width=28)
        table.add_column("Line", width=5, justify="right")
        table.add_column("Confidence", width=10, justify="right")

        for idx, c in enumerate(report.comments[:30], 1):
            cat_label = _CATEGORY_LABEL.get(c.category.value, c.category.value)
            table.add_row(
                str(idx),
                colored_severity(c.severity),
                cat_label,
                c.file or "—",
                str(c.line) if c.line else "—",
                f"{c.confidence:.0%}" if c.confidence else "—",
            )

        console.print()
        console.print(table)

        for idx, c in enumerate(report.comments[:30], 1):
            sev_color = _SEVERITY_COLOR.get(c.severity, "white")
            cat_label = _CATEGORY_LABEL.get(c.category.value, c.category.value)
            console.print()
            console.print(f"[bold]Finding {idx}[/bold]")
            console.print(f"  Severity:         [{sev_color}]{c.severity.upper()}[/{sev_color}]")
            console.print(f"  Category:         {cat_label}")
            console.print(f"  File:             {c.file or '—'}")
            console.print(f"  Line:             {c.line or '—'}")
            console.print(f"  Explanation:      {c.explanation}")
            console.print(f"  Suggested Fix:    {c.suggested_fix or '—'}")
            console.print(f"  Confidence:       {c.confidence:.0%}" if c.confidence else "  Confidence:       —")
            console.print(f"  Estimated Impact: {c.estimated_impact or '—'}")

    console.print()
    console.print("[bold]Summary[/bold]")
    console.print(report.summary or "(no summary)")
    console.print()


# ------------------------------------------------------------------
# refactory merge-readiness
# ------------------------------------------------------------------

def merge_readiness_cmd(
    base: str = typer.Option("", "--base", "-b", help="Base ref"),
    head: str = typer.Option("", "--head", help="Head ref"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Compute merge readiness score: review, tests, risk, security."""
    try:
        pr_service, container = _get_pr_service()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Computing merge readiness..."):
            diff = _get_diff(pr_service, root, base, head)
            report = pr_service.merge_readiness(diff, root)
        if json_output:
            console.print(json.dumps(report.model_dump(), indent=2, default=str))
        else:
            status_color = {
                "ready": "green", "needs_work": "yellow", "block_merge": "red"
            }
            c = status_color.get(report.status.value, "white")
            lines = [
                "", "Merge Readiness", "===============", "",
                f"Overall Score: {report.overall_score:.0%}",
                f"Status: [{c}]{report.status.value.replace('_', ' ').upper()}[/{c}]", "",
                f"  Risk:           {report.risk_score:.0%}",
                f"  Security:       {report.security_score:.0%}",
                f"  Tests:          {report.test_coverage_score:.0%}",
                f"  Architecture:   {report.architecture_score:.0%}",
                f"  Documentation:  {report.documentation_score:.0%}", "",
            ]
            if report.blockers:
                lines.append("Blockers:")
                for b in report.blockers:
                    lines.append(f"  - {b}")
                lines.append("")
            lines.extend([f"Recommendation: {report.recommendation}", ""])
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


# ------------------------------------------------------------------
# refactory explain-change
# ------------------------------------------------------------------

def explain_change_cmd(
    base: str = typer.Option("", "--base", "-b", help="Base ref"),
    head: str = typer.Option("", "--head", help="Head ref"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Explain why the change matters, downstream effects, migration concerns."""
    try:
        pr_service, container = _get_pr_service()
        root = Path(container.git_service.get_root_path()).resolve()
        with loading("Generating explanation..."):
            diff = _get_diff(pr_service, root, base, head)
            explanation = pr_service.explain_change(diff, root)
        if json_output:
            console.print(json.dumps(explanation.model_dump(), indent=2, default=str))
        else:
            lines = [
                "", "Change Explanation", "==================", "",
                explanation.summary, "",
            ]
            if explanation.downstream_effects:
                lines.append("Downstream Effects:")
                for e in explanation.downstream_effects:
                    lines.append(f"  - {e}")
                lines.append("")
            if explanation.migration_concerns:
                lines.append("Migration Concerns:")
                for m in explanation.migration_concerns:
                    lines.append(f"  - {m}")
                lines.append("")
            if explanation.architectural_consequences:
                lines.append("Architectural Consequences:")
                for a in explanation.architectural_consequences:
                    lines.append(f"  - {a}")
                lines.append("")
            lines.append(f"Risk: {explanation.risk_level.value.upper()}")
            lines.append("")
            console.print("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)
