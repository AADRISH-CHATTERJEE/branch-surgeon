"""Tests for embedding quality validation helpers (Backlog 2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from refactory.retrieval.validation import (
    AUTH_TOKEN_CASES,
    PrecisionResult,
    ValidationCase,
    ValidationReport,
    evaluate_retrieval,
    precision_at_k,
    recall_at_k,
)


class TestPrecisionAtK:
    def test_perfect_precision(self):
        retrieved = ["auth.py", "token.py", "login.py"]
        relevant = {"auth.py", "token.py", "login.py"}
        assert precision_at_k(retrieved, relevant, 3) == 1.0

    def test_zero_precision(self):
        retrieved = ["foo.py", "bar.py"]
        relevant = {"auth.py"}
        assert precision_at_k(retrieved, relevant, 2) == 0.0

    def test_partial_precision(self):
        retrieved = ["auth.py", "foo.py", "bar.py", "token.py"]
        relevant = {"auth.py", "token.py"}
        assert precision_at_k(retrieved, relevant, 4) == 0.5

    def test_k_zero(self):
        assert precision_at_k(["a"], {"a"}, 0) == 0.0

    def test_empty_retrieved(self):
        assert precision_at_k([], {"a"}, 5) == 0.0

    def test_k_larger_than_retrieved(self):
        retrieved = ["auth.py"]
        relevant = {"auth.py"}
        assert precision_at_k(retrieved, relevant, 10) == 1.0


class TestRecallAtK:
    def test_perfect_recall(self):
        retrieved = ["auth.py", "token.py"]
        relevant = {"auth.py", "token.py"}
        assert recall_at_k(retrieved, relevant, 5) == 1.0

    def test_zero_recall(self):
        retrieved = ["foo.py"]
        relevant = {"auth.py", "token.py"}
        assert recall_at_k(retrieved, relevant, 5) == 0.0

    def test_partial_recall(self):
        retrieved = ["auth.py", "foo.py"]
        relevant = {"auth.py", "token.py"}
        assert recall_at_k(retrieved, relevant, 5) == 0.5

    def test_empty_relevant(self):
        assert recall_at_k(["a"], set(), 5) == 1.0

    def test_k_limits_results(self):
        retrieved = ["foo.py", "auth.py"]
        relevant = {"auth.py"}
        assert recall_at_k(retrieved, relevant, 1) == 0.0
        assert recall_at_k(retrieved, relevant, 2) == 1.0


class TestValidationCase:
    def test_auth_cases_exist(self):
        assert len(AUTH_TOKEN_CASES) >= 3

    def test_case_structure(self):
        for case in AUTH_TOKEN_CASES:
            assert case.query
            assert len(case.expected_files) > 0


class TestEvaluateRetrieval:
    def test_with_mock_retrieval(self):
        retrieval = MagicMock()
        from refactory.retrieval.models import (
            RetrievedSymbol,
            RetrievalStatistics,
            SearchQuery,
            SearchResult,
            EntityKind,
        )
        retrieval.search.return_value = SearchResult(
            query=SearchQuery(text="auth"),
            hits=[
                RetrievedSymbol(
                    result="auth.py:AuthService",
                    score=0.9,
                    file_path="auth.py",
                    module_name="auth",
                    symbol="AuthService",
                    kind=EntityKind.CLASS,
                ),
            ],
            statistics=RetrievalStatistics(),
        )

        cases = [
            ValidationCase(
                query="authentication",
                expected_files=["auth.py"],
                expected_symbols=["AuthService"],
            ),
        ]
        report = evaluate_retrieval(retrieval, cases, k=5)
        assert isinstance(report, ValidationReport)
        assert len(report.cases) == 1
        assert report.cases[0].precision > 0
        assert report.mean_precision > 0

    def test_retrieval_failure_handled(self):
        retrieval = MagicMock()
        retrieval.search.side_effect = RuntimeError("no store")
        cases = [
            ValidationCase(
                query="auth",
                expected_files=["auth.py"],
            ),
        ]
        report = evaluate_retrieval(retrieval, cases, k=5)
        assert report.cases[0].precision == 0.0

    def test_report_notes_on_low_precision(self):
        retrieval = MagicMock()
        retrieval.search.side_effect = RuntimeError("no store")
        cases = AUTH_TOKEN_CASES[:2]
        report = evaluate_retrieval(retrieval, cases, k=5)
        assert any("precision" in n.lower() for n in report.notes)

    def test_empty_cases(self):
        retrieval = MagicMock()
        report = evaluate_retrieval(retrieval, [], k=5)
        assert report.mean_precision == 0.0
        assert report.cases == []
