"""Tests for EmbeddingService → PersistenceService integration.

Verifies that:
  - Successful embedding runs persist metadata to the relational database
  - Only metadata is persisted — vectors are NOT stored in SQL
  - PersistenceService APIs are called correctly
  - Database failures never cause embedding generation to fail
  - Existing behaviour is unchanged when PersistenceService is None
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from refactory.core.logger import get_service_logger
from refactory.embedding.models import (
    EmbeddingRunResult,
    EmbeddingStore,
    FileEmbeddingRecord,
)
from refactory.embedding.service import EmbeddingService
from refactory.indexer.models import (
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class FakeEmbeddingProvider:
    """Deterministic provider: vector = first 8 floats from sha256 of text."""

    def __init__(self, model_name: str = "fake-model") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[:8]]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _index(files: list[IndexedFile], *, name: str = "test-repo") -> RepositoryIndex:
    symbols: list[IndexedSymbol] = []
    for f in files:
        symbols.extend(f.symbols)
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="/tmp/test-repo",
            repository_name=name,
            total_indexed_files=len(files),
            timestamp=datetime.now(timezone.utc),
        ),
        statistics=RepositoryStatistics(),
        files=files,
        symbols=symbols,
        import_references=[],
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _file(
    path: str,
    *,
    content_hash: str = "abc123",
    module: str | None = None,
    functions: list[str] | None = None,
    classes: list[str] | None = None,
) -> IndexedFile:
    module = module or path.replace("/", ".").removesuffix(".py")
    symbols: list[IndexedSymbol] = [
        IndexedSymbol(
            name=module,
            kind=SymbolKind.MODULE,
            file_path=path,
            start_line=1,
            end_line=100,
        ),
    ]
    for fn in (functions or []):
        symbols.append(
            IndexedSymbol(
                name=fn,
                kind=SymbolKind.FUNCTION,
                file_path=path,
                start_line=10,
                end_line=20,
            )
        )
    for cls in (classes or []):
        symbols.append(
            IndexedSymbol(
                name=cls,
                kind=SymbolKind.CLASS,
                file_path=path,
                start_line=30,
                end_line=50,
            )
        )
    return IndexedFile(
        relative_path=path,
        language="python",
        file_size=500,
        content_hash=content_hash,
        modified_at=datetime.now(timezone.utc),
        module_name=module,
        symbols=symbols,
        import_references=[],
    )


def _make_persistence_mock() -> MagicMock:
    mock = MagicMock()
    mock.get_or_create_repository.return_value = {
        "id": "repo-001",
        "name": "test-repo",
        "root_path": "/tmp/test-repo",
        "default_branch": "main",
        "remote_url": None,
        "created_at": None,
        "updated_at": None,
    }
    mock.persist_file.return_value = {
        "id": "file-001",
        "repository_id": "repo-001",
        "path": "",
        "language": "python",
        "sha256": None,
        "size": 0,
        "last_indexed": None,
    }
    mock.persist_embeddings.return_value = 0
    return mock


def _build_service(
    *,
    persistence: MagicMock | None = "DEFAULT",
    provider: FakeEmbeddingProvider | None = None,
) -> tuple[EmbeddingService, MagicMock | None]:
    if persistence == "DEFAULT":
        persistence = _make_persistence_mock()
    service = EmbeddingService(
        provider=provider or FakeEmbeddingProvider(),
        logger=get_service_logger("test.embedding.persist"),
        persistence_service=persistence,
    )
    return service, persistence


def _run_embed(service, files, *, tmp_path):
    """Helper to run embed_repository with a temp directory."""
    index = _index(files)
    return service.embed_repository(index, root=tmp_path)


# ---------------------------------------------------------------------------
# Tests: Core persistence
# ---------------------------------------------------------------------------


class TestEmbeddingPersistence:

    def test_persist_embeddings_called(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        persistence.persist_embeddings.assert_called()

    def test_get_or_create_repository_called(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py")], tmp_path=tmp_path)
        persistence.get_or_create_repository.assert_called_once_with(
            name="test-repo",
            root_path="/tmp/test-repo",
            default_branch="main",
        )

    def test_persist_file_called_per_file(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [
            _file("auth.py", functions=["login"]),
            _file("util.py", functions=["helper"]),
        ], tmp_path=tmp_path)
        assert persistence.persist_file.call_count == 2

    def test_metadata_contains_chunk_id(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        calls = persistence.persist_embeddings.call_args_list
        all_dicts = []
        for c in calls:
            all_dicts.extend(c[0][1])
        assert any("chunk_id" in d for d in all_dicts)

    def test_metadata_contains_provider(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        calls = persistence.persist_embeddings.call_args_list
        all_dicts = []
        for c in calls:
            all_dicts.extend(c[0][1])
        assert all(d["provider"] == "fake-model" for d in all_dicts)

    def test_metadata_contains_model(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        calls = persistence.persist_embeddings.call_args_list
        all_dicts = []
        for c in calls:
            all_dicts.extend(c[0][1])
        assert all(d["model"] == "fake-model" for d in all_dicts)

    def test_metadata_contains_vector_reference(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        calls = persistence.persist_embeddings.call_args_list
        all_dicts = []
        for c in calls:
            all_dicts.extend(c[0][1])
        assert all("vector_reference" in d for d in all_dicts)
        assert all(d["vector_reference"].startswith("chroma:") for d in all_dicts)

    def test_result_unchanged(self, tmp_path):
        service_with, _ = _build_service()
        service_without, _ = _build_service(persistence=None)

        files = [_file("auth.py", functions=["login"])]
        result_with = _run_embed(service_with, files, tmp_path=tmp_path / "a")
        result_without = _run_embed(service_without, files, tmp_path=tmp_path / "b")

        assert isinstance(result_with, EmbeddingRunResult)
        assert result_with.model == result_without.model
        assert result_with.total_stored_vectors == result_without.total_stored_vectors
        assert result_with.newly_embedded_symbols == result_without.newly_embedded_symbols


class TestVectorsNotPersisted:

    def test_no_vector_data_in_metadata(self, tmp_path):
        """Verify that actual vector floats are never sent to PersistenceService."""
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        calls = persistence.persist_embeddings.call_args_list
        for c in calls:
            for emb_dict in c[0][1]:
                for key, value in emb_dict.items():
                    assert not isinstance(value, list), \
                        f"Vector data found in metadata key '{key}'"

    def test_chunk_ids_are_strings(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [_file("auth.py", classes=["User"])], tmp_path=tmp_path)
        calls = persistence.persist_embeddings.call_args_list
        for c in calls:
            for emb_dict in c[0][1]:
                assert isinstance(emb_dict["chunk_id"], str)


class TestFailureHandling:

    def test_persist_failure_does_not_abort_embedding(self, tmp_path):
        service, persistence = _build_service()
        persistence.persist_embeddings.side_effect = RuntimeError("DB connection lost")
        result = _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        assert isinstance(result, EmbeddingRunResult)
        assert result.total_stored_vectors > 0

    def test_repository_creation_failure_does_not_abort(self, tmp_path):
        service, persistence = _build_service()
        persistence.get_or_create_repository.side_effect = ConnectionError("timeout")
        result = _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        assert isinstance(result, EmbeddingRunResult)

    def test_persist_file_failure_does_not_abort(self, tmp_path):
        service, persistence = _build_service()
        persistence.persist_file.side_effect = RuntimeError("file table locked")
        result = _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        assert isinstance(result, EmbeddingRunResult)

    def test_failure_logged_with_error(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.persist_embeddings.side_effect = RuntimeError("disk full")
        service = EmbeddingService(
            provider=FakeEmbeddingProvider(),
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _index([_file("auth.py", functions=["login"])])
        service.embed_repository(index, root=tmp_path)
        mock_logger.error.assert_called_once()
        error_str = str(mock_logger.error.call_args)
        assert "disk full" in error_str
        assert "test-repo" in error_str

    def test_failure_log_includes_traceback(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.get_or_create_repository.side_effect = ValueError("bad data")
        service = EmbeddingService(
            provider=FakeEmbeddingProvider(),
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _index([_file("auth.py")])
        service.embed_repository(index, root=tmp_path)
        error_str = str(mock_logger.error.call_args)
        assert "ValueError" in error_str or "bad data" in error_str


class TestNoPersistenceService:

    def test_embedding_works_without_persistence(self, tmp_path):
        service, _ = _build_service(persistence=None)
        result = _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        assert isinstance(result, EmbeddingRunResult)
        assert result.total_stored_vectors > 0

    def test_no_persistence_no_errors(self, tmp_path):
        service, _ = _build_service(persistence=None)
        result = _run_embed(service, [
            _file("a.py", functions=["fa"]),
            _file("b.py", functions=["fb"]),
        ], tmp_path=tmp_path)
        assert result.files_processed == 2

    def test_default_persistence_is_none(self):
        service = EmbeddingService(
            provider=FakeEmbeddingProvider(),
            logger=get_service_logger("test"),
        )
        assert service._persistence is None

    def test_json_store_still_written(self, tmp_path):
        service, _ = _build_service(persistence=None)
        _run_embed(service, [_file("auth.py", functions=["login"])], tmp_path=tmp_path)
        store_path = service.storage_path(tmp_path)
        assert store_path.is_file()


class TestPersistenceLogging:

    def test_success_log_contains_repository(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        service = EmbeddingService(
            provider=FakeEmbeddingProvider(),
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _index([_file("a.py", functions=["fa"])])
        service.embed_repository(index, root=tmp_path)
        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "persisted" in str(c).lower()]
        assert len(persist_calls) >= 1
        log_str = str(persist_calls[0])
        assert "test-repo" in log_str

    def test_success_log_contains_counts(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        service = EmbeddingService(
            provider=FakeEmbeddingProvider(),
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _index([_file("a.py", functions=["fa"])])
        service.embed_repository(index, root=tmp_path)
        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "persisted" in str(c).lower()]
        assert len(persist_calls) >= 1
        log_str = str(persist_calls[0])
        assert "embeddings=" in log_str
        assert "files=" in log_str

    def test_success_log_contains_elapsed(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        service = EmbeddingService(
            provider=FakeEmbeddingProvider(),
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _index([_file("a.py", functions=["fa"])])
        service.embed_repository(index, root=tmp_path)
        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "elapsed_ms" in str(c)]
        assert len(persist_calls) >= 1


class TestEdgeCases:

    def test_zero_files(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [], tmp_path=tmp_path)
        persistence.persist_embeddings.assert_not_called()

    def test_file_with_no_symbols(self, tmp_path):
        """A file with only a MODULE symbol still produces file+module embeddings."""
        service, persistence = _build_service()
        f = _file("empty.py")
        _run_embed(service, [f], tmp_path=tmp_path)
        persistence.persist_embeddings.assert_called()
        calls = persistence.persist_embeddings.call_args_list
        all_dicts = []
        for c in calls:
            all_dicts.extend(c[0][1])
        chunk_ids = [d["chunk_id"] for d in all_dicts]
        assert any("file" in cid for cid in chunk_ids)
        assert any("module" in cid for cid in chunk_ids)

    def test_multiple_files_all_persisted(self, tmp_path):
        service, persistence = _build_service()
        files = [_file(f"mod_{i}.py", functions=[f"func_{i}"]) for i in range(5)]
        _run_embed(service, files, tmp_path=tmp_path)
        assert persistence.persist_file.call_count == 5
        assert persistence.persist_embeddings.call_count == 5

    def test_class_and_function_chunk_ids(self, tmp_path):
        service, persistence = _build_service()
        _run_embed(service, [
            _file("app.py", classes=["AppService"], functions=["run_app"]),
        ], tmp_path=tmp_path)
        calls = persistence.persist_embeddings.call_args_list
        all_dicts = []
        for c in calls:
            all_dicts.extend(c[0][1])
        chunk_ids = [d["chunk_id"] for d in all_dicts]
        assert any("class::AppService" in cid for cid in chunk_ids)
        assert any("function::run_app" in cid for cid in chunk_ids)

    def test_cached_embeddings_skip_vector_gen_but_persist(self, tmp_path):
        """When embeddings are reused from cache (hash match), metadata is still persisted."""
        service, persistence = _build_service()
        files = [_file("auth.py", content_hash="hash1", functions=["login"])]
        _run_embed(service, files, tmp_path=tmp_path)

        persistence2 = _make_persistence_mock()
        service2 = EmbeddingService(
            provider=FakeEmbeddingProvider(),
            logger=get_service_logger("test"),
            persistence_service=persistence2,
        )
        _run_embed(service2, files, tmp_path=tmp_path)
        persistence2.persist_embeddings.assert_called()


class TestBackwardCompatibility:

    def test_embed_repository_returns_result(self, tmp_path):
        service, _ = _build_service()
        result = _run_embed(service, [_file("a.py", functions=["fa"])], tmp_path=tmp_path)
        assert isinstance(result, EmbeddingRunResult)

    def test_json_store_written_with_persistence(self, tmp_path):
        service, _ = _build_service()
        _run_embed(service, [_file("a.py", functions=["fa"])], tmp_path=tmp_path)
        store_path = service.storage_path(tmp_path)
        assert store_path.is_file()

    def test_embed_incremental_also_persists(self, tmp_path):
        service, persistence = _build_service()
        index = _index([_file("a.py", functions=["fa"])])
        service.embed_incremental(index, root=tmp_path)
        persistence.persist_embeddings.assert_called()

    def test_status_works_after_embedding(self, tmp_path):
        service, _ = _build_service()
        _run_embed(service, [_file("a.py", functions=["fa"])], tmp_path=tmp_path)
        status = service.status(tmp_path)
        assert status.store_exists is True
