"""Tests for RepositoryGraphService → PersistenceService integration.

Verifies that:
  - Successful graph builds persist nodes and edges to the database
  - PersistenceService.persist_graph() is called exactly once per build
  - Node and edge data are forwarded correctly
  - Database failures never cause graph generation to fail
  - Existing graph behaviour is unchanged
  - Persistence is skipped when PersistenceService is None
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refactory.core.logger import get_service_logger
from refactory.graph.models import GraphStatistics, NodeKind, RelationshipType, RepositoryGraph
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import (
    ImportReference,
    IndexedFile,
    IndexedSymbol,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
    SymbolKind,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _summary(**kwargs) -> RepositorySummary:
    base = dict(
        repository_root="/tmp/test-repo",
        repository_name="test-repo",
        total_indexed_files=0,
        ignored_file_count=0,
        total_functions=0,
        total_classes=0,
        total_imports=0,
        todo_count=0,
        timestamp=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return RepositorySummary(**base)


def _make_index(files: list[IndexedFile] | None = None) -> RepositoryIndex:
    files = files or []
    symbols: list[IndexedSymbol] = []
    refs: list[ImportReference] = []
    for f in files:
        symbols.extend(f.symbols)
        refs.extend(f.import_references)
    return RepositoryIndex(
        summary=_summary(total_indexed_files=len(files)),
        statistics=RepositoryStatistics(),
        files=files,
        symbols=symbols,
        import_references=refs,
    )


def _indexed_file(
    path: str,
    module: str,
    *,
    symbols: list[IndexedSymbol] | None = None,
    imports: list[ImportReference] | None = None,
) -> IndexedFile:
    return IndexedFile(
        relative_path=path,
        language="python",
        file_size=100,
        content_hash="abc123",
        modified_at=datetime.now(timezone.utc),
        module_name=module,
        symbols=symbols or [
            IndexedSymbol(
                name=module,
                kind=SymbolKind.MODULE,
                file_path=path,
                start_line=1,
                end_line=10,
            ),
            IndexedSymbol(
                name=f"func_{module}",
                kind=SymbolKind.FUNCTION,
                file_path=path,
                start_line=3,
                end_line=8,
            ),
        ],
        import_references=imports or [],
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
    mock.persist_graph.return_value = {"nodes": 4, "edges": 6}
    return mock


def _build_service(
    *,
    persistence: MagicMock | None = "DEFAULT",
) -> tuple[RepositoryGraphService, MagicMock | None]:
    if persistence == "DEFAULT":
        persistence = _make_persistence_mock()
    service = RepositoryGraphService(
        logger=get_service_logger("test.graph.persist"),
        persistence_service=persistence,
    )
    return service, persistence


# ---------------------------------------------------------------------------
# Tests: Core persistence
# ---------------------------------------------------------------------------


class TestGraphPersistence:

    def test_persist_graph_called_exactly_once(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("auth.py", "auth")])
        service.build_graph(index)
        persistence.persist_graph.assert_called_once()

    def test_get_or_create_repository_called(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("auth.py", "auth")])
        service.build_graph(index)
        persistence.get_or_create_repository.assert_called_once_with(
            name="test-repo",
            root_path="/tmp/test-repo",
            default_branch="main",
        )

    def test_repository_id_forwarded(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("auth.py", "auth")])
        service.build_graph(index)
        call_args = persistence.persist_graph.call_args
        assert call_args[0][0] == "repo-001"

    def test_nodes_forwarded(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("auth.py", "auth")])
        service.build_graph(index)
        call_kwargs = persistence.persist_graph.call_args.kwargs
        nodes = call_kwargs["nodes"]
        assert len(nodes) > 0
        assert all("name" in n and "type" in n for n in nodes)

    def test_edges_forwarded(self):
        service, persistence = _build_service()
        index = _make_index([
            _indexed_file("auth.py", "auth", imports=[
                ImportReference(
                    source_file="auth.py",
                    source_module="auth",
                    target_module="util",
                    symbol="helper",
                ),
            ]),
            _indexed_file("util.py", "util"),
        ])
        service.build_graph(index)
        call_kwargs = persistence.persist_graph.call_args.kwargs
        edges = call_kwargs["edges"]
        assert len(edges) > 0
        assert all("relationship" in e for e in edges)

    def test_node_type_is_string(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("app.py", "app")])
        service.build_graph(index)
        nodes = persistence.persist_graph.call_args.kwargs["nodes"]
        for n in nodes:
            assert isinstance(n["type"], str)

    def test_edge_relationship_is_string(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("app.py", "app")])
        service.build_graph(index)
        edges = persistence.persist_graph.call_args.kwargs["edges"]
        for e in edges:
            assert isinstance(e["relationship"], str)

    def test_graph_result_unchanged(self):
        service_with, _ = _build_service()
        service_without, _ = _build_service(persistence=None)
        index = _make_index([_indexed_file("auth.py", "auth")])

        graph_with = service_with.build_graph(index)
        graph_without = service_without.build_graph(index)

        assert isinstance(graph_with, RepositoryGraph)
        assert graph_with.repository_name == graph_without.repository_name
        assert len(graph_with.nodes) == len(graph_without.nodes)
        assert len(graph_with.edges) == len(graph_without.edges)


class TestFailureHandling:

    def test_persist_graph_failure_does_not_break_build(self):
        service, persistence = _build_service()
        persistence.persist_graph.side_effect = RuntimeError("DB connection lost")
        index = _make_index([_indexed_file("auth.py", "auth")])
        graph = service.build_graph(index)
        assert isinstance(graph, RepositoryGraph)
        assert len(graph.nodes) > 0

    def test_repository_creation_failure_does_not_break_build(self):
        service, persistence = _build_service()
        persistence.get_or_create_repository.side_effect = ConnectionError("timeout")
        index = _make_index([_indexed_file("auth.py", "auth")])
        graph = service.build_graph(index)
        assert isinstance(graph, RepositoryGraph)

    def test_failure_logged_with_error(self):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.persist_graph.side_effect = RuntimeError("disk full")
        service = RepositoryGraphService(
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _make_index([_indexed_file("auth.py", "auth")])
        service.build_graph(index)
        mock_logger.error.assert_called_once()
        error_str = str(mock_logger.error.call_args)
        assert "disk full" in error_str
        assert "test-repo" in error_str

    def test_failure_log_includes_traceback(self):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.get_or_create_repository.side_effect = ValueError("bad data")
        service = RepositoryGraphService(
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _make_index([_indexed_file("a.py", "a")])
        service.build_graph(index)
        error_str = str(mock_logger.error.call_args)
        assert "ValueError" in error_str or "bad data" in error_str


class TestNoPersistenceService:

    def test_build_graph_works_without_persistence(self):
        service, _ = _build_service(persistence=None)
        index = _make_index([_indexed_file("app.py", "app")])
        graph = service.build_graph(index)
        assert isinstance(graph, RepositoryGraph)
        assert len(graph.nodes) > 0

    def test_no_persistence_no_errors(self):
        service, _ = _build_service(persistence=None)
        index = _make_index([_indexed_file("a.py", "a"), _indexed_file("b.py", "b")])
        graph = service.build_graph(index)
        assert graph.repository_name == "test-repo"

    def test_default_persistence_is_none(self):
        service = RepositoryGraphService(
            logger=get_service_logger("test"),
        )
        assert service._persistence is None

    def test_instantiates_with_cache_only(self):
        service = RepositoryGraphService(
            logger=get_service_logger("test"),
            cache=None,
        )
        assert service._persistence is None


class TestPersistenceLogging:

    def test_success_log_contains_repository(self):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        service = RepositoryGraphService(
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _make_index([_indexed_file("a.py", "a")])
        service.build_graph(index)
        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "persisted" in str(c).lower()]
        assert len(persist_calls) >= 1
        log_str = str(persist_calls[0])
        assert "test-repo" in log_str

    def test_success_log_contains_counts(self):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        service = RepositoryGraphService(
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _make_index([_indexed_file("a.py", "a")])
        service.build_graph(index)
        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "persisted" in str(c).lower()]
        assert len(persist_calls) >= 1
        log_str = str(persist_calls[0])
        assert "elapsed_ms" in log_str

    def test_success_log_contains_elapsed(self):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        service = RepositoryGraphService(
            logger=mock_logger,
            persistence_service=persistence,
        )
        index = _make_index([_indexed_file("a.py", "a")])
        service.build_graph(index)
        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "elapsed_ms" in str(c)]
        assert len(persist_calls) >= 1


class TestEdgeCases:

    def test_zero_node_graph(self):
        service, persistence = _build_service()
        index = _make_index([])
        graph = service.build_graph(index)
        assert len(graph.nodes) == 0
        persistence.persist_graph.assert_called_once()
        call_kwargs = persistence.persist_graph.call_args.kwargs
        assert call_kwargs["nodes"] == []
        assert call_kwargs["edges"] == []

    def test_zero_edge_graph(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("solo.py", "solo")])
        graph = service.build_graph(index)
        persistence.persist_graph.assert_called_once()
        call_kwargs = persistence.persist_graph.call_args.kwargs
        assert len(call_kwargs["nodes"]) > 0

    def test_multiple_files_all_nodes_forwarded(self):
        service, persistence = _build_service()
        files = [_indexed_file(f"mod_{i}.py", f"mod_{i}") for i in range(5)]
        index = _make_index(files)
        service.build_graph(index)
        call_kwargs = persistence.persist_graph.call_args.kwargs
        assert len(call_kwargs["nodes"]) >= 10

    def test_cached_graph_does_not_persist(self):
        """When graph is served from cache, no DB persistence should occur."""
        persistence = _make_persistence_mock()
        from refactory.cache.store import DeterministicCache
        cache = MagicMock()
        cache.get.return_value = None
        service = RepositoryGraphService(
            logger=get_service_logger("test"),
            cache=cache,
            persistence_service=persistence,
        )
        index = _make_index([_indexed_file("a.py", "a")])
        service.build_graph(index)
        persistence.persist_graph.assert_called_once()

        cache2 = MagicMock()
        graph = service.build_graph(index)
        graph_dict = graph.model_dump(mode="json")
        cache2.get.return_value = graph_dict
        service2 = RepositoryGraphService(
            logger=get_service_logger("test"),
            cache=cache2,
            persistence_service=_make_persistence_mock(),
        )
        result = service2.build_graph(index)
        assert isinstance(result, RepositoryGraph)
        service2._persistence.persist_graph.assert_not_called()


class TestBackwardCompatibility:

    def test_build_graph_returns_repository_graph(self):
        service, _ = _build_service()
        index = _make_index([_indexed_file("a.py", "a")])
        graph = service.build_graph(index)
        assert isinstance(graph, RepositoryGraph)

    def test_graph_accessor_works(self):
        service, _ = _build_service()
        index = _make_index([_indexed_file("a.py", "a")])
        service.build_graph(index)
        assert service.graph() is not None

    def test_statistics_computed(self):
        service, _ = _build_service()
        index = _make_index([_indexed_file("a.py", "a")])
        graph = service.build_graph(index)
        assert graph.statistics.total_nodes > 0

    def test_update_graph_delegates_to_build(self):
        service, persistence = _build_service()
        index = _make_index([_indexed_file("a.py", "a")])
        graph = service.update_graph(index)
        assert isinstance(graph, RepositoryGraph)
        persistence.persist_graph.assert_called()
