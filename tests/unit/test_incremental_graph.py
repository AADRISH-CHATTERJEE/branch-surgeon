"""Tests for incremental graph updates (update_incremental)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from refactory.graph.service import IncrementalGraphResult, RepositoryGraphService
from refactory.indexer.models import (
    ImportReference,
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)


def _make_index(files: list[dict]) -> RepositoryIndex:
    indexed_files = []
    for f in files:
        indexed_files.append(IndexedFile(
            relative_path=f["path"],
            module_name=f.get("module", f["path"].replace("/", ".").replace(".py", "")),
            language="python",
            content_hash=f.get("hash", "h_" + f["path"]),
            symbols=[
                IndexedSymbol(
                    name="func",
                    kind=SymbolKind.FUNCTION,
                    file_path=f["path"],
                    start_line=1,
                    end_line=5,
                )
            ],
            classes=[],
            functions=["func"],
            nested_functions=[],
            import_references=[],
        ))
    return RepositoryIndex(
        files=indexed_files,
        file_hashes={f["path"]: f.get("hash", "h_" + f["path"]) for f in files},
        summary=RepositorySummary(
            repository_root="/tmp/test",
            repository_name="test",
            total_indexed_files=len(files),
            timestamp=datetime.now(timezone.utc),
        ),
        statistics=RepositoryStatistics(files_parsed=len(files)),
    )


@pytest.fixture
def graph_service() -> RepositoryGraphService:
    from loguru import logger
    return RepositoryGraphService(logger=logger)


class TestIncrementalGraphUpdates:
    def test_first_build_full_rebuild(self, graph_service: RepositoryGraphService):
        idx = _make_index([{"path": "a.py", "hash": "h1"}])
        result = graph_service.update_incremental(idx)
        assert isinstance(result, IncrementalGraphResult)
        assert result.full_rebuild is True
        assert result.added_files == 1

    def test_no_changes_no_rebuild(self, graph_service: RepositoryGraphService):
        idx = _make_index([{"path": "a.py", "hash": "h1"}])
        graph_service.build_graph(idx)
        result = graph_service.update_incremental(idx)
        assert result.preserved_files == 1
        assert result.changed_files == 0
        assert result.added_files == 0
        assert result.deleted_files == 0

    def test_file_added(self, graph_service: RepositoryGraphService):
        idx1 = _make_index([{"path": "a.py", "hash": "h1"}])
        graph_service.build_graph(idx1)
        idx2 = _make_index([
            {"path": "a.py", "hash": "h1"},
            {"path": "b.py", "hash": "h2"},
        ])
        result = graph_service.update_incremental(idx2)
        assert result.added_files == 1
        assert result.preserved_files == 1

    def test_file_modified(self, graph_service: RepositoryGraphService):
        idx1 = _make_index([{"path": "a.py", "hash": "h1"}])
        graph_service.build_graph(idx1)
        idx2 = _make_index([{"path": "a.py", "hash": "h2"}])
        result = graph_service.update_incremental(idx2)
        assert result.changed_files == 1

    def test_file_deleted(self, graph_service: RepositoryGraphService):
        idx1 = _make_index([
            {"path": "a.py", "hash": "h1"},
            {"path": "b.py", "hash": "h2"},
        ])
        graph_service.build_graph(idx1)
        idx2 = _make_index([{"path": "a.py", "hash": "h1"}])
        result = graph_service.update_incremental(idx2)
        assert result.deleted_files == 1
        assert result.preserved_files == 1

    def test_mixed_changes(self, graph_service: RepositoryGraphService):
        idx1 = _make_index([
            {"path": "a.py", "hash": "h1"},
            {"path": "b.py", "hash": "h2"},
            {"path": "c.py", "hash": "h3"},
        ])
        graph_service.build_graph(idx1)
        idx2 = _make_index([
            {"path": "a.py", "hash": "h1"},
            {"path": "b.py", "hash": "h2_mod"},
            {"path": "d.py", "hash": "h4"},
        ])
        result = graph_service.update_incremental(idx2)
        assert result.preserved_files == 1
        assert result.changed_files == 1
        assert result.added_files == 1
        assert result.deleted_files == 1

    def test_large_change_full_rebuild(self, graph_service: RepositoryGraphService):
        files1 = [{"path": f"f{i}.py", "hash": f"h{i}"} for i in range(10)]
        idx1 = _make_index(files1)
        graph_service.build_graph(idx1)

        files2 = [{"path": f"f{i}.py", "hash": f"new_h{i}"} for i in range(10)]
        idx2 = _make_index(files2)
        result = graph_service.update_incremental(idx2)
        assert result.full_rebuild is True

    def test_graph_is_valid_after_update(self, graph_service: RepositoryGraphService):
        idx = _make_index([
            {"path": "a.py", "hash": "h1"},
            {"path": "b.py", "hash": "h2"},
        ])
        result = graph_service.update_incremental(idx)
        assert result.graph is not None
        assert result.graph.statistics.total_nodes > 0

    def test_update_graph_method(self, graph_service: RepositoryGraphService):
        idx1 = _make_index([{"path": "a.py", "hash": "h1"}])
        graph_service.build_graph(idx1)
        idx2 = _make_index([{"path": "a.py", "hash": "h1"}])
        graph = graph_service.update_graph(idx2)
        assert graph is not None

    def test_update_graph_no_prior(self, graph_service: RepositoryGraphService):
        idx = _make_index([{"path": "a.py", "hash": "h1"}])
        graph = graph_service.update_graph(idx)
        assert graph is not None

    def test_empty_index(self, graph_service: RepositoryGraphService):
        idx = _make_index([])
        result = graph_service.update_incremental(idx)
        assert result.graph is not None

    def test_single_file_change(self, graph_service: RepositoryGraphService):
        idx1 = _make_index([
            {"path": "a.py", "hash": "h1"},
            {"path": "b.py", "hash": "h2"},
            {"path": "c.py", "hash": "h3"},
            {"path": "d.py", "hash": "h4"},
            {"path": "e.py", "hash": "h5"},
        ])
        graph_service.build_graph(idx1)
        idx2 = _make_index([
            {"path": "a.py", "hash": "h1"},
            {"path": "b.py", "hash": "h2"},
            {"path": "c.py", "hash": "h3_mod"},
            {"path": "d.py", "hash": "h4"},
            {"path": "e.py", "hash": "h5"},
        ])
        result = graph_service.update_incremental(idx2)
        assert result.changed_files == 1
        assert result.preserved_files == 4
        assert result.full_rebuild is False

    def test_all_files_deleted(self, graph_service: RepositoryGraphService):
        idx1 = _make_index([{"path": "a.py", "hash": "h1"}])
        graph_service.build_graph(idx1)
        idx2 = _make_index([])
        result = graph_service.update_incremental(idx2)
        assert result.deleted_files == 1

    def test_incremental_result_dataclass(self):
        from refactory.graph.models import RepositoryGraph
        g = RepositoryGraph(repository_name="test", repository_root="/tmp")
        r = IncrementalGraphResult(
            graph=g,
            added_files=1,
            changed_files=2,
            deleted_files=3,
            preserved_files=4,
            full_rebuild=False,
        )
        assert r.added_files == 1
        assert r.changed_files == 2
        assert r.deleted_files == 3
        assert r.preserved_files == 4
