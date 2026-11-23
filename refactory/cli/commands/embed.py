"""`refactory embed` — presentation adapter for EmbeddingService."""

from __future__ import annotations

from pathlib import Path

import typer

from refactory.cli.commands._common import get_container, handle_error, warm_backend_client
from refactory.cli.ui.console import console
from refactory.embedding.models import EmbeddingRunResult, EmbeddingStatus
from refactory.embedding.service import require_index

embed_app = typer.Typer(
    name="embed",
    help="[dev] Generate semantic embeddings from the repository index.",
    invoke_without_command=True,
    no_args_is_help=False,
)


@embed_app.callback()
def embed_root(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Re-embed even when hashes match."),
    incremental: bool = typer.Option(
        True, "--incremental/--full", help="Incremental mode (default). Use --full to rebuild.",
    ),
) -> None:
    """Embed indexed repository entities (incremental by content hash)."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        container = get_container()
        warm_backend_client(container)
        repository = container.git_service.get_repository_metadata()
        root = Path(repository.root_path)
        index = require_index(container.indexer_service.load_index(root))
        should_force = force or not incremental
        result = container.embedding_service.embed_repository(
            index,
            root=root,
            force=should_force,
        )
        _render_run(result)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


@embed_app.command("status")
def embed_status() -> None:
    """Show embedding model, store stats, and storage location."""
    try:
        container = get_container()
        repository = container.git_service.get_repository_metadata()
        root = Path(repository.root_path)
        status = container.embedding_service.status(root)
        _render_status(status)
    except Exception as exc:  # noqa: BLE001
        handle_error(exc)


def _render_run(result: EmbeddingRunResult) -> None:
    lines = [
        "====================================",
        "",
        "Repository Embeddings",
        "",
        "====================================",
        "",
        f"Model: {result.model}",
        "",
        f"Repository Symbols: {result.repository_symbols}",
        "",
        f"Total Stored Vectors: {result.total_stored_vectors}",
        "",
        "------------------------------",
        "",
        "This Run",
        "",
        f"Files processed: {result.files_processed}",
        "",
        f"Files embedded: {result.embedded}",
        "",
        f"Files skipped: {result.skipped}",
        "",
        f"Newly embedded symbols: {result.newly_embedded_symbols}",
        "",
        f"Reused vectors: {result.reused_vectors}",
        "",
        f"Elapsed: {result.elapsed_seconds:.2f} sec",
        "",
        "====================================",
    ]
    console.print("\n".join(lines))


def _render_status(status: EmbeddingStatus) -> None:
    last = status.last_update.isoformat() if status.last_update else "(never)"
    lines = [
        "====================================",
        "",
        "Embedding Status",
        "",
        "====================================",
        "",
        f"Embedding model: {status.model}",
        "",
        f"Total embedded symbols: {status.total_embedded_symbols}",
        "",
        f"Files in store: {status.total_files}",
        "",
        f"Last update: {last}",
        "",
        f"Storage location: {status.storage_path}",
        "",
        "====================================",
    ]
    console.print("\n".join(lines))
