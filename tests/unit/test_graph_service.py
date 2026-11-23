"""Unit tests for RepositoryGraphService (deterministic knowledge graph)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from refactory.core.exceptions import IndexError_
from refactory.core.logger import get_service_logger
from refactory.graph.models import NodeKind, RelationshipType
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
from refactory.indexer.service import IndexerService
from refactory.parser.service import ParserService


def _logger() -> object:
    return get_service_logger("test.graph")


def _summary(**kwargs: object) -> RepositorySummary:
    base = dict(
        repository_root="/tmp/demo",
        repository_name="demo",
        total_indexed_files=0,
        ignored_file_count=0,
        total_functions=0,
        total_classes=0,
        total_imports=0,
        todo_count=0,
        timestamp=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return RepositorySummary(**base)  # type: ignore[arg-type]


def _make_index(files: list[IndexedFile]) -> RepositoryIndex:
    symbols: list[IndexedSymbol] = []
    refs: list[ImportReference] = []
    for f in files:
        symbols.extend(f.symbols)
        refs.extend(f.import_references)
    return RepositoryIndex(
        summary=_summary(
            total_indexed_files=len(files),
            total_functions=sum(1 for s in symbols if s.kind == SymbolKind.FUNCTION),
            total_classes=sum(1 for s in symbols if s.kind == SymbolKind.CLASS),
            total_imports=len(refs),
        ),
        statistics=RepositoryStatistics(),
        files=files,
        symbols=symbols,
        import_references=refs,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _auth_login_index() -> RepositoryIndex:
    auth = IndexedFile(
        relative_path="auth.py",
        language="python",
        content_hash="a" * 64,
        module_name="auth",
        classes=["AuthService"],
        functions=["validate_token"],
        nested_functions=["inner"],
        imports=[],
        symbols=[
            IndexedSymbol(
                name="auth",
                kind=SymbolKind.MODULE,
                file_path="auth.py",
                start_line=1,
                end_line=20,
            ),
            IndexedSymbol(
                name="validate_token",
                kind=SymbolKind.FUNCTION,
                file_path="auth.py",
                start_line=3,
                end_line=6,
            ),
            IndexedSymbol(
                name="AuthService",
                kind=SymbolKind.CLASS,
                file_path="auth.py",
                start_line=8,
                end_line=18,
            ),
            IndexedSymbol(
                name="login",
                kind=SymbolKind.METHOD,
                file_path="auth.py",
                start_line=10,
                end_line=16,
                parent="AuthService",
            ),
            IndexedSymbol(
                name="inner",
                kind=SymbolKind.NESTED_FUNCTION,
                file_path="auth.py",
                start_line=12,
                end_line=14,
                parent="login",
            ),
        ],
        import_references=[],
    )
    login = IndexedFile(
        relative_path="login.py",
        language="python",
        content_hash="b" * 64,
        module_name="login",
        classes=[],
        functions=["handle_login"],
        imports=["from auth import validate_token"],
        symbols=[
            IndexedSymbol(
                name="login",
                kind=SymbolKind.MODULE,
                file_path="login.py",
                start_line=1,
                end_line=10,
            ),
            IndexedSymbol(
                name="handle_login",
                kind=SymbolKind.FUNCTION,
                file_path="login.py",
                start_line=4,
                end_line=8,
            ),
        ],
        import_references=[
            ImportReference(
                source_file="login.py",
                source_module="login",
                target_module="auth",
                symbol="validate_token",
                kind="from_import",
                start_line=1,
            )
        ],
    )
    service = IndexedFile(
        relative_path="service.py",
        language="python",
        content_hash="c" * 64,
        module_name="service",
        classes=[],
        functions=["run"],
        imports=["import auth"],
        symbols=[
            IndexedSymbol(
                name="service",
                kind=SymbolKind.MODULE,
                file_path="service.py",
                start_line=1,
                end_line=8,
            ),
            IndexedSymbol(
                name="run",
                kind=SymbolKind.FUNCTION,
                file_path="service.py",
                start_line=3,
                end_line=6,
            ),
        ],
        import_references=[
            ImportReference(
                source_file="service.py",
                source_module="service",
                target_module="auth",
                symbol=None,
                kind="import",
                start_line=1,
            )
        ],
    )
    tests = IndexedFile(
        relative_path="tests/test_auth.py",
        language="python",
        content_hash="d" * 64,
        module_name="test_auth",
        classes=[],
        functions=["test_validate"],
        imports=["from auth import validate_token"],
        symbols=[
            IndexedSymbol(
                name="test_auth",
                kind=SymbolKind.MODULE,
                file_path="tests/test_auth.py",
                start_line=1,
                end_line=8,
            ),
            IndexedSymbol(
                name="test_validate",
                kind=SymbolKind.FUNCTION,
                file_path="tests/test_auth.py",
                start_line=3,
                end_line=6,
            ),
        ],
        import_references=[
            ImportReference(
                source_file="tests/test_auth.py",
                source_module="test_auth",
                target_module="auth",
                symbol="validate_token",
                kind="from_import",
                start_line=1,
            )
        ],
    )
    return _make_index([auth, login, service, tests])


def _service(index: RepositoryIndex | None = None) -> RepositoryGraphService:
    svc = RepositoryGraphService(logger=_logger())  # type: ignore[arg-type]
    if index is not None:
        svc.build_graph(index)
    return svc


def test_build_graph_creates_nodes_and_edges():
    svc = _service(_auth_login_index())
    graph = svc.graph()
    assert graph.statistics.files == 4
    assert graph.statistics.modules == 4
    assert graph.statistics.classes == 1
    assert graph.statistics.functions >= 1
    assert graph.statistics.methods == 1
    assert graph.statistics.nested_functions == 1
    assert graph.statistics.total_nodes > 0
    assert graph.statistics.total_edges > 0
    assert graph.statistics.import_edges >= 3


def test_graph_raises_before_build():
    svc = _service()
    with pytest.raises(IndexError_):
        svc.graph()


def test_symbol_lookup_validate_token():
    svc = _service(_auth_login_index())
    matches = svc.find_symbol("validate_token")
    assert len(matches) == 1
    assert matches[0].kind == NodeKind.FUNCTION
    assert matches[0].file_path == "auth.py"
    assert svc.where_defined("validate_token") == ["auth.py"]


def test_find_class_and_methods():
    svc = _service(_auth_login_index())
    classes = svc.find_class("AuthService")
    assert len(classes) == 1
    methods = svc.methods_of("AuthService")
    assert [m.name for m in methods] == ["login"]


def test_find_function_and_nested():
    svc = _service(_auth_login_index())
    fns = svc.find_function("login")
    assert any(f.kind == NodeKind.METHOD for f in fns)
    nested = svc.nested_functions("login")
    assert [n.name for n in nested] == ["inner"]
    assert nested[0].parent_id is not None


def test_find_module_and_file():
    svc = _service(_auth_login_index())
    module = svc.find_module("auth")
    assert module is not None
    assert module.name == "auth"
    file_node = svc.find_file("auth.py")
    assert file_node is not None
    assert file_node.language == "python"


def test_find_file_by_basename():
    svc = _service(_auth_login_index())
    # basename unique within fixture
    assert svc.find_file("test_auth.py") is not None


def test_functions_and_classes_in_module():
    svc = _service(_auth_login_index())
    fns = svc.functions_in_module("auth")
    assert "validate_token" in [f.name for f in fns]
    classes = svc.classes_in_module("auth")
    assert [c.name for c in classes] == ["AuthService"]


def test_import_graph_who_imports_module():
    svc = _service(_auth_login_index())
    importers = svc.who_imports("auth")
    assert set(importers) == {"login.py", "service.py", "tests/test_auth.py"}


def test_who_imports_file_and_reverse_dependencies():
    svc = _service(_auth_login_index())
    importers = svc.who_imports_file("auth.py")
    assert set(importers) == {"login.py", "service.py", "tests/test_auth.py"}
    assert svc.reverse_dependencies("auth.py") == importers


def test_dependencies_of_file():
    svc = _service(_auth_login_index())
    assert svc.dependencies_of("login.py") == ["auth.py"]
    assert svc.dependencies_of("auth.py") == []


def test_affected_files_transitive_reverse_deps():
    svc = _service(_auth_login_index())
    affected = svc.affected_files("auth.py")
    assert set(affected) == {"login.py", "service.py", "tests/test_auth.py"}


def test_affected_files_unknown_path():
    svc = _service(_auth_login_index())
    assert svc.affected_files("missing.py") == []


def test_reference_and_call_edges_for_named_imports():
    svc = _service(_auth_login_index())
    stats = svc.repository_statistics()
    assert stats.reference_edges >= 2
    assert stats.call_edges >= 2
    refs = svc.files_referencing_symbol("validate_token")
    assert "login.py" in refs
    assert "tests/test_auth.py" in refs


def test_definition_edge_types_present():
    svc = _service(_auth_login_index())
    rels = {e.relationship for e in svc.graph().edges}
    assert RelationshipType.FILE_CONTAINS_MODULE in rels
    assert RelationshipType.MODULE_CONTAINS_CLASS in rels
    assert RelationshipType.MODULE_CONTAINS_FUNCTION in rels
    assert RelationshipType.CLASS_CONTAINS_METHOD in rels
    assert RelationshipType.NESTED_FUNCTION in rels
    assert RelationshipType.PARENT_FUNCTION in rels
    assert RelationshipType.FILE_IMPORTS_FILE in rels
    assert RelationshipType.MODULE_IMPORTS_MODULE in rels
    assert RelationshipType.FUNCTION_DEFINED_IN_FILE in rels
    assert RelationshipType.SYMBOL_DEFINED_IN_FILE in rels


def test_symbol_table_populated():
    svc = _service(_auth_login_index())
    table = svc.graph().symbol_table
    assert "validate_token" in table
    assert "AuthService" in table
    assert "inner" in table


def test_top_imported_and_connected():
    svc = _service(_auth_login_index())
    top = svc.top_imported_modules()
    assert top[0][0] == "auth"
    assert top[0][1] >= 3
    connected = svc.most_connected_files()
    assert any(path == "auth.py" for path, _ in connected)


def test_average_stats_computed():
    stats = _service(_auth_login_index()).repository_statistics()
    assert stats.average_imports_per_file >= 0
    assert stats.average_symbols_per_file > 0


def test_empty_index():
    svc = _service(_make_index([]))
    graph = svc.graph()
    assert graph.statistics.total_nodes == 0
    assert graph.statistics.total_edges == 0
    assert svc.find_symbol("x") == []
    assert svc.affected_files("a.py") == []


def test_rebuild_replaces_graph():
    svc = _service(_auth_login_index())
    first_nodes = svc.graph().statistics.total_nodes
    svc.build_graph(_make_index([]))
    assert svc.graph().statistics.total_nodes == 0
    assert first_nodes > 0


def test_integration_with_real_indexer(tmp_path: Path):
    (tmp_path / "auth.py").write_text(
        "def validate_token():\n    return True\n\n"
        "class AuthService:\n    def login(self):\n"
        "        def nested():\n            return 1\n"
        "        return nested()\n",
        encoding="utf-8",
    )
    (tmp_path / "login.py").write_text(
        "from auth import validate_token\n\ndef handle():\n    return validate_token()\n",
        encoding="utf-8",
    )
    parser = ParserService(
        ignore_dirs=[".git", ".refactory"],
        logger=get_service_logger("test.parser"),
    )
    indexer = IndexerService(
        parser_service=parser,
        ignore_dirs=[".git", ".refactory"],
        logger=get_service_logger("test.indexer"),
    )
    index = indexer.build_index(tmp_path, repository_name="demo")
    svc = _service(index)
    assert "validate_token" in svc.graph().symbol_table
    assert "login.py" in svc.who_imports_file("auth.py")
    assert "login.py" in svc.affected_files("auth.py")
    nested = svc.nested_functions("login")
    assert any(n.name == "nested" for n in nested)


def test_defined_symbols_in_file():
    svc = _service(_auth_login_index())
    symbols = svc.defined_symbols_in_file("auth.py")
    names = {s.name for s in symbols}
    assert "validate_token" in names
    assert "AuthService" in names
    assert "login" in names
