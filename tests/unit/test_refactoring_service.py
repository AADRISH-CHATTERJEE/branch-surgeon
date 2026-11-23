"""Tests for RefactoringService — end-to-end orchestration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refactory.core.logger import get_service_logger
from refactory.documentation.models import DocGap
from refactory.documentation.service import DocumentationService
from refactory.graph.models import DeadCodeCandidate, DependencyCycle, NodeKind
from refactory.graph.service import RepositoryGraphService
from refactory.indexer.models import (
    IndexedFile,
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary,
)
from refactory.indexer.service import IndexerService
from refactory.parser.models import (
    FileMetadata,
    ParsedFile,
    ParsedFunction,
    ParsedModule,
)
from refactory.parser.service import ParserService
from refactory.refactor.models import (
    RefactorAnalysis,
    RefactorCategory,
    RefactorSeverity,
)
from refactory.refactor.service import RefactoringService


def _logger():
    return get_service_logger("test.refactor.svc")


def _minimal_index(files: list[IndexedFile] | None = None) -> RepositoryIndex:
    return RepositoryIndex(
        summary=RepositorySummary(
            repository_root="/repo",
            repository_name="test",
            timestamp=datetime(2025, 1, 1),
        ),
        statistics=RepositoryStatistics(),
        files=files or [],
    )


def _indexed_file(path: str = "mod.py") -> IndexedFile:
    return IndexedFile(
        relative_path=path,
        language="python",
        content_hash="abc",
        module_name=path.removesuffix(".py"),
    )


def _parsed_file(path: str = "mod.py", line_count: int = 50) -> ParsedFile:
    return ParsedFile(
        metadata=FileMetadata(path=path, language="python", line_count=line_count),
        module=ParsedModule(name=path.removesuffix(".py")),
    )


def _build_service(
    index: RepositoryIndex | None = None,
    parsed_map: dict[str, ParsedFile] | None = None,
) -> RefactoringService:
    _index = index or _minimal_index()
    _parsed = parsed_map or {}

    def _resolve_key(p: Path) -> str:
        s = str(p).replace("\\", "/")
        for key in _parsed:
            if s.endswith("/" + key) or s.endswith("\\" + key) or s == key:
                return key
        return s

    parser = MagicMock(spec=ParserService)
    parser.parse_file.side_effect = lambda p: _parsed.get(_resolve_key(p))

    indexer = MagicMock(spec=IndexerService)
    indexer.load_index.return_value = _index
    indexer.index_repository.return_value = _index

    graph = MagicMock(spec=RepositoryGraphService)
    graph.build_graph.return_value = None
    graph.dead_code_candidates.return_value = []
    graph.find_cycles.return_value = []

    docs = MagicMock(spec=DocumentationService)
    docs.find_missing_docstrings.return_value = []

    svc = RefactoringService(
        logger=_logger(),
        parser_service=parser,
        indexer_service=indexer,
        graph_service=graph,
        documentation_service=docs,
    )
    # Patch _parse_all to bypass filesystem check
    original_parse_all = svc._parse_all

    def _mock_parse_all(repo_root: Path, index: RepositoryIndex) -> dict[str, ParsedFile]:
        result: dict[str, ParsedFile] = {}
        for f in index.files:
            key = f.relative_path
            if key in _parsed:
                result[key] = _parsed[key]
        return result

    svc._parse_all = _mock_parse_all  # type: ignore[assignment]
    return svc


class TestAnalyze:
    def test_empty_repo(self):
        svc = _build_service()
        result = svc.analyze(Path("/repo"))
        assert isinstance(result, RefactorAnalysis)
        assert result.metrics.files_analyzed == 0
        assert result.metrics.total_issues == 0
        assert result.metrics.health_score == 100

    def test_clean_repo(self):
        idx = _minimal_index([_indexed_file("main.py")])
        parsed = {"main.py": _parsed_file("main.py", line_count=50)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"))
        assert result.metrics.files_analyzed == 1
        assert result.metrics.health_score > 0

    def test_large_file_detected(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"))
        large = [i for i in result.issues if i.category == RefactorCategory.LARGE_FILE]
        assert len(large) >= 1

    def test_scope_file(self):
        idx = _minimal_index([_indexed_file("a.py"), _indexed_file("b.py")])
        parsed = {
            "a.py": _parsed_file("a.py", line_count=500),
            "b.py": _parsed_file("b.py", line_count=500),
        }
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"), target_file="a.py")
        assert result.scope == "file"
        files = {i.file for i in result.issues}
        assert "b.py" not in files

    def test_category_filter(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"), category_filter="dead_code")
        assert not any(i.category == RefactorCategory.LARGE_FILE for i in result.issues)

    def test_severity_filter(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"), severity_filter="high")
        for issue in result.issues:
            assert issue.severity == RefactorSeverity.HIGH

    def test_invalid_category_filter_ignored(self):
        svc = _build_service()
        result = svc.analyze(Path("/repo"), category_filter="nonexistent")
        assert isinstance(result, RefactorAnalysis)

    def test_invalid_severity_filter_ignored(self):
        svc = _build_service()
        result = svc.analyze(Path("/repo"), severity_filter="extreme")
        assert isinstance(result, RefactorAnalysis)

    def test_plan_generated(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"))
        assert len(result.plan.steps) > 0

    def test_recommendations_generated(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"))
        assert len(result.recommendations) > 0

    def test_notes_include_elapsed(self):
        svc = _build_service()
        result = svc.analyze(Path("/repo"))
        assert any("completed" in n.lower() for n in result.notes)


class TestAnalyzeJson:
    def test_valid_json(self):
        svc = _build_service()
        raw = svc.analyze_json(Path("/repo"))
        data = json.loads(raw)
        assert "scope" in data
        assert "issues" in data
        assert "metrics" in data

    def test_json_with_issues(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        raw = svc.analyze_json(Path("/repo"))
        data = json.loads(raw)
        assert len(data["issues"]) > 0


class TestMetrics:
    def test_health_score_degrades(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"))
        assert result.metrics.health_score < 100

    def test_grade_a_for_clean(self):
        svc = _build_service()
        result = svc.analyze(Path("/repo"))
        assert result.metrics.grade == "A"

    def test_largest_file_tracked(self):
        idx = _minimal_index([_indexed_file("big.py")])
        parsed = {"big.py": _parsed_file("big.py", line_count=500)}
        svc = _build_service(idx, parsed)
        result = svc.analyze(Path("/repo"))
        assert result.metrics.largest_file_lines == 500

    def test_index_fallback_when_none(self):
        parser = MagicMock(spec=ParserService)
        indexer = MagicMock(spec=IndexerService)
        indexer.load_index.return_value = None
        indexer.build_index.return_value = _minimal_index()
        graph = MagicMock(spec=RepositoryGraphService)
        graph.build_graph.return_value = None
        graph.dead_code_candidates.return_value = []
        graph.find_cycles.return_value = []
        docs = MagicMock(spec=DocumentationService)
        docs.find_missing_docstrings.return_value = []
        svc = RefactoringService(
            logger=_logger(),
            parser_service=parser,
            indexer_service=indexer,
            graph_service=graph,
            documentation_service=docs,
        )
        result = svc.analyze(Path("/repo"))
        assert isinstance(result, RefactorAnalysis)
        indexer.build_index.assert_called_once()
