"""`refactory file-history <path>` — per-file history for the local repository."""

from __future__ import annotations

import typer

from refactory.analysis.models import FileHistory
from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console


def file_history_cmd(
    path: str = typer.Argument(..., help="Repository-relative file path"),
) -> None:
    """Show creation, authors, renames, and modification history for a file."""
    try:
        container = get_container()
        history = container.repository_analysis_service.get_file_history(path)
        _render(history)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(history: FileHistory) -> None:
    lines = [
        "====================================",
        "",
        "File History",
        "",
        "====================================",
        "",
        "Path:",
        history.path,
        "",
        "Exists:",
        "yes" if history.exists else "no",
        "",
        "Modifications:",
        str(history.modification_count),
        "",
        "Created:",
        f"{history.creation_sha[:7] if history.creation_sha else 'n/a'}"
        f"  {history.creation_at.isoformat() if history.creation_at else ''}",
        "",
        "Last modified:",
        f"{history.last_modification_sha[:7] if history.last_modification_sha else 'n/a'}"
        f"  {history.last_modification_at.isoformat() if history.last_modification_at else ''}",
        "",
        f"Deleted:  {'yes' if history.was_deleted else 'no'}",
        f"Restored: {'yes' if history.was_restored else 'no'}",
        "",
        "====================================",
        "",
        "Authors",
        "",
    ]
    if history.authors:
        for author in history.authors:
            lines.append(
                f"{author.commits:4}  {author.name} <{author.email}>  "
                f"+{author.insertions}/-{author.deletions}"
            )
    else:
        lines.append("(none)")

    lines.extend(["", "Renames", ""])
    if history.rename_history:
        for event in history.rename_history:
            lines.append(
                f"{event.sha[:7]}  {event.old_path} → {event.new_path}"
            )
    else:
        lines.append("(none)")

    lines.extend(["", "Events", ""])
    if history.events:
        for event in history.events[:30]:
            lines.append(
                f"{event.short_sha}  {event.kind:8}  "
                f"{event.author_name}  {event.message}"
            )
    else:
        lines.append("(none)")

    lines.extend(["", "===================================="])
    console.print("\n".join(lines))
