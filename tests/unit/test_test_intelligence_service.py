"""Unit tests for TestIntelligenceService (local only — no AI/network)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from refactory.codesearch.models import CodeSearchResult
from refactory.core.exceptions import IndexError_
from refactory.core.logger import get_service_logger
from refactory.git.commit_service import CommitService
from refactory.git.service import GitService
from refactory.graph.service import RepositoryGraphService
from refactory.impact.models import ImpactReport, ImpactTargetKind, RiskLevel
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
from refactory.testing.service import TestIntelligenceService


def _logger():
    return get_service_logger("test.testing")


def _summary(**kwargs: object) -> RepositorySummary:
    base = dict(
        repository_root="/tmp/testing",
        repository_name="testing-demo",
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
        summary=_summary(total_indexed_files=len(files)),
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
    import_lines: list[str] | None = None,
) -> IndexedFile:
    return IndexedFile(
        relative_path=path,
        language="python",
        content_hash=(path + "h" * 64)[:64],
        module_name=Path(path).stem.replace("test_", ""),
        symbols=symbols or [],
        import_references=imports or [],
        imports=import_lines or [],
    )


def _standard_layout_index() -> RepositoryIndex:
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
                name="User",
                kind=SymbolKind.CLASS,
                file_path="auth.py",
                start_line=6,
                end_line=12,
            ),
            IndexedSymbol(
                name="login",
                kind=SymbolKind.METHOD,
                file_path="auth.py",
                start_line=8,
                end_line=10,
                parent="User",
            ),
        ],
    )
    pytest_test = _file(
        "tests/test_auth.py",
        symbols=[
            IndexedSymbol(
                name="test_validate_token",
                kind=SymbolKind.FUNCTION,
                file_path="tests/test_auth.py",
                start_line=4,
                end_line=8,
            ),
            IndexedSymbol(
                name="test_user",
                kind=SymbolKind.FUNCTION,
                file_path="tests/test_auth.py",
                start_line=10,
                end_line=14,
            ),
        ],
        imports=[
            ImportReference(
                source_file="tests/test_auth.py",
                source_module="tests.test_auth",
                target_module="auth",
                symbol="validate_token",
                kind="from_import",
                start_line=1,
            ),
            ImportReference(
                source_file="tests/test_auth.py",
                source_module="tests.test_auth",
                target_module="auth",
                symbol="validate_token",
                kind="call",
                start_line=5,
            ),
        ],
        import_lines=["import pytest", "from auth import validate_token"],
    )
    unittest_test = _file(
        "tests/unit/test_user.py",
        symbols=[
            IndexedSymbol(
                name="TestUser",
                kind=SymbolKind.CLASS,
                file_path="tests/unit/test_user.py",
                start_line=3,
                end_line=20,
            ),
            IndexedSymbol(
                name="test_login",
                kind=SymbolKind.METHOD,
                file_path="tests/unit/test_user.py",
                start_line=5,
                end_line=8,
                parent="TestUser",
            ),
        ],
        imports=[
            ImportReference(
                source_file="tests/unit/test_user.py",
                source_module="tests.unit.test_user",
                target_module="auth",
                symbol="User",
                kind="from_import",
                start_line=1,
            )
        ],
        import_lines=["import unittest", "from auth import User"],
    )
    nested = _file(
        "tests/nested/deep/test_auth.py",
        symbols=[
            IndexedSymbol(
                name="test_validate_token",
                kind=SymbolKind.FUNCTION,
                file_path="tests/nested/deep/test_auth.py",
                start_line=1,
                end_line=3,
            )
        ],
        imports=[
            ImportReference(
                source_file="tests/nested/deep/test_auth.py",
                source_module="tests.nested.deep.test_auth",
                target_module="auth",
                kind="import",
                start_line=1,
            )
        ],
        import_lines=["import auth"],
    )
    orphan = _file(
        "tests/test_orphan.py",
        symbols=[
            IndexedSymbol(
                name="test_nothing",
                kind=SymbolKind.FUNCTION,
                file_path="tests/test_orphan.py",
                start_line=1,
                end_line=2,
            )
        ],
        import_lines=["import pytest"],
    )
    uncovered = _file(
        "payments.py",
        symbols=[
            IndexedSymbol(
                name="charge",
                kind=SymbolKind.FUNCTION,
                file_path="payments.py",
                start_line=1,
                end_line=3,
            )
        ],
    )
    return _make_index([auth, pytest_test, unittest_test, nested, orphan, uncovered])


def _build_service(tmp_path: Path, index: RepositoryIndex) -> TestIntelligenceService:
    root = tmp_path / "test-intel-repo"
    root.mkdir(exist_ok=True)
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "t@example.com")
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("init")

    for indexed in index.files:
        path = root / indexed.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {indexed.relative_path}\n", encoding="utf-8")

    logger = _logger()
    loaded = index.model_copy(
        update={"summary": index.summary.model_copy(update={"repository_root": str(root)})}
    )
    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = loaded
    indexer.get_last_index.return_value = loaded
    indexer.build_index.side_effect = AssertionError("must never rebuild")

    impact = MagicMock(spec=ImpactAnalysisService)
    impact.analyze.return_value = ImpactReport(
        target="auth.py",
        target_kind=ImpactTargetKind.FILE,
        resolved_paths=["auth.py"],
        impacted_files=["auth.py", "payments.py"],
        risk_level=RiskLevel.MEDIUM,
        confidence=0.7,
    )

    analysis = MagicMock()
    analysis.get_repository_languages.return_value = {"python": 3}

    commits = MagicMock(spec=CommitService)
    commits.get_recent_commits.return_value = []

    search = MagicMock()
    search.find_related.return_value = CodeSearchResult(query="", hits=[])

    return TestIntelligenceService(
        logger=logger,
        git_service=GitService(logger=logger, path=root),
        commit_service=commits,
        parser_service=ParserService(ignore_dirs=[".git"], logger=logger),
        indexer_service=indexer,
        graph_service=RepositoryGraphService(logger=logger),
        impact_analysis_service=impact,
        repository_analysis_service=analysis,
        code_search_service=search,
    )


@pytest.fixture
def service(tmp_path: Path) -> TestIntelligenceService:
    return _build_service(tmp_path, _standard_layout_index())


def test_standard_pytest_layout(service: TestIntelligenceService):
    report = service.find_tests_for_file("auth.py")
    paths = {t.path for t in report.tests}
    assert "tests/test_auth.py" in paths
    assert report.coverage_confidence > 0
    assert any(t.framework.value == "pytest" for t in report.tests)


def test_unittest_layout(service: TestIntelligenceService):
    report = service.find_related_tests("User")
    paths = {t.path for t in report.tests}
    assert "tests/unit/test_user.py" in paths or "tests/test_auth.py" in paths


def test_nested_test_folders(service: TestIntelligenceService):
    report = service.find_tests_for_file("auth.py")
    paths = {t.path for t in report.tests}
    assert "tests/nested/deep/test_auth.py" in paths


def test_multiple_matching_tests(service: TestIntelligenceService):
    report = service.find_tests_for_symbol("validate_token")
    assert len(report.tests) >= 2


def test_orphan_tests(service: TestIntelligenceService):
    orphans = service.find_orphan_tests()
    paths = {o.path for o in orphans}
    assert "tests/test_orphan.py" in paths


def test_duplicate_tests(service: TestIntelligenceService):
    groups = service.find_duplicate_tests()
    assert groups
    assert any("test_validate_token" in g.key or "auth.py" in g.key for g in groups)


def test_missing_tests_uncovered(service: TestIntelligenceService):
    uncovered = service.find_uncovered_files()
    paths = {item.path for item in uncovered}
    assert "payments.py" in paths


def test_coverage_map(service: TestIntelligenceService):
    mapping = service.compute_test_coverage_map()
    assert mapping.test_files
    assert mapping.coverage_ratio > 0
    assert "payments.py" in mapping.uncovered_files
    assert "tests/test_orphan.py" in mapping.orphan_tests


def test_estimate_test_impact(service: TestIntelligenceService):
    report = service.estimate_test_impact("auth.py")
    assert report.recommended_tests
    assert report.risk_if_skipped.value in {"low", "medium", "high", "critical"}
    assert "payments.py" in report.missing_critical_tests or report.impacted_production_files


def test_slow_test_candidates(service: TestIntelligenceService):
    # Add breadth via multi-module already present; ensure API returns list.
    candidates = service.find_slow_test_candidates(limit=10)
    assert isinstance(candidates, list)


def test_large_repository(tmp_path: Path):
    files: list[IndexedFile] = []
    for i in range(40):
        files.append(
            _file(
                f"mod_{i}.py",
                symbols=[
                    IndexedSymbol(
                        name=f"fn_{i}",
                        kind=SymbolKind.FUNCTION,
                        file_path=f"mod_{i}.py",
                        start_line=1,
                        end_line=2,
                    )
                ],
            )
        )
        files.append(
            _file(
                f"tests/test_mod_{i}.py",
                symbols=[
                    IndexedSymbol(
                        name=f"test_fn_{i}",
                        kind=SymbolKind.FUNCTION,
                        file_path=f"tests/test_mod_{i}.py",
                        start_line=1,
                        end_line=2,
                    )
                ],
                imports=[
                    ImportReference(
                        source_file=f"tests/test_mod_{i}.py",
                        source_module=f"tests.test_mod_{i}",
                        target_module=f"mod_{i}",
                        kind="import",
                        start_line=1,
                    )
                ],
            )
        )
    service = _build_service(tmp_path, _make_index(files))
    report = service.find_tests_for_file("mod_7.py")
    assert any(t.path == "tests/test_mod_7.py" for t in report.tests)
    mapping = service.compute_test_coverage_map()
    assert mapping.coverage_ratio > 0.5


def test_cache_reuse(service: TestIntelligenceService):
    service.find_related_tests("auth.py")
    first = service._cache
    service.find_orphan_tests()
    service.compute_test_coverage_map()
    assert service._cache is first


def test_never_rebuilds_index(service: TestIntelligenceService):
    service.find_related_tests("auth.py")
    service._indexer.build_index.assert_not_called()


def test_missing_index_raises(tmp_path: Path):
    root = tmp_path / "empty"
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
    service = TestIntelligenceService(
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
    with pytest.raises(IndexError_):
        service.find_related_tests("auth.py")
