"""`refactory repo` — repository intelligence summary."""

from __future__ import annotations

from refactory.analysis.models import RepositoryOverview
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console


def repo_cmd() -> None:
    """Analyze the local repository and print an overview."""
    try:
        container = get_container()
        overview = container.repository_analysis_service.analyze_repository()
        _render(overview)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(overview: RepositoryOverview) -> None:
    stats = overview.statistics
    health = overview.health
    lines = [
        "====================================",
        "",
        "Repository Overview",
        "",
        "====================================",
        "",
        "Name:",
        overview.name,
        "",
        "Root:",
        overview.root_path,
        "",
        "Branch:",
        overview.current_branch,
        "",
        "HEAD:",
        overview.head_sha or "(none)",
        "",
        "====================================",
        "",
        "Statistics",
        "",
        f"Tracked files:     {stats.tracked_files}",
        f"Ignored files:     {stats.ignored_files}",
        f"Commits (scanned): {stats.commit_count}",
        f"Branches:          {stats.branch_count}",
        f"Tags:              {stats.tag_count}",
        f"Contributors:      {stats.contributor_count}",
        f"Avg commits/day:   {stats.average_commits_per_day}",
        "",
        "Languages:",
    ]
    if overview.languages:
        for lang, count in overview.languages.items():
            lines.append(f"  {lang}: {count}")
    else:
        lines.append("  (none)")

    lines.extend(
        [
            "",
            "====================================",
            "",
            "Health",
            "",
            f"TODO count/density:   {health.todo_count} / {health.todo_density}",
            f"FIXME count/density:  {health.fixme_count} / {health.fixme_density}",
            f"Average file size:    {health.average_file_size}",
            f"Largest module:       {health.largest_module or '(none)'}",
            f"Orphan modules:       {len(health.orphan_modules)}",
            f"Longest dep. chain:   {health.longest_dependency_chain}",
            "",
            "====================================",
            "",
            "Top hotspots",
            "",
        ]
    )
    if overview.hotspots.files:
        for item in overview.hotspots.files[:10]:
            lines.append(
                f"  {item.path}  score={item.score}  "
                f"mods={item.modification_count}  authors={item.author_count}"
            )
    else:
        lines.append("  (none)")

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))
