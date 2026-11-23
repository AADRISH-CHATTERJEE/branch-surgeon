"""Tests for incremental repository graph updates."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from refactory.cache.store import NullCache
from refactory.core.logger import get_service_logger
from refactory.graph.models import (
    FileNode,
    GraphStatistics,
    NodeKind,
    RepositoryGraph,
)
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import (
    IndexedFile,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
)

_NOW = datetime.now(timezone.utc)


def _make_service() -> RepositoryGraphService:
    return RepositoryGraphService(
        logger=get_service_logger("test.graph"),
        cache=NullCache(),
    )


def _make_index(
    files: list[IndexedFile],
    name: str = "test-repo",
    root: str = "/tmp/repo",
) -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_name=name,
            repository_root=root,
            total_indexed_files=len(files),
            timestamp=_NOW,
        ),
        statistics=RepositoryStatistics(),
        files=files,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _make_file(
    path: str,
    content_hash: str = "abc123",
    language: str = "python",
    module_name: str | None = None,
) -> IndexedFile:
    return IndexedFile(
        relative_path=path,
        language=language,
        file_size=100,
        content_hash=content_hash,
        module_name=module_name or path.replace("/", ".").removesuffix(".py"),
    )


class TestIncrementalGraphUpdate:
    def test_update_with_no_prior_graph_does_full_build(self):
        svc = _make_service()
        files = [_make_file("a.py", "hash1"), _make_file("b.py", "hash2")]
        index = _make_index(files)
        graph = svc.update_graph(index)
        assert graph is not None
        assert graph.statistics.total_nodes > 0

    def test_update_with_no_changes_returns_same_graph(self):
        svc = _make_service()
        files = [_make_file("a.py", "hash1")]
        index = _make_index(files)
        g1 = svc.build_graph(index)
        g2 = svc.update_graph(index)
        assert g2 is g1

    def test_update_detects_added_files(self):
        svc = _make_service()
        files1 = [_make_file("a.py", "hash1")]
        svc.build_graph(_make_index(files1))

        files2 = [_make_file("a.py", "hash1"), _make_file("b.py", "hash2")]
        index2 = _make_index(files2)
        g2 = svc.update_graph(index2)
        assert g2 is not None
        assert g2.statistics.total_nodes > 0

    def test_update_detects_deleted_files(self):
        svc = _make_service()
        files1 = [_make_file("a.py", "h1"), _make_file("b.py", "h2")]
        svc.build_graph(_make_index(files1))

        files2 = [_make_file("a.py", "h1")]
        g2 = svc.update_graph(_make_index(files2))
        assert g2 is not None

    def test_update_detects_modified_files(self):
        svc = _make_service()
        files1 = [_make_file("a.py", "hash_v1")]
        svc.build_graph(_make_index(files1))

        files2 = [_make_file("a.py", "hash_v2")]
        g2 = svc.update_graph(_make_index(files2))
        assert g2 is not None

    def test_full_rebuild_when_majority_changed(self):
        svc = _make_service()
        files1 = [_make_file(f"f{i}.py", f"h{i}") for i in range(4)]
        svc.build_graph(_make_index(files1))

        files2 = [_make_file(f"f{i}.py", f"new_h{i}") for i in range(4)]
        g2 = svc.update_graph(_make_index(files2))
        assert g2 is not None

    def test_graph_property_after_update(self):
        svc = _make_service()
        files = [_make_file("mod.py", "h1")]
        svc.update_graph(_make_index(files))
        assert svc.graph() is not None
