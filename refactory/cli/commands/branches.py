"""`refactory branches` — local branch intelligence."""

from __future__ import annotations

from refactory.analysis.models import BranchAnalysis
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console


def branches_cmd() -> None:
    """Show local branch information (ahead/behind, stale, merged)."""
    try:
        container = get_container()
        report = container.repository_analysis_service.get_branch_information()
        _render(report)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(report: BranchAnalysis) -> None:
    lines = [
        "====================================",
        "",
        "Branches",
        "",
        "====================================",
        "",
        "Active:",
        report.active_branch,
        "",
        "Default:",
        report.default_branch or "(none)",
        "",
        "Detached:",
        "yes" if report.is_detached else "no",
        "",
        "====================================",
        "",
    ]
    if not report.branches:
        lines.append("(no branches)")
    else:
        for branch in report.branches:
            flags: list[str] = []
            if branch.is_active:
                flags.append("active")
            if branch.is_merged:
                flags.append("merged")
            if branch.is_stale:
                flags.append("stale")
            flag_text = f" [{', '.join(flags)}]" if flags else ""
            lines.extend(
                [
                    f"{branch.name}{flag_text}",
                    f"  ahead={branch.ahead} behind={branch.behind}",
                    f"  last={branch.last_commit_sha[:7] if branch.last_commit_sha else 'n/a'}"
                    f"  {branch.last_author or ''}",
                    f"  {branch.last_commit_message or ''}",
                    "",
                ]
            )

    lines.extend(
        [
            "Merged:",
            ", ".join(report.merged_branches) if report.merged_branches else "(none)",
            "",
            "Stale:",
            ", ".join(report.stale_branches) if report.stale_branches else "(none)",
            "",
            "====================================",
        ]
    )
    console.print("\n".join(lines))
