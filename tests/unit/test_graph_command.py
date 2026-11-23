"""CLI graph commands must delegate to container graph/indexer services."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from typer.testing import CliRunner

from refactory.cli.app import app
from refactory.graph.models import (
    FileNode,
    GraphStatistics,
    NodeKind,
    RepositoryGraph,
    SymbolMatch,
)
from refactory.indexer.models import RepositoryIndex, RepositoryStatistics, RepositorySummary

runner = CliRunner()


def _index() -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="C:/tmp/demo",
            repository_name="demo",
            total_indexed_files=2,
            timestamp=datetime.now(timezone.utc),
        ),
        statistics=RepositoryStatistics(),
    )


def _graph() -> RepositoryGraph:
    return RepositoryGraph(
        repository_name="demo",
        repository_root="C:/tmp/demo",
        statistics=GraphStatistics(
            files=2,
            modules=2,
            classes=1,
            functions=3,
            total_nodes=10,
            total_edges=20,
            import_edges=4,
        ),
    )


def _patch_container(mocker, *, graph_service: MagicMock, index: RepositoryIndex | None = None):
    git = MagicMock()
    git.get_repository_metadata.return_value.name = "demo"
    git.get_repository_metadata.return_value.root_path = "C:/tmp/demo"

    indexer = MagicMock()
    indexer.load_index.return_value = index if index is not None else _index()

    container = MagicMock()
    container.git_service = git
    container.indexer_service = indexer
    container.graph_service = graph_service
    mocker.patch("refactory.cli.commands.graph.get_container", return_value=container)
    return container


def test_graph_summary_command(mocker):
    graph_service = MagicMock()
    built = _graph()
    graph_service.build_graph.return_value = built
    graph_service.top_imported_modules.return_value = [("auth", 3)]
    graph_service.top_referenced_symbols.return_value = [("validate_token", 2)]
    graph_service.most_connected_files.return_value = [("auth.py", 5)]
    _patch_container(mocker, graph_service=graph_service)

    result = runner.invoke(app, ["graph"])

    assert result.exit_code == 0, result.stdout
    graph_service.build_graph.assert_called_once()
    assert "Repository Graph" in result.stdout
    assert "Nodes: 10" in result.stdout
    assert "Edges: 20" in result.stdout
    assert "auth (3)" in result.stdout
    assert "validate_token (2)" in result.stdout


def test_graph_symbol_command(mocker):
    graph_service = MagicMock()
    graph_service.build_graph.return_value = _graph()
    graph_service.find_symbol.return_value = [
        SymbolMatch(
            name="validate_token",
            kind=NodeKind.FUNCTION,
            node_id="function:auth.py:validate_token",
            file_path="auth.py",
            module_name="auth",
        )
    ]
    graph_service.where_defined.return_value = ["auth.py"]
    graph_service.who_imports.return_value = ["login.py", "service.py"]
    graph_service.who_imports_file.return_value = ["login.py", "service.py"]
    graph_service.files_referencing_symbol.return_value = ["tests/test_auth.py"]
    _patch_container(mocker, graph_service=graph_service)

    result = runner.invoke(app, ["graph", "symbol", "validate_token"])

    assert result.exit_code == 0, result.stdout
    assert "validate_token()" in result.stdout
    assert "auth.py" in result.stdout
    assert "login.py" in result.stdout
    assert "tests/test_auth.py" in result.stdout


def test_graph_symbol_not_found(mocker):
    graph_service = MagicMock()
    graph_service.build_graph.return_value = _graph()
    graph_service.find_symbol.return_value = []
    _patch_container(mocker, graph_service=graph_service)

    result = runner.invoke(app, ["graph", "symbol", "missing"])

    assert result.exit_code == 1
    assert "Symbol not found" in result.stdout


def test_graph_file_command(mocker):
    graph_service = MagicMock()
    graph_service.build_graph.return_value = _graph()
    graph_service.find_file.return_value = FileNode(
        id="file:auth.py",
        kind=NodeKind.FILE,
        name="auth.py",
        file_path="auth.py",
        module_name="auth",
        language="python",
    )
    graph_service.defined_symbols_in_file.return_value = [
        SymbolMatch(
            name="validate_token",
            kind=NodeKind.FUNCTION,
            node_id="function:auth.py:validate_token",
            file_path="auth.py",
        )
    ]
    graph_service.dependencies_of.return_value = ["jwt.py"]
    graph_service.who_imports_file.return_value = ["login.py", "service.py"]
    _patch_container(mocker, graph_service=graph_service)

    result = runner.invoke(app, ["graph", "file", "auth.py"])

    assert result.exit_code == 0, result.stdout
    assert "File" in result.stdout
    assert "auth.py" in result.stdout
    assert "validate_token()" in result.stdout
    assert "jwt.py" in result.stdout
    assert "login.py" in result.stdout


def test_graph_builds_index_when_missing(mocker):
    graph_service = MagicMock()
    graph_service.build_graph.return_value = _graph()
    graph_service.top_imported_modules.return_value = []
    graph_service.top_referenced_symbols.return_value = []
    graph_service.most_connected_files.return_value = []

    git = MagicMock()
    git.get_repository_metadata.return_value.name = "demo"
    git.get_repository_metadata.return_value.root_path = "C:/tmp/demo"
    indexer = MagicMock()
    indexer.load_index.return_value = None
    indexer.build_index.return_value = _index()
    container = MagicMock()
    container.git_service = git
    container.indexer_service = indexer
    container.graph_service = graph_service
    mocker.patch("refactory.cli.commands.graph.get_container", return_value=container)

    result = runner.invoke(app, ["graph"])

    assert result.exit_code == 0, result.stdout
    indexer.build_index.assert_called_once()
    graph_service.build_graph.assert_called_once()
