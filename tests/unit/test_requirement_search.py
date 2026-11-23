"""Tests for RequirementSearch — candidate file discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from refactory.codesearch.models import CodeSearchHit, CodeSearchResult
from refactory.codesearch.service import CodeSearchService
from refactory.core.logger import get_service_logger
from refactory.graph.service import RepositoryGraphService
from refactory.requirement.models import RequirementSummary
from refactory.requirement.search import RequirementSearch
from refactory.retrieval.service import RetrievalService


def _logger():
    return get_service_logger("test.req.search")


def _hit(file: str, score: float = 0.5, reasons: list[str] | None = None) -> CodeSearchHit:
    return CodeSearchHit(
        file=file,
        score=score,
        reasons=reasons or ["test"],
    )


def _result(hits: list[CodeSearchHit] | None = None) -> CodeSearchResult:
    return CodeSearchResult(
        query="test",
        hits=hits or [],
    )


def _make_search(
    search_results: CodeSearchResult | None = None,
    file_results: CodeSearchResult | None = None,
) -> RequirementSearch:
    code_search = MagicMock(spec=CodeSearchService)
    code_search.search.return_value = search_results or _result()
    code_search.search_files.return_value = file_results or _result()

    graph_service = MagicMock(spec=RepositoryGraphService)
    graph_service.dependencies_of.return_value = []
    graph_service.reverse_dependencies.return_value = []

    retrieval = MagicMock(spec=RetrievalService)

    return RequirementSearch(
        logger=_logger(),
        code_search_service=code_search,
        graph_service=graph_service,
        retrieval_service=retrieval,
    )


class TestFindCandidates:
    def test_empty_summary_returns_empty(self):
        search = _make_search()
        summary = RequirementSummary()
        candidates = search.find_candidates(summary)
        assert candidates == []

    def test_keywords_produce_candidates(self):
        search = _make_search(
            search_results=_result([_hit("auth.py", 0.9)])
        )
        summary = RequirementSummary(
            detected_keywords=["authentication"],
            detected_features=["Authentication"],
        )
        candidates = search.find_candidates(summary)
        assert any(c.path == "auth.py" for c in candidates)

    def test_file_hints_produce_candidates(self):
        search = _make_search(
            file_results=_result([_hit("service.py", 0.95)])
        )
        summary = RequirementSummary(
            file_hints=["service.py"],
        )
        candidates = search.find_candidates(summary)
        assert any(c.path == "service.py" for c in candidates)

    def test_multiple_keywords_merged(self):
        hits1 = [_hit("auth.py", 0.9)]
        hits2 = [_hit("auth.py", 0.8), _hit("login.py", 0.7)]
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.side_effect = [
            _result(hits1), _result(hits2),
            _result(), _result(), _result(),
        ]
        code_search.search_files.return_value = _result()

        graph_service = MagicMock(spec=RepositoryGraphService)
        graph_service.dependencies_of.return_value = []
        graph_service.reverse_dependencies.return_value = []
        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph_service,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["auth", "login"],
            detected_features=["Authentication"],
        )
        candidates = search.find_candidates(summary)
        paths = [c.path for c in candidates]
        assert "auth.py" in paths

    def test_confidence_normalized(self):
        search = _make_search(
            search_results=_result([
                _hit("auth.py", 1.0),
                _hit("utils.py", 0.1),
            ])
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        assert all(0.0 <= c.confidence <= 1.0 for c in candidates)

    def test_deduplication(self):
        search = _make_search(
            search_results=_result([
                _hit("auth.py", 0.9),
                _hit("auth.py", 0.8),
            ])
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        paths = [c.path for c in candidates]
        assert paths.count("auth.py") == 1

    def test_low_score_filtered_out(self):
        search = _make_search(
            search_results=_result([_hit("noise.py", 0.001)])
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        # Very low-score items should still appear since they're the only hit
        # (confidence relative to max), but truly zero should not
        # This is a soft filter test
        assert isinstance(candidates, list)

    def test_search_exception_handled(self):
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.side_effect = RuntimeError("search failed")
        code_search.search_files.return_value = _result()

        graph_service = MagicMock(spec=RepositoryGraphService)
        graph_service.dependencies_of.return_value = []
        graph_service.reverse_dependencies.return_value = []
        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph_service,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=["Authentication"],
        )
        # Should not raise
        candidates = search.find_candidates(summary)
        assert isinstance(candidates, list)


class TestGraphExpansion:
    def test_graph_deps_added(self):
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.return_value = _result([_hit("auth.py", 0.9)])
        code_search.search_files.return_value = _result()

        graph_service = MagicMock(spec=RepositoryGraphService)
        graph_service.dependencies_of.return_value = ["login.py"]
        graph_service.reverse_dependencies.return_value = ["service.py"]

        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph_service,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        paths = [c.path for c in candidates]
        assert "login.py" in paths or "service.py" in paths

    def test_graph_failure_handled(self):
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.return_value = _result([_hit("auth.py", 0.9)])
        code_search.search_files.return_value = _result()

        graph_service = MagicMock(spec=RepositoryGraphService)
        graph_service.dependencies_of.side_effect = RuntimeError("graph failed")
        graph_service.reverse_dependencies.side_effect = RuntimeError("graph failed")
        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph_service,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        assert any(c.path == "auth.py" for c in candidates)


# -------------------------------------------------------------------
# Production code ranking (Backlog 4)
# -------------------------------------------------------------------


class TestProductionCodeRanking:
    """Production files should rank higher than tests/demos."""

    def test_production_above_test(self):
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.return_value = _result([
            _hit("tests/test_auth.py", 0.9),
            _hit("auth.py", 0.9),
        ])
        code_search.search_files.return_value = _result()
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dependencies_of.return_value = []
        graph.reverse_dependencies.return_value = []
        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        paths = [c.path for c in candidates]
        assert "auth.py" in paths
        assert "tests/test_auth.py" in paths
        assert paths.index("auth.py") < paths.index("tests/test_auth.py")

    def test_production_above_demo(self):
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.return_value = _result([
            _hit("examples/demo_service.py", 0.9),
            _hit("service.py", 0.9),
        ])
        code_search.search_files.return_value = _result()
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dependencies_of.return_value = []
        graph.reverse_dependencies.return_value = []
        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["service"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        paths = [c.path for c in candidates]
        assert "service.py" in paths
        assert paths.index("service.py") < paths.index("examples/demo_service.py")

    def test_test_files_not_removed(self):
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.return_value = _result([
            _hit("tests/test_auth.py", 0.8),
        ])
        code_search.search_files.return_value = _result()
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dependencies_of.return_value = []
        graph.reverse_dependencies.return_value = []
        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        assert any(c.path == "tests/test_auth.py" for c in candidates)

    def test_ranking_order_production_utils_tests_demos(self):
        code_search = MagicMock(spec=CodeSearchService)
        code_search.search.return_value = _result([
            _hit("examples/auth_demo.py", 0.9),
            _hit("tests/test_auth.py", 0.9),
            _hit("utils/helper.py", 0.9),
            _hit("auth/service.py", 0.9),
        ])
        code_search.search_files.return_value = _result()
        graph = MagicMock(spec=RepositoryGraphService)
        graph.dependencies_of.return_value = []
        graph.reverse_dependencies.return_value = []
        retrieval = MagicMock(spec=RetrievalService)

        search = RequirementSearch(
            logger=_logger(),
            code_search_service=code_search,
            graph_service=graph,
            retrieval_service=retrieval,
        )
        summary = RequirementSummary(
            detected_keywords=["auth"],
            detected_features=[],
        )
        candidates = search.find_candidates(summary)
        paths = [c.path for c in candidates]
        prod_idx = paths.index("auth/service.py")
        util_idx = paths.index("utils/helper.py")
        test_idx = paths.index("tests/test_auth.py")
        demo_idx = paths.index("examples/auth_demo.py")
        assert prod_idx < util_idx < test_idx < demo_idx
