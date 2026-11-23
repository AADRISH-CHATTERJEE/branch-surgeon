"""Stabilization sprint regression tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from refactory.cache.store import DeterministicCache
from refactory.codesearch.service import CodeSearchService
from refactory.core.logger import get_service_logger
from refactory.git.service import GitService
from refactory.graph.models import FileNode, NodeKind, RepositoryGraph
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
from refactory.retrieval.service import RetrievalService
from refactory.testing.service import TestIntelligenceService


def _logger(name: str = "test.stabilize"):
    return get_service_logger(name)


def _summary(**kwargs: object) -> RepositorySummary:
    base = dict(
        repository_root="/tmp/stabilize",
        repository_name="stabilize",
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
) -> IndexedFile:
    return IndexedFile(
        relative_path=path,
        language="python",
        content_hash=(path + "h" * 64)[:64],
        module_name=Path(path).stem,
        symbols=symbols or [],
        import_references=imports or [],
    )


def _auth_graph_index() -> RepositoryIndex:
    auth = _file(
        "auth.py",
        symbols=[
            IndexedSymbol(
                name="validate_token",
                kind=SymbolKind.FUNCTION,
                file_path="auth.py",
                start_line=1,
                end_line=3,
            )
        ],
    )
    login = _file(
        "login.py",
        symbols=[
            IndexedSymbol(
                name="login",
                kind=SymbolKind.FUNCTION,
                file_path="login.py",
                start_line=1,
                end_line=3,
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
            )
        ],
    )
    service = _file(
        "service.py",
        imports=[
            ImportReference(
                source_file="service.py",
                source_module="service",
                target_module="auth",
                symbol="validate_token",
                kind="from_import",
                start_line=1,
            )
        ],
    )
    helper = _file("helper_orphan.py")
    return _make_index([auth, login, service, helper])


def _init_git(root: Path) -> None:
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")


def test_graph_cache_rehydrates_file_nodes(tmp_path: Path):
    """Cached graphs must restore FileNode subclasses (impact find_file)."""
    cache = DeterministicCache(
        enabled=True, disk_dir=tmp_path / "cache", namespace="graph"
    )
    logger = _logger("graph.cache")
    index = _auth_graph_index()
    first = RepositoryGraphService(logger=logger, cache=cache)
    g1 = first.build_graph(index)
    assert isinstance(first.find_file("auth.py"), FileNode)

    second = RepositoryGraphService(logger=logger, cache=cache)
    g2 = second.build_graph(index)
    assert g2.statistics.total_nodes == g1.statistics.total_nodes
    node = second.find_file("auth.py")
    assert isinstance(node, FileNode)
    assert node.file_path == "auth.py"
    assert second.reverse_dependencies("auth.py") == ["login.py", "service.py"]


def test_repository_graph_model_validate_preserves_file_node():
    graph = RepositoryGraph(repository_name="x", repository_root="/tmp")
    graph.nodes["file:auth.py"] = FileNode(
        id="file:auth.py",
        kind=NodeKind.FILE,
        name="auth.py",
        file_path="auth.py",
        language="python",
    )
    graph.file_index["auth.py"] = "file:auth.py"
    restored = RepositoryGraph.model_validate(graph.model_dump(mode="json"))
    node = restored.nodes["file:auth.py"]
    assert isinstance(node, FileNode)


def test_impact_direct_dependents_and_chains(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _init_git(root)
    index = _auth_graph_index()
    logger = _logger("impact")
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = index
    indexer.get_last_index.return_value = index
    retrieval = MagicMock(spec=RetrievalService)
    retrieval.impacted_files.return_value = []
    service = ImpactAnalysisService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        retrieval_service=retrieval,
    )
    report = service.analyze("auth.py")
    direct_paths = {i.path for i in report.direct_impact}
    assert "login.py" in direct_paths
    assert "service.py" in direct_paths
    assert any("imports auth.py" in r for i in report.direct_impact for r in i.reasons)
    assert report.dependency_chains
    assert any(
        chain.nodes[:2] == ["auth.py", "login.py"] or chain.nodes[:2] == ["auth.py", "service.py"]
        for chain in report.dependency_chains
    )
    assert report.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL, RiskLevel.MEDIUM}


def test_impact_orphan_helper_is_low_risk(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _init_git(root)
    index = _auth_graph_index()
    logger = _logger("impact.low")
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = index
    indexer.get_last_index.return_value = index
    retrieval = MagicMock(spec=RetrievalService)
    retrieval.impacted_files.return_value = []
    service = ImpactAnalysisService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        retrieval_service=retrieval,
    )
    report = service.analyze("helper_orphan.py")
    assert report.risk_level == RiskLevel.LOW


def test_related_prefers_graph_before_embeddings(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _init_git(root)
    index = _auth_graph_index()
    logger = _logger("related")
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = index
    indexer.get_last_index.return_value = index
    retrieval = MagicMock(spec=RetrievalService)
    retrieval.related_files.return_value = []
    retrieval.has_store.return_value = False
    service = CodeSearchService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        retrieval_service=retrieval,
    )
    result = service.find_related("auth.py", top_k=10)
    paths = [h.file for h in result.hits]
    assert "login.py" in paths
    assert "service.py" in paths
    assert result.structural_hits >= 2
    assert any("embed" in n.lower() for n in result.notes)


def _testing_service(tmp_path: Path, index: RepositoryIndex) -> TestIntelligenceService:
    root = tmp_path / "repo"
    root.mkdir()
    _init_git(root)
    logger = _logger("testing")
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = index
    indexer.get_last_index.return_value = index
    indexer.build_index.side_effect = AssertionError("no rebuild")
    return TestIntelligenceService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        commit_service=MagicMock(),
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        impact_analysis_service=MagicMock(),
        repository_analysis_service=MagicMock(),
        code_search_service=MagicMock(),
    )


def test_unknown_target_reports_not_found(tmp_path: Path):
    index = _make_index(
        [
            _file("auth.py"),
            _file(
                "tests/test_auth.py",
                symbols=[
                    IndexedSymbol(
                        name="test_ok",
                        kind=SymbolKind.FUNCTION,
                        file_path="tests/test_auth.py",
                        start_line=1,
                        end_line=2,
                    )
                ],
            ),
        ]
    )
    service = _testing_service(tmp_path, index)
    report = service.find_related_tests("abc.py")
    assert report.target_found is False
    assert report.coverage_confidence == 0.0
    assert any("was not found" in n for n in report.notes)


def test_conftest_excluded_from_orphan_tests(tmp_path: Path):
    index = _make_index(
        [
            _file("auth.py"),
            _file(
                "tests/conftest.py",
                symbols=[
                    IndexedSymbol(
                        name="valid_token",
                        kind=SymbolKind.FUNCTION,
                        file_path="tests/conftest.py",
                        start_line=1,
                        end_line=2,
                    )
                ],
            ),
            _file(
                "tests/orphan_test.py",
                symbols=[
                    IndexedSymbol(
                        name="test_math",
                        kind=SymbolKind.FUNCTION,
                        file_path="tests/orphan_test.py",
                        start_line=1,
                        end_line=2,
                    )
                ],
            ),
        ]
    )
    service = _testing_service(tmp_path, index)
    orphans = {o.path for o in service.find_orphan_tests()}
    assert "tests/conftest.py" not in orphans
    assert "tests/orphan_test.py" in orphans


def test_indexer_detects_stale_file_count(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("x=1\n", encoding="utf-8")
    (root / "b.py").write_text("y=2\n", encoding="utf-8")
    logger = _logger("stale")
    parser = ParserService(ignore_dirs=[".git"], logger=logger)
    indexer = IndexerService(parser_service=parser, ignore_dirs=[".git"], logger=logger)
    built = indexer.build_index(root, repository_name="stale", force=True)
    assert built.summary.total_indexed_files == 2
    (root / "c.py").write_text("z=3\n", encoding="utf-8")
    info = indexer.assess_staleness(root)
    assert info["is_stale"] is True
    assert info["indexed_files"] == 2
    assert info["current_files"] == 3
