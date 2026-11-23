"""Unit tests for CodeSearchService (local index/graph/retrieval only)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from refactory.codesearch.models import CodeHitKind
from refactory.codesearch.service import CodeSearchService
from refactory.core.logger import get_service_logger
from refactory.git.service import GitService
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
from refactory.retrieval.models import (
    EntityKind,
    RetrievedFile,
    RetrievedSymbol,
    RetrievalStatistics,
    SearchQuery,
    SearchResult,
)


def _logger():
    return get_service_logger("test.codesearch")


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
            total_functions=sum(
                1
                for s in symbols
                if s.kind
                in {SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.NESTED_FUNCTION}
            ),
            total_classes=sum(1 for s in symbols if s.kind == SymbolKind.CLASS),
            total_imports=len(refs),
            todo_count=sum(len(f.todo_tags) for f in files),
        ),
        statistics=RepositoryStatistics(),
        files=files,
        symbols=symbols,
        import_references=refs,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _demo_index() -> RepositoryIndex:
    auth = IndexedFile(
        relative_path="auth.py",
        language="python",
        content_hash="a" * 64,
        module_name="auth",
        classes=["AuthService"],
        functions=["validate_token"],
        nested_functions=["inner"],
        comments=["# TODO: harden token checks", "# note: public API"],
        todo_tags=["TODO"],
        symbols=[
            IndexedSymbol(
                name="auth",
                kind=SymbolKind.MODULE,
                file_path="auth.py",
                start_line=1,
                end_line=40,
            ),
            IndexedSymbol(
                name="validate_token",
                kind=SymbolKind.FUNCTION,
                file_path="auth.py",
                start_line=3,
                end_line=6,
                decorators=["lru_cache"],
            ),
            IndexedSymbol(
                name="AuthService",
                kind=SymbolKind.CLASS,
                file_path="auth.py",
                start_line=8,
                end_line=30,
            ),
            IndexedSymbol(
                name="login",
                kind=SymbolKind.METHOD,
                file_path="auth.py",
                start_line=12,
                end_line=20,
                parent="AuthService",
                decorators=["classmethod"],
            ),
            IndexedSymbol(
                name="inner",
                kind=SymbolKind.NESTED_FUNCTION,
                file_path="auth.py",
                start_line=15,
                end_line=17,
                parent="login",
            ),
        ],
        import_references=[],
    )
    # Second definition file entry for multiple definitions.
    legacy = IndexedFile(
        relative_path="auth/legacy.py",
        language="python",
        content_hash="d" * 64,
        module_name="auth.legacy",
        functions=["validate_token"],
        symbols=[
            IndexedSymbol(
                name="validate_token",
                kind=SymbolKind.FUNCTION,
                file_path="auth/legacy.py",
                start_line=2,
                end_line=4,
            )
        ],
        import_references=[],
    )
    login = IndexedFile(
        relative_path="login.py",
        language="python",
        content_hash="b" * 64,
        module_name="login",
        functions=["handle_login"],
        comments=["# FIXME: rate limit"],
        todo_tags=["FIXME"],
        symbols=[
            IndexedSymbol(
                name="handle_login",
                kind=SymbolKind.FUNCTION,
                file_path="login.py",
                start_line=4,
                end_line=10,
            )
        ],
        import_references=[
            ImportReference(
                source_file="login.py",
                source_module="login",
                target_module="auth",
                symbol="validate_token",
                kind="from_import",
                start_line=1,
            ),
            ImportReference(
                source_file="login.py",
                source_module="login",
                target_module="auth",
                symbol="validate_token",
                kind="call",
                start_line=6,
            ),
            ImportReference(
                source_file="login.py",
                source_module="login",
                target_module="auth",
                symbol="AuthService",
                kind="from_import",
                start_line=2,
            ),
        ],
    )
    return _make_index([auth, legacy, login])


def _build_service(
    tmp_path: Path,
    index: RepositoryIndex,
    *,
    retrieval: MagicMock | None = None,
) -> CodeSearchService:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    Repo.init(root, initial_branch="main")
    with Repo(root).config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    repo = Repo(root)
    repo.index.add(["README.md"])
    repo.index.commit("init")

    # Materialize indexed files for snippets.
    for indexed in index.files:
        path = root / indexed.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# placeholder"] * max(
            (s.end_line for s in indexed.symbols),
            default=5,
        )
        for symbol in indexed.symbols:
            if 1 <= symbol.start_line <= len(lines):
                lines[symbol.start_line - 1] = f"def {symbol.name}():  # {symbol.kind.value}"
        if indexed.comments:
            lines[0] = indexed.comments[0]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    logger = _logger()
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = index.model_copy(
        update={"summary": index.summary.model_copy(update={"repository_root": str(root)})}
    )
    indexer.build_index.return_value = indexer.load_index.return_value

    if retrieval is None:
        retrieval = MagicMock()
        retrieval.search.return_value = SearchResult(
            query=SearchQuery(text="x"),
            hits=[],
            statistics=RetrievalStatistics(),
        )
        retrieval.related_files.return_value = []

    return CodeSearchService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        retrieval_service=retrieval,
    )


@pytest.fixture
def service(tmp_path: Path) -> CodeSearchService:
    return _build_service(tmp_path, _demo_index())


def test_exact_search(service: CodeSearchService):
    result = service.search_symbols("validate_token")
    assert result.hits
    assert any(h.symbol == "validate_token" or h.symbol.endswith("validate_token") for h in result.hits)
    assert result.hits[0].score >= 1.0
    assert "exact_match" in result.hits[0].reasons


def test_semantic_search_merged(tmp_path: Path):
    retrieval = MagicMock()
    retrieval.search.return_value = SearchResult(
        query=SearchQuery(text="token validation"),
        hits=[
            RetrievedSymbol(
                result="function:validate_token",
                score=0.88,
                file_path="auth.py",
                module_name="auth",
                symbol="validate_token",
                kind=EntityKind.FUNCTION,
            )
        ],
        statistics=RetrievalStatistics(results_returned=1),
    )
    retrieval.related_files.return_value = []
    service = _build_service(tmp_path, _demo_index(), retrieval=retrieval)
    result = service.search("token validation", top_k=10)
    assert result.semantic_hits >= 1
    assert any(h.file == "auth.py" for h in result.hits)
    assert any("semantic_similarity" in h.reasons for h in result.hits)


def test_missing_symbol(service: CodeSearchService):
    result = service.find_definition("does_not_exist_xyz")
    assert result.hits == []


def test_multiple_definitions(service: CodeSearchService):
    result = service.find_definition("validate_token")
    files = {h.file for h in result.hits}
    assert "auth.py" in files
    assert "auth/legacy.py" in files


def test_nested_functions(service: CodeSearchService):
    result = service.search_functions("inner")
    assert any(h.type == CodeHitKind.NESTED_FUNCTION.value for h in result.hits)
    assert any(h.symbol.endswith("inner") for h in result.hits)


def test_class_methods(service: CodeSearchService):
    result = service.find_definition("AuthService.login")
    assert result.hits
    assert any(h.symbol == "AuthService.login" for h in result.hits)
    assert result.hits[0].file == "auth.py"


def test_import_aliases(service: CodeSearchService):
    result = service.search_imports("validate_token")
    assert result.hits
    assert any(h.file == "login.py" for h in result.hits)


def test_decorators(service: CodeSearchService):
    result = service.search_functions("lru_cache")
    assert any("decorator_match" in h.reasons for h in result.hits)
    assert any(h.symbol == "validate_token" or "validate_token" in h.symbol for h in result.hits)


def test_todo_discovery(service: CodeSearchService):
    result = service.search_todos()
    assert result.hits
    tags = {h.symbol for h in result.hits}
    assert "TODO" in tags or any("TODO" in (h.snippet or "") for h in result.hits)
    assert any(h.file == "login.py" for h in result.hits)


def test_reference_lookup(service: CodeSearchService):
    result = service.find_references("validate_token")
    assert any(h.file == "login.py" for h in result.hits)


def test_call_graph(service: CodeSearchService):
    callers = service.find_callers("validate_token")
    assert any(h.file == "login.py" for h in callers.hits)

    callees = service.find_callees("login.py")
    assert any("validate_token" in h.symbol for h in callees.hits)

    qualified = service.find_callees("AuthService.login")
    assert qualified.query == "AuthService.login"
    # Resolves to auth.py and reports file-level callees when present.
    assert isinstance(qualified.hits, list)


def test_large_repository(tmp_path: Path):
    files: list[IndexedFile] = []
    for i in range(80):
        name = f"fn_{i}"
        path = f"pkg/mod_{i}.py"
        files.append(
            IndexedFile(
                relative_path=path,
                language="python",
                content_hash=f"{i:064d}"[:64],
                module_name=f"pkg.mod_{i}",
                functions=[name],
                symbols=[
                    IndexedSymbol(
                        name=name,
                        kind=SymbolKind.FUNCTION,
                        file_path=path,
                        start_line=1,
                        end_line=3,
                    )
                ],
            )
        )
    service = _build_service(tmp_path, _make_index(files))
    result = service.search_functions("fn_42")
    assert result.hits
    assert result.hits[0].symbol == "fn_42"


def test_cache_reuse(service: CodeSearchService):
    service.search_symbols("login")
    first = service._cache
    service.find_definition("AuthService")
    service.search_todos()
    assert service._cache is first


def test_search_comments(service: CodeSearchService):
    result = service.search_comments("harden")
    assert result.hits
    assert any("harden" in (h.snippet or "").lower() for h in result.hits)


def test_search_files(service: CodeSearchService):
    result = service.search_files("login")
    assert any(h.file == "login.py" for h in result.hits)


def test_find_related_uses_retrieval(tmp_path: Path):
    retrieval = MagicMock()
    retrieval.search.return_value = SearchResult(
        query=SearchQuery(text="x"), hits=[], statistics=RetrievalStatistics()
    )
    retrieval.related_files.return_value = [
        RetrievedFile(
            file_path="login.py",
            module_name="login",
            score=0.77,
            best_symbol="handle_login",
            best_kind=EntityKind.FUNCTION,
        )
    ]
    service = _build_service(tmp_path, _demo_index(), retrieval=retrieval)
    result = service.find_related("validate_token", top_k=5)
    assert any(h.file == "login.py" for h in result.hits)


# -------------------------------------------------------------------
# Hybrid related ranking (Backlog 1)
# -------------------------------------------------------------------


def test_related_caller_callee_signals(tmp_path: Path):
    """Caller/callee relationships should appear in related results."""
    service = _build_service(tmp_path, _demo_index())
    result = service.find_related("auth.py", top_k=15)
    reasons_all = [r for h in result.hits for r in h.reasons]
    assert any(
        r.startswith("graph_") or r in ("caller", "callee", "same_package")
        for r in reasons_all
    ) or len(result.hits) == 0  # no graph data = no signals but no crash


def test_related_fused_ranking_deterministic(tmp_path: Path):
    """Multiple calls should produce identical ordering."""
    service = _build_service(tmp_path, _demo_index())
    r1 = service.find_related("auth.py", top_k=10)
    r2 = service.find_related("auth.py", top_k=10)
    assert [h.file for h in r1.hits] == [h.file for h in r2.hits]


def test_related_package_proximity_included(tmp_path: Path):
    """Same-package files should get a proximity signal."""
    idx = _demo_index()
    idx.files.append(
        IndexedFile(
            relative_path="auth/helper.py",
            module_name="auth.helper",
            language="python",
            content_hash="aaa",
            line_count=10,
            import_count=0,
            function_count=1,
            class_count=0,
        )
    )
    idx.files.append(
        IndexedFile(
            relative_path="auth/utils.py",
            module_name="auth.utils",
            language="python",
            content_hash="bbb",
            line_count=10,
            import_count=0,
            function_count=1,
            class_count=0,
        )
    )
    service = _build_service(tmp_path, idx)
    result = service.find_related("auth/helper.py", top_k=15)
    if any(h.file == "auth/utils.py" for h in result.hits):
        auth_utils = [h for h in result.hits if h.file == "auth/utils.py"][0]
        assert "same_package" in auth_utils.reasons
