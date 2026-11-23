"""CLI embed commands must delegate to container embedding/indexer services."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.embedding.models import EmbeddingRunResult, EmbeddingStatus
from refactory.indexer.models import RepositoryIndex, RepositoryStatistics, RepositorySummary

runner = CliRunner()


def _index() -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="C:/tmp/demo",
            repository_name="demo",
            total_indexed_files=10,
            timestamp=datetime.now(timezone.utc),
        ),
        statistics=RepositoryStatistics(),
    )


def _patch(mocker, *, embedding_service: MagicMock, index: RepositoryIndex | None = None):
    git = MagicMock()
    git.get_repository_metadata.return_value.name = "demo"
    git.get_repository_metadata.return_value.root_path = "C:/tmp/demo"

    indexer = MagicMock()
    indexer.load_index.return_value = _index() if index is None else index

    container = MagicMock()
    container.git_service = git
    container.indexer_service = indexer
    container.embedding_service = embedding_service
    mocker.patch("refactory.cli.commands.embed.get_container", return_value=container)
    return container


def test_embed_command_renders_summary(mocker):
    embedding = MagicMock()
    embedding.embed_repository.return_value = EmbeddingRunResult(
        model="BAAI/bge-small-en-v1.5",
        repository_symbols=33,
        total_stored_vectors=33,
        files_processed=10,
        embedded=10,
        skipped=0,
        newly_embedded_symbols=33,
        reused_vectors=0,
        symbols_embedded=33,
        elapsed_seconds=1.5,
        storage_path="C:/tmp/demo/.refactory/embeddings.json",
    )
    _patch(mocker, embedding_service=embedding)

    result = runner.invoke(app, ["embed"])

    assert result.exit_code == 0, result.stdout
    embedding.embed_repository.assert_called_once()
    assert "Repository Embeddings" in result.stdout
    assert "Model: BAAI/bge-small-en-v1.5" in result.stdout
    assert "Repository Symbols: 33" in result.stdout
    assert "Total Stored Vectors: 33" in result.stdout
    assert "This Run" in result.stdout
    assert "Files processed: 10" in result.stdout
    assert "Files embedded: 10" in result.stdout
    assert "Files skipped: 0" in result.stdout
    assert "Newly embedded symbols: 33" in result.stdout
    assert "Reused vectors: 0" in result.stdout
    assert "1.50 sec" in result.stdout


def test_embed_second_run_shows_skips(mocker):
    embedding = MagicMock()
    embedding.embed_repository.return_value = EmbeddingRunResult(
        model="BAAI/bge-small-en-v1.5",
        repository_symbols=23,
        total_stored_vectors=23,
        files_processed=10,
        embedded=0,
        skipped=10,
        newly_embedded_symbols=0,
        reused_vectors=23,
        symbols_embedded=0,
        elapsed_seconds=0.05,
    )
    _patch(mocker, embedding_service=embedding)

    result = runner.invoke(app, ["embed"])

    assert result.exit_code == 0, result.stdout
    assert "Repository Symbols: 23" in result.stdout
    assert "Files embedded: 0" in result.stdout
    assert "Files skipped: 10" in result.stdout
    assert "Newly embedded symbols: 0" in result.stdout
    assert "Reused vectors: 23" in result.stdout


def test_embed_status_command(mocker):
    embedding = MagicMock()
    embedding.status.return_value = EmbeddingStatus(
        model="BAAI/bge-small-en-v1.5",
        total_embedded_symbols=42,
        total_files=10,
        last_update=datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc),
        storage_path="C:/tmp/demo/.refactory/embeddings.json",
        store_exists=True,
    )
    _patch(mocker, embedding_service=embedding)

    result = runner.invoke(app, ["embed", "status"])

    assert result.exit_code == 0, result.stdout
    assert "Embedding Status" in result.stdout
    assert "BAAI/bge-small-en-v1.5" in result.stdout
    assert "Total embedded symbols: 42" in result.stdout
    assert "embeddings.json" in result.stdout


def test_embed_requires_index(mocker):
    embedding = MagicMock()
    git = MagicMock()
    git.get_repository_metadata.return_value.name = "demo"
    git.get_repository_metadata.return_value.root_path = "C:/tmp/demo"
    indexer = MagicMock()
    indexer.load_index.return_value = None
    container = MagicMock()
    container.git_service = git
    container.indexer_service = indexer
    container.embedding_service = embedding
    mocker.patch("refactory.cli.commands.embed.get_container", return_value=container)

    result = runner.invoke(app, ["embed"])

    assert result.exit_code == 1
    assert "index" in result.stdout.lower()
    embedding.embed_repository.assert_not_called()


def test_embed_force_flag_passed(mocker):
    embedding = MagicMock()
    embedding.embed_repository.return_value = EmbeddingRunResult(
        files_processed=1,
        embedded=1,
        skipped=0,
        elapsed_seconds=0.1,
    )
    _patch(mocker, embedding_service=embedding)

    result = runner.invoke(app, ["embed", "--force"])

    assert result.exit_code == 0, result.stdout
    kwargs = embedding.embed_repository.call_args.kwargs
    assert kwargs.get("force") is True
