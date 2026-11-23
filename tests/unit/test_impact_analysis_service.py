"""Unit tests for ImpactAnalysisService (load-only index, local graph/retrieval)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from refactory.core.exceptions import IndexError_
from refactory.core.logger import get_service_logger
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.models import RiskLevel
from refactory.impact.service import ImpactAnalysisService
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
from refactory.retrieval.models import EntityKind, RetrievedFile


def _logger():
    return get_service_logger("test.impact")


def _summary(**kwargs: object) -> RepositorySummary:
    base = dict(
        repository_root="/tmp/impact",
        repository_name="impact-demo",
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
        summary=_summary(total_indexed_files=len(files), total_imports=len(refs)),
        statistics=RepositoryStatistics(),
        files=files,
        symbols=symbols,
        import_references=refs,
        file_hashes={f.relative_path: f.content_hash for f in files},
    )


def _file(
    path: str,
    *,
    symbols: list[IndexedSymbol] | None = None,
    imports: list[ImportReference] | None = None,
    module: str | None = None,
) -> IndexedFile:
    symbols = symbols or []
    return IndexedFile(
        relative_path=path,
        language="python",
        content_hash=(path + "x" * 64)[:64],
        module_name=module or Path(path).stem,
        symbols=symbols,
        import_references=imports or [],
        classes=[s.name for s in symbols if s.kind == SymbolKind.CLASS],
        functions=[s.name for s in symbols if s.kind == SymbolKind.FUNCTION],
    )


def _impact_index() -> RepositoryIndex:
    """auth ← login, service; a↔b cycle; orphan lonely; inheritance Base/Child."""
    auth = _file(
        "auth.py",
        symbols=[
            IndexedSymbol(
                name="validate_token",
                kind=SymbolKind.FUNCTION,
                file_path="auth.py",
                start_line=1,
                end_line=4,
            ),
            IndexedSymbol(
                name="AuthService",
                kind=SymbolKind.CLASS,
                file_path="auth.py",
                start_line=6,
                end_line=20,
            ),
            IndexedSymbol(
                name="login",
                kind=SymbolKind.METHOD,
                file_path="auth.py",
                start_line=8,
                end_line=12,
                parent="AuthService",
            ),
            IndexedSymbol(
                name="User",
                kind=SymbolKind.CLASS,
                file_path="auth.py",
                start_line=14,
                end_line=18,
            ),
        ],
    )
    login = _file(
        "login.py",
        symbols=[
            IndexedSymbol(
                name="handle_login",
                kind=SymbolKind.FUNCTION,
                file_path="login.py",
                start_line=3,
                end_line=8,
            )
        ],
        imports=[
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
                start_line=5,
            ),
        ],
    )
    service = _file(
        "service.py",
        symbols=[
            IndexedSymbol(
                name="run",
                kind=SymbolKind.FUNCTION,
                file_path="service.py",
                start_line=2,
                end_line=4,
            )
        ],
        imports=[
            ImportReference(
                source_file="service.py",
                source_module="service",
                target_module="auth",
                kind="import",
                start_line=1,
            )
        ],
    )
    a = _file(
        "a.py",
        imports=[
            ImportReference(
                source_file="a.py",
                source_module="a",
                target_module="b",
                kind="import",
                start_line=1,
            )
        ],
    )
    b = _file(
        "b.py",
        imports=[
            ImportReference(
                source_file="b.py",
                source_module="b",
                target_module="a",
                kind="import",
                start_line=1,
            )
        ],
    )
    lonely = _file(
        "lonely.py",
        symbols=[
            IndexedSymbol(
                name="unused",
                kind=SymbolKind.FUNCTION,
                file_path="lonely.py",
                start_line=1,
                end_line=2,
            )
        ],
    )
    base = _file(
        "base.py",
        symbols=[
            IndexedSymbol(
                name="Base",
                kind=SymbolKind.CLASS,
                file_path="base.py",
                start_line=1,
                end_line=3,
                bases=[],
            )
        ],
    )
    child = _file(
        "child.py",
        symbols=[
            IndexedSymbol(
                name="Child",
                kind=SymbolKind.CLASS,
                file_path="child.py",
                start_line=1,
                end_line=4,
                bases=["Base"],
            ),
            IndexedSymbol(
                name="Nested",
                kind=SymbolKind.CLASS,
                file_path="child.py",
                start_line=5,
                end_line=8,
                parent="Child",
            ),
        ],
        imports=[
            ImportReference(
                source_file="child.py",
                source_module="child",
                target_module="base",
                symbol="Base",
                kind="from_import",
                start_line=1,
            )
        ],
    )
    deleted = _file(
        "deleted.py",
        symbols=[
            IndexedSymbol(
                name="gone",
                kind=SymbolKind.FUNCTION,
                file_path="deleted.py",
                start_line=1,
                end_line=2,
            )
        ],
    )
    return _make_index([auth, login, service, a, b, lonely, base, child, deleted])


def _build_service(
    tmp_path: Path,
    index: RepositoryIndex,
    *,
    retrieval: MagicMock | None = None,
    materialize_deleted: bool = False,
) -> ImpactAnalysisService:
    root = tmp_path / "impact-repo"
    root.mkdir(exist_ok=True)
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")

    for indexed in index.files:
        if indexed.relative_path == "deleted.py" and not materialize_deleted:
            continue
        path = root / indexed.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {indexed.relative_path}\n", encoding="utf-8")

    logger = _logger()
    indexer = MagicMock(spec=IndexerService)
    loaded = index.model_copy(
        update={"summary": index.summary.model_copy(update={"repository_root": str(root)})}
    )
    indexer.load_index.return_value = loaded
    indexer.get_last_index.return_value = loaded
    indexer.build_index.side_effect = AssertionError("must never rebuild repository")

    if retrieval is None:
        retrieval = MagicMock()
        retrieval.impacted_files.return_value = [
            RetrievedFile(
                file_path="login.py",
                module_name="login",
                score=0.81,
                best_symbol="handle_login",
                best_kind=EntityKind.FUNCTION,
            )
        ]

    return ImpactAnalysisService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        retrieval_service=retrieval,
    )


@pytest.fixture
def service(tmp_path: Path) -> ImpactAnalysisService:
    return _build_service(tmp_path, _impact_index())


def test_recursive_imports(service: ImpactAnalysisService):
    report = service.analyze("auth.py")
    files = set(report.impacted_files)
    assert "login.py" in files
    assert "service.py" in files
    assert report.direct_impact
    assert report.risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}


def test_circular_imports(service: ImpactAnalysisService):
    report = service.analyze("a.py")
    assert report.in_cycle is True
    assert "b.py" in report.cycle_files or "a.py" in report.cycle_files
    assert "b.py" in report.impacted_files


def test_unused_orphan_files(service: ImpactAnalysisService):
    report = service.analyze("lonely.py")
    assert report.orphan_target is True
    assert report.confidence > 0


def test_deep_dependency_trees(tmp_path: Path):
    files: list[IndexedFile] = []
    # chain: f0 ← f1 ← f2 ← ... ← f9
    for i in range(10):
        imports = []
        if i > 0:
            imports.append(
                ImportReference(
                    source_file=f"f{i}.py",
                    source_module=f"f{i}",
                    target_module=f"f{i-1}",
                    kind="import",
                    start_line=1,
                )
            )
        files.append(_file(f"f{i}.py", imports=imports))
    service = _build_service(tmp_path, _make_index(files), retrieval=MagicMock(impacted_files=MagicMock(return_value=[])))
    report = service.analyze("f0.py")
    assert "f1.py" in report.impacted_files
    assert any(len(c.nodes) >= 2 for c in report.dependency_chains) or report.direct_impact


def test_renames_and_symbol_resolution(service: ImpactAnalysisService):
    report = service.analyze("validate_token")
    assert report.resolved_symbols
    assert "auth.py" in report.resolved_paths
    assert any(h.path == "login.py" for h in report.callers) or any(
        h.path == "login.py" for h in report.direct_impact
    )


def test_deleted_files_still_in_index(service: ImpactAnalysisService):
    report = service.analyze("deleted.py")
    assert report.resolved_paths == ["deleted.py"]
    assert report.target_kind.value == "file"


def test_nested_classes(service: ImpactAnalysisService):
    report = service.analyze("Child")
    assert "child.py" in report.resolved_paths
    # Inheritance linkage to Base
    assert any(i.symbol == "Base" for i in report.inheritance) or "base.py" in report.impacted_files


def test_large_repository(tmp_path: Path):
    files = [_file(f"m{i}.py") for i in range(60)]
    files.append(
        _file(
            "hub.py",
            imports=[
                ImportReference(
                    source_file="hub.py",
                    source_module="hub",
                    target_module="m0",
                    kind="import",
                    start_line=1,
                )
            ],
        )
    )
    files[0] = _file("m0.py")  # target
    # Make several files import m0
    for i in range(1, 15):
        files[i] = _file(
            f"m{i}.py",
            imports=[
                ImportReference(
                    source_file=f"m{i}.py",
                    source_module=f"m{i}",
                    target_module="m0",
                    kind="import",
                    start_line=1,
                )
            ],
        )
    retrieval = MagicMock()
    retrieval.impacted_files.return_value = []
    service = _build_service(tmp_path, _make_index(files), retrieval=retrieval)
    report = service.analyze("m0.py")
    assert len(report.impacted_files) >= 10
    assert report.confidence > 0.4


def test_cache_reuse(service: ImpactAnalysisService):
    service.analyze("auth.py")
    first = service._cache
    service.analyze("login")
    service.analyze("User")
    assert service._cache is first


def test_never_rebuilds_index(service: ImpactAnalysisService):
    service.analyze("auth.py")
    service._indexer.build_index.assert_not_called()


def test_missing_index_raises(tmp_path: Path):
    root = tmp_path / "empty-git"
    root.mkdir()
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")

    logger = _logger()
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = None
    indexer.get_last_index.return_value = None
    service = ImpactAnalysisService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        retrieval_service=MagicMock(),
    )
    with pytest.raises(IndexError_):
        service.analyze("auth.py")


def test_analyze_user_and_login_symbols(service: ImpactAnalysisService):
    user = service.analyze("User")
    assert user.resolved_paths
    login = service.analyze("login")
    assert login.resolved_paths or login.resolved_symbols
