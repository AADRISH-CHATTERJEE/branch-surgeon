"""`refactory commit <hash>` — local commit inspection (presentation only)."""

from __future__ import annotations

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.git.models import CommitDetail, CommitDiff, CommitFileChange


def commit_cmd(
    hash: str = typer.Argument(..., help="Commit hash (full or abbreviated)"),
) -> None:
    """Show commit metadata, changed files, statistics, and a diff summary."""
    try:
        container = get_container()
        service = container.commit_service
        detail = service.get_commit(hash)
        diff = service.get_commit_diff(hash)
        _render(detail, diff)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(detail: CommitDetail, diff: CommitDiff) -> None:
    stats = diff.statistics
    parents = ", ".join(p[:7] for p in detail.parent_shas) or "(none)"
    lines = [
        "====================================",
        "",
        "Commit",
        "",
        "====================================",
        "",
        "Hash:",
        detail.sha,
        "",
        "Short:",
        detail.short_sha,
        "",
        "Author:",
        f"{detail.author_name} <{detail.author_email}>",
        "",
        "Date:",
        detail.committed_at.isoformat(),
        "",
        "Parents:",
        parents,
        "",
        "Merge:",
        "yes" if detail.is_merge else "no",
        "",
        "Message:",
        detail.message or "(empty)",
        "",
        "====================================",
        "",
        "Changed Files",
        "",
    ]
    if diff.files:
        for item in diff.files:
            lines.append(_format_file(item))
    else:
        lines.append("(none)")

    lines.extend(
        [
            "",
            "====================================",
            "",
            "Statistics",
            "",
            f"Files changed: {stats.files_changed}",
            f"Insertions:    {stats.insertions}",
            f"Deletions:     {stats.deletions}",
            "",
            "====================================",
            "",
            "Diff Summary",
            "",
        ]
    )
    summary = _diff_summary(diff)
    lines.append(summary if summary else "(empty)")
    lines.extend(["", "===================================="])
    console.print("\n".join(lines))


def _format_file(item: CommitFileChange) -> str:
    label = item.path
    if item.old_path and item.old_path != item.path:
        label = f"{item.old_path} → {item.path}"
    binary = " [binary]" if item.is_binary else ""
    return (
        f"{item.kind.value:12} {label}  "
        f"+{item.insertions}/-{item.deletions}{binary}"
    )


def _diff_summary(diff: CommitDiff) -> str:
    """Short per-file summary (not the full patch body)."""
    if not diff.files:
        return ""
    rows: list[str] = []
    for item in diff.files:
        if item.is_binary:
            rows.append(f"{item.path}: binary")
            continue
        rows.append(f"{item.path}: +{item.insertions}/-{item.deletions}")
    return "\n".join(rows)
