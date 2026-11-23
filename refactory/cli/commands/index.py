"""`refactory index` — presentation adapter for deterministic repository indexing."""

from __future__ import annotations

import typer

from refactory.cli.commands._common import get_container, handle_error
from refactory.cli.ui.console import console
from refactory.cli.ui.panels import print_banner
from refactory.cli.ui.progress import loading
from refactory.cli.ui.style import format_ms
from refactory.cli.ui.tables import key_value_table
from refactory.indexer.models import RepositoryIndex


def index(
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild even if hashes match."),
) -> None:
    """Index the current Git repository via IndexerService (no embeddings / AI)."""
    try:
        container = get_container()
        repository = container.git_service.get_repository_metadata()
        with loading(f"Indexing {repository.name}…"):
            result = container.indexer_service.build_index(
                repository.root_path,
                repository_name=repository.name,
                force=force,
            )
        _render(result)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render(index: RepositoryIndex) -> None:
    summary = index.summary
    stats = index.statistics
    reused = stats.reused_unchanged_files
    print_banner("Repository index")
    console.print(
        key_value_table(
            "Repository summary",
            {
                "Repository": summary.repository_name,
                "Indexed files": summary.total_indexed_files,
                "Ignored files": summary.ignored_file_count,
                "Functions": summary.total_functions,
                "Classes": summary.total_classes,
                "Imports": summary.total_imports,
                "TODOs": summary.todo_count,
            },
        )
    )
    console.print()
    console.print(
        key_value_table(
            "This run",
            {
                "Files parsed": stats.files_parsed,
                "Cache reused": reused,
                "Newly added": stats.newly_added_files,
                "Modified": stats.modified_files,
                "Deleted": stats.deleted_files,
                "Ignored": stats.ignored_files,
                "Parse failures": stats.parse_failures,
                "Elapsed": format_ms(stats.indexing_duration_seconds * 1000.0),
            },
        )
    )
