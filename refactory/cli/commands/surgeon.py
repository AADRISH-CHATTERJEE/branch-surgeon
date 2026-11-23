"""`refactory surgeon` — Branch Surgeon: structural branch health analysis."""

from __future__ import annotations

import json
import time

import typer
from typing_extensions import Annotated

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.surgeon.models import (
    BranchAnalysis,
    BranchIssue,
    BranchRecommendation,
    IssueSeverity,
)


def surgeon_cmd(
    branch: Annotated[
        str | None,
        typer.Option("--branch", "-b", help="Branch to analyze (default: current branch)"),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show per-commit and per-file details"),
    ] = False,
) -> None:
    """Analyze a branch for structural problems before merge."""
    try:
        container = get_container()
        started = time.perf_counter()
        label = f"branch '{branch}'" if branch else "current branch"
        with loading(f"Branch Surgeon: analyzing {label}…"):
            analysis = container.branch_surgeon_service.analyze(branch)
        elapsed = (time.perf_counter() - started) * 1000.0

        try:
            from refactory.history.helpers import record_history

            h = analysis.health
            record_history(
                container,
                analysis_type="branch_surgeon",
                status="completed",
                duration_ms=elapsed,
                summary=(
                    f"Branch Surgeon: {analysis.branch} score {h.score}/100 "
                    f"({h.grade}), {len(analysis.issues)} issue(s)"
                ),
                result_data={
                    "branch": analysis.branch,
                    "base_branch": analysis.base_branch,
                    "score": h.score,
                    "grade": h.grade,
                    "issue_count": len(analysis.issues),
                    "recommendation_count": len(analysis.recommendations),
                },
                metadata={"source": "cli"},
            )
        except Exception:  # noqa: BLE001
            pass

        if output_json:
            console.print(analysis.model_dump_json(indent=2))
        else:
            _render(analysis, verbose=verbose, elapsed_ms=elapsed)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_SEV_LABEL = {
    IssueSeverity.LOW: "LOW    ",
    IssueSeverity.MEDIUM: "MEDIUM ",
    IssueSeverity.HIGH: "HIGH   ",
    IssueSeverity.CRITICAL: "CRITICAL",
}


def _render(analysis: BranchAnalysis, *, verbose: bool, elapsed_ms: float) -> None:
    h = analysis.health
    lines: list[str] = [
        "",
        "Branch Surgeon",
        "==============",
        "",
        f"Current Branch : {analysis.branch}",
        f"Compared To    : {analysis.base_branch}",
        f"Repository     : {analysis.repository}",
        "",
        f"Changed Files  : {h.changed_file_count}",
        f"Commits        : {h.commit_count}",
        f"Insertions     : +{h.total_insertions}",
        f"Deletions      : -{h.total_deletions}",
        f"Branch Age     : {h.branch_age_days:.1f} days",
        "",
        f"Health Score   : {h.score}/100  (Grade: {h.grade})",
        f"Conflict Risk  : {h.merge_conflict_risk.value.upper()}",
        "",
    ]

    if analysis.issues:
        lines.append("Problems")
        lines.append("--------")
        for issue in analysis.issues:
            sev = _SEV_LABEL.get(issue.severity, issue.severity.value.upper())
            lines.append(f"  [{sev}]  {issue.title}")
            if verbose and issue.detail:
                for part in issue.detail.split(". "):
                    if part.strip():
                        lines.append(f"           {part.strip()}")
            if verbose and issue.files:
                lines.append(f"           Files: {', '.join(issue.files[:5])}")
            if verbose and issue.commits:
                lines.append(f"           Commits: {', '.join(issue.commits[:5])}")
        lines.append("")
    else:
        lines += ["Problems", "--------", "  (none detected)", ""]

    if analysis.recommendations:
        lines.append("Suggestions")
        lines.append("-----------")
        for rec in analysis.recommendations:
            lines.append(f"  -> {rec.title}")
            if verbose and rec.detail:
                lines.append(f"     {rec.detail}")
            if verbose and rec.files:
                lines.append(f"     Files: {', '.join(rec.files[:5])}")
        lines.append("")
    else:
        lines += ["Suggestions", "-----------", "  (none)", ""]

    if verbose and analysis.commits:
        lines.append("Commits on branch")
        lines.append("-----------------")
        for c in analysis.commits[:20]:
            lines.append(
                f"  {c.short_sha}  {c.committed_at.strftime('%Y-%m-%d')}  "
                f"+{c.insertions}/-{c.deletions}  {c.message[:60]}"
            )
        if len(analysis.commits) > 20:
            lines.append(f"  ... and {len(analysis.commits) - 20} more")
        lines.append("")

    if verbose and analysis.changed_files:
        lines.append("Changed files")
        lines.append("-------------")
        for f in analysis.changed_files[:30]:
            flags = []
            if f.is_test:
                flags.append("test")
            if f.is_security_sensitive:
                flags.append("security")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(
                f"  {f.path}  ({f.commit_count} commit(s), "
                f"+{f.insertions}/-{f.deletions}){flag_str}"
            )
        if len(analysis.changed_files) > 30:
            lines.append(f"  ... and {len(analysis.changed_files) - 30} more")
        lines.append("")

    if analysis.notes:
        lines.append("Notes")
        lines.append("-----")
        for note in analysis.notes:
            lines.append(f"  {note}")
        lines.append("")

    lines.append(f"Analysis completed in {format_ms(elapsed_ms)}")
    lines.append("")

    console.print("\n".join(lines))
