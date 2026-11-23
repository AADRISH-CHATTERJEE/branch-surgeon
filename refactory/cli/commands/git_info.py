"""Temporary development command: `refactory git-info`.

Presentation-only: loads GitService via DI and prints a typed snapshot.
Safe to remove once GitService is validated against real repositories.
"""

from __future__ import annotations

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.git.models import GitRepositoryInfo


def git_info() -> None:
    """Print local repository information discovered from the current directory."""
    try:
        container = get_container()
        info = container.git_service.get_repository_info()
        _render(info)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(info: GitRepositoryInfo) -> None:
    status = info.working_tree
    commit = info.commit
    short = commit.short_sha if commit else (info.head_sha[:7] if info.head_sha else "n/a")
    tree_label = "Dirty" if info.is_dirty else "Clean"

    lines = [
        "====================================",
        "",
        "Repository Information",
        "",
        "====================================",
        "",
        "Repository:",
        info.name,
        "",
        "Root:",
        info.root_path,
        "",
        "Current Branch:",
        info.current_branch,
        "",
        "Current Commit:",
        short,
    ]
    if commit:
        lines.extend(
            [
                "",
                "Commit Message:",
                commit.message,
                "",
                "Commit Author:",
                f"{commit.author_name} <{commit.author_email}>",
            ]
        )
    lines.extend(
        [
            "",
            "Remote:",
            info.remote_url or "None",
            "",
            "Default Branch:",
            info.default_branch or "None",
            "",
            "Working Tree:",
            tree_label,
            "",
            "Modified Files",
            "",
        ]
    )
    if status.modified_files:
        lines.extend(item.path for item in status.modified_files)
    else:
        lines.append("(none)")

    lines.extend(["", "Deleted Files", ""])
    if status.deleted_files:
        lines.extend(item.path for item in status.deleted_files)
    else:
        lines.append("(none)")

    lines.extend(["", "Staged Files", ""])
    if status.staged_files:
        lines.extend(item.path for item in status.staged_files)
    else:
        lines.append("(none)")

    lines.extend(["", "Untracked Files", ""])
    if status.untracked_files:
        lines.extend(status.untracked_files)
    else:
        lines.append("(none)")

    lines.extend(
        [
            "",
            f"Changed File Count: {status.changed_file_count}",
            "",
            "====================================",
        ]
    )
    console.print("\n".join(lines))
