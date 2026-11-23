"""`refactory history` — recent local commits (presentation only)."""

from __future__ import annotations

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.git.models import CommitSummary


def history_cmd(
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        min=1,
        max=500,
        help="Maximum number of commits to show.",
    ),
) -> None:
    """List recent commits from HEAD (hash, author, date, message)."""
    try:
        container = get_container()
        commits = container.commit_service.get_recent_commits(limit=limit)
        _render(commits, limit=limit)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(commits: list[CommitSummary], *, limit: int) -> None:
    lines = [
        "====================================",
        "",
        "Commit History",
        "",
        f"(showing up to {limit})",
        "",
        "====================================",
        "",
    ]
    if not commits:
        lines.append("(no commits)")
    else:
        for item in commits:
            lines.extend(
                [
                    f"{item.short_sha}  {item.committed_at.date().isoformat()}",
                    f"  {item.author_name} <{item.author_email}>",
                    f"  {item.message or '(empty)'}",
                    f"  {item.sha}",
                    "",
                ]
            )
    lines.append("====================================")
    console.print("\n".join(lines))
