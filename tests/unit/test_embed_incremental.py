"""Tests for incremental embedding index."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from refactory.core.logger import get_service_logger
from refactory.embedding.models import EmbeddingStore, FileEmbeddingRecord
from refactory.embedding.service import EMBEDDINGS_FILENAME, REFACTORY_DIR, EmbeddingService
from refactory.indexer.models import (
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)

_NOW = datetime.now(timezone.utc)


def _mock_provider(model: str = "test-model") -> MagicMock:
    provider = MagicMock()
    provider.model_name = model
    provider.embed_batch.side_effect = lambda texts: [[0.1, 0.2, 0.3]] * len(texts)
    provider.embed_text.return_value = [0.1, 0.2, 0.3]
    return provider


def _make_index(files: list[IndexedFile], name: str = "test") -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_name=name,
            repository_root="/tmp/test",
            total_indexed_files=len(files),
            timestamp=_NOW,
        ),
        statistics=RepositoryStatistics(),
        files=files,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _make_file(
    path: str,
    content_hash: str = "hash1",
    functions: list[str] | None = None,
) -> IndexedFile:
    fns = functions or ["main"]
    symbols = [
        IndexedSymbol(
            name=f, kind=SymbolKind.FUNCTION, file_path=path,
            start_line=1, end_line=2,
        )
        for f in fns
    ]
    return IndexedFile(
        relative_path=path,
        language="python",
        file_size=100,
        content_hash=content_hash,
        module_name=path.removesuffix(".py"),
        functions=fns,
        symbols=symbols,
    )


class TestIncrementalEmbedding:
    def test_first_run_embeds_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = _mock_provider()
            svc = EmbeddingService(provider, get_service_logger("test"))
            files = [_make_file("a.py", "h1", ["func_a"])]
            result = svc.embed_repository(_make_index(files), root=root)
            assert result.embedded == 1
            assert result.skipped == 0

    def test_incremental_skips_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = _mock_provider()
            svc = EmbeddingService(provider, get_service_logger("test"))
            files = [_make_file("a.py", "h1", ["func_a"])]
            svc.embed_repository(_make_index(files), root=root)
            provider.embed_batch.reset_mock()

            result = svc.embed_repository(_make_index(files), root=root)
            assert result.skipped == 1
            assert result.embedded == 0
            provider.embed_batch.assert_not_called()

    def test_incremental_embeds_modified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = _mock_provider()
            svc = EmbeddingService(provider, get_service_logger("test"))
            files_v1 = [_make_file("a.py", "h1", ["func_a"])]
            svc.embed_repository(_make_index(files_v1), root=root)

            files_v2 = [_make_file("a.py", "h2", ["func_a"])]
            provider.embed_batch.reset_mock()
            provider.embed_batch.side_effect = lambda texts: [[0.4, 0.5, 0.6]] * len(texts)
            result = svc.embed_repository(_make_index(files_v2), root=root)
            assert result.embedded == 1

    def test_deleted_files_not_in_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = _mock_provider()
            svc = EmbeddingService(provider, get_service_logger("test"))

            files_v1 = [
                _make_file("a.py", "h1", ["func_a"]),
                _make_file("b.py", "h2", ["func_b"]),
            ]
            provider.embed_batch.return_value = [[0.1] * 3, [0.2] * 3]
            svc.embed_repository(_make_index(files_v1), root=root)

            files_v2 = [_make_file("a.py", "h1", ["func_a"])]
            result = svc.embed_repository(_make_index(files_v2), root=root)
            store = svc.load_store(root)
            assert store is not None
            assert "b.py" not in store.files

    def test_force_reembeds_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = _mock_provider()
            svc = EmbeddingService(provider, get_service_logger("test"))
            files = [_make_file("a.py", "h1", ["func_a"])]
            svc.embed_repository(_make_index(files), root=root)

            provider.embed_batch.reset_mock()
            provider.embed_batch.side_effect = lambda texts: [[0.9, 0.8, 0.7]] * len(texts)
            result = svc.embed_repository(_make_index(files), root=root, force=True)
            assert result.skipped == 0
            assert result.embedded == 1

    def test_model_change_rebuilds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider1 = _mock_provider("model-v1")
            svc1 = EmbeddingService(provider1, get_service_logger("test"))
            files = [_make_file("a.py", "h1", ["func_a"])]
            svc1.embed_repository(_make_index(files), root=root)

            provider2 = _mock_provider("model-v2")
            svc2 = EmbeddingService(provider2, get_service_logger("test"))
            result = svc2.embed_repository(_make_index(files), root=root)
            assert result.embedded == 1

    def test_new_file_embedded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = _mock_provider()
            svc = EmbeddingService(provider, get_service_logger("test"))
            files_v1 = [_make_file("a.py", "h1", ["func_a"])]
            svc.embed_repository(_make_index(files_v1), root=root)

            files_v2 = [
                _make_file("a.py", "h1", ["func_a"]),
                _make_file("b.py", "h2", ["func_b"]),
            ]
            provider.embed_batch.reset_mock()
            provider.embed_batch.side_effect = lambda texts: [[0.3, 0.3, 0.3]] * len(texts)
            result = svc.embed_repository(_make_index(files_v2), root=root)
            assert result.embedded == 1
            assert result.skipped == 1
