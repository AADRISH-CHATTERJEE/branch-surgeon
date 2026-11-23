"""`refactory hotspots` — hotspot ranking for the local repository."""

from __future__ import annotations

import typer

from refactory.analysis.models import HotspotReport
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console


def hotspots_cmd(
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=100, help="Max ranked rows."),
) -> None:
    """Show hotspot rankings (files, directories, churn, multi-author)."""
    try:
        container = get_container()
        report = container.repository_analysis_service.get_hotspots(limit=limit)
        _render(report, limit=limit)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(report: HotspotReport, *, limit: int) -> None:
    lines = [
        "====================================",
        "",
        "Hotspots",
        "",
        f"(top {limit})",
        "",
        "====================================",
        "",
        "Files",
        "",
    ]
    if report.files:
        for item in report.files[:limit]:
            lines.append(
                f"{item.score:8.3f}  {item.path}  "
                f"mods={item.modification_count} authors={item.author_count} "
                f"recent={item.recent_modification_count} churn={item.churn}"
            )
    else:
        lines.append("(none)")

    lines.extend(["", "Directories", ""])
    if report.directories:
        for item in report.directories[:limit]:
            lines.append(
                f"{item.score:8.3f}  {item.path}/  "
                f"mods={item.modification_count} authors={item.author_count}"
            )
    else:
        lines.append("(none)")

    lines.extend(["", "High churn", ""])
    if report.high_churn_files:
        for item in report.high_churn_files[:limit]:
            lines.append(f"{item.churn:6}  {item.path}")
    else:
        lines.append("(none)")

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))
