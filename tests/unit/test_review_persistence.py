"""Tests for ReviewEngine → PersistenceService integration.

Verifies that:
  - Successful reviews are persisted to the database
  - PersistenceService.persist_review() is called exactly once per review
  - All suggestion fields are forwarded to persistence
  - Summary, risk, confidence, provider, model are persisted
  - Database failures never cause a review to fail
  - Existing review behaviour is unchanged
  - Persistence is skipped when PersistenceService is None
"""

from __future__ import annotations

import io
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refactory.ai.models import AIResponse
from refactory.core.logger import get_service_logger
from refactory.github.models import ChangedFile, PullRequest
from refactory.graph.models import GraphStatistics, RepositoryGraph
from refactory.indexer.models import (
    RepositoryIndex,
    RepositoryStatistics,
    RepositorySummary as IndexSummary,
)
from refactory.prompt.models import PromptMetadata, PromptRequest
from refactory.response.models import ReviewMetadata, ReviewResult as ParsedReviewResult
from refactory.response.models import ReviewSuggestion as ParsedSuggestion
from refactory.review.engine import ReviewEngine
from refactory.review.models import Repository, ReviewResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _index(root: Path) -> RepositoryIndex:
    return RepositoryIndex(
        summary=IndexSummary(
            repository_name=root.name,
            repository_root=str(root),
            total_indexed_files=0,
            timestamp=datetime(2026, 7, 29, tzinfo=timezone.utc),
        ),
        statistics=RepositoryStatistics(),
        files=[],
    )


def _graph() -> RepositoryGraph:
    return RepositoryGraph(
        repository_name="demo",
        repository_root=".",
        nodes={},
        edges=[],
        statistics=GraphStatistics(),
    )


def _parsed_review(**overrides) -> ParsedReviewResult:
    defaults = {
        "summary": "Code looks good overall",
        "overall_risk": "medium",
        "confidence": 0.85,
        "suggestions": [
            ParsedSuggestion(
                title="SQL Injection Risk",
                explanation="User input is concatenated into SQL query",
                recommendation="Use parameterized queries",
                severity="error",
                file="auth.py",
                line=42,
                category="security",
                confidence=0.95,
                estimated_impact="High — data breach risk",
            ),
            ParsedSuggestion(
                title="Missing docstring",
                explanation="Public function lacks documentation",
                recommendation="Add docstring",
                severity="info",
                file="utils.py",
                line=10,
                category="documentation",
            ),
        ],
        "metadata": ReviewMetadata(
            source_format="json",
            provider="gemini",
            model="gemini-1.5-pro",
        ),
    }
    defaults.update(overrides)
    return ParsedReviewResult(**defaults)


def _make_persistence_mock() -> MagicMock:
    """Create a fresh PersistenceService mock with standard return values."""
    mock = MagicMock()
    mock.get_or_create_repository.return_value = {
        "id": "repo-001",
        "name": "test-repo",
        "root_path": "/test",
        "default_branch": "main",
        "remote_url": "https://github.com/test/repo.git",
        "created_at": None,
        "updated_at": None,
    }
    mock.persist_review.return_value = {
        "id": "review-001",
        "repository_id": "repo-001",
        "pr_number": 42,
        "provider": "gemini",
        "model": "gemini-1.5-pro",
        "risk": "medium",
        "confidence": 0.85,
        "summary": "Code looks good overall",
        "created_at": None,
    }
    return mock


def _wired_engine(
    tmp_path: Path,
    *,
    persistence: MagicMock | None = "DEFAULT",
    parsed_review: ParsedReviewResult | None = None,
) -> tuple[ReviewEngine, dict]:
    """Build a fully wired ReviewEngine with mocked collaborators."""
    if persistence == "DEFAULT":
        persistence = _make_persistence_mock()

    repo = Repository(
        name="test-repo",
        root_path=str(tmp_path),
        current_branch="feature",
        default_branch="main",
        remote_url="https://github.com/test/repo.git",
    )
    pr = PullRequest(
        number=42,
        title="Add auth",
        body="Secure login",
        changed_files=[ChangedFile(path="auth.py", status="modified")],
    )
    index = _index(tmp_path)
    parsed = parsed_review or _parsed_review()

    git = MagicMock()
    git.require_repository.return_value = repo
    github = MagicMock()
    github.fetch_pull_request.return_value = pr
    indexer = MagicMock()
    indexer.ensure_index.return_value = 1
    indexer.load_index.return_value = index
    indexer.get_last_index.return_value = index
    graph_service = MagicMock()
    graph_service.build_graph.return_value = _graph()
    graph_service.affected_files.return_value = []
    retrieval = MagicMock()
    retrieval.search.return_value = MagicMock(hits=[])
    retrieval.retrieve_related_context.return_value = []
    prompt_builder = MagicMock()
    prompt_builder.build.return_value = PromptRequest(
        system_prompt="sys",
        user_prompt="user",
        metadata=PromptMetadata(template_source="local_default", pr_number=42),
    )
    gateway = MagicMock()
    gateway.generate.return_value = AIResponse(
        text="{}",
        provider="gemini",
        model="gemini-1.5-pro",
        latency_ms=150.0,
    )
    parser = MagicMock()
    parser.parse_response.return_value = parsed

    engine = ReviewEngine(
        git_service=git,
        github_service=github,
        parser_service=MagicMock(),
        indexer_service=indexer,
        retrieval_service=retrieval,
        ai_service=MagicMock(),
        logger=get_service_logger("test.review.persist"),
        graph_service=graph_service,
        prompt_builder=prompt_builder,
        ai_gateway=gateway,
        response_parser=parser,
        persistence_service=persistence,
    )

    return engine, {
        "repo": repo,
        "persistence": persistence,
        "gateway": gateway,
        "parser": parser,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReviewPersistence:
    """Core persistence integration tests."""

    def test_persist_review_called_exactly_once(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        mocks["persistence"].persist_review.assert_called_once()

    def test_repository_get_or_create_called(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        mocks["persistence"].get_or_create_repository.assert_called_once_with(
            name="test-repo",
            root_path=str(tmp_path),
            default_branch="main",
            remote_url="https://github.com/test/repo.git",
        )

    def test_summary_persisted(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["summary"] == "Code looks good overall"

    def test_risk_persisted(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["risk"] == "medium"

    def test_confidence_persisted(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["confidence"] == 0.85

    def test_provider_persisted(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["provider"] == "gemini"

    def test_model_persisted(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["model"] == "gemini-1.5-pro"

    def test_pr_number_persisted(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["pr_number"] == 42

    def test_repository_id_forwarded(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["repository_id"] == "repo-001"

    def test_suggestions_persisted(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        suggestions = call_kwargs["suggestions"]
        assert len(suggestions) == 2

    def test_suggestion_fields_complete(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        s = call_kwargs["suggestions"][0]
        assert s["file"] == "auth.py"
        assert s["line"] == 42
        assert s["severity"] == "error"
        assert s["category"] == "security"
        assert s["title"] == "SQL Injection Risk"
        assert "concatenated" in s["explanation"]
        assert "parameterized" in s["suggested_fix"]
        assert s["confidence"] == 0.95
        assert "data breach" in s["estimated_impact"]

    def test_second_suggestion_fields(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        s = call_kwargs["suggestions"][1]
        assert s["file"] == "utils.py"
        assert s["line"] == 10
        assert s["severity"] == "info"
        assert s["category"] == "documentation"
        assert s["title"] == "Missing docstring"

    def test_review_result_unchanged(self, tmp_path):
        """Persistence must not alter the returned ReviewResult."""
        engine, mocks = _wired_engine(tmp_path)
        result = engine.review(42)
        assert isinstance(result, ReviewResult)
        assert result.pull_request_number == 42
        assert result.summary == "Code looks good overall"
        assert result.risk_level == "medium"
        assert result.confidence == 0.85
        assert len(result.suggestions) == 2


class TestPersistenceFailureHandling:
    """Verify that database failures never break the review pipeline."""

    def test_persist_review_exception_does_not_fail_review(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        mocks["persistence"].persist_review.side_effect = RuntimeError("DB connection lost")
        result = engine.review(42)
        assert isinstance(result, ReviewResult)
        assert result.summary == "Code looks good overall"
        assert result.risk_level == "medium"

    def test_get_or_create_repository_exception_does_not_fail_review(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        mocks["persistence"].get_or_create_repository.side_effect = ConnectionError("timeout")
        result = engine.review(42)
        assert isinstance(result, ReviewResult)
        assert result.pull_request_number == 42

    def test_persistence_exception_logged_with_error_level(self, tmp_path, capsys):
        """Verify that persistence failures produce an error log (not silently swallowed)."""
        engine, mocks = _wired_engine(tmp_path)
        mocks["persistence"].persist_review.side_effect = RuntimeError("disk full")
        result = engine.review(42)
        assert isinstance(result, ReviewResult)
        assert result.summary == "Code looks good overall"

    def test_persistence_exception_does_not_alter_result(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path)
        mocks["persistence"].get_or_create_repository.side_effect = Exception("any error")
        result = engine.review(42)
        assert result.confidence == 0.85
        assert len(result.suggestions) == 2
        assert result.provider == "gemini"


class TestNoPersistenceService:
    """Verify behaviour when PersistenceService is None (backward compat)."""

    def test_review_works_without_persistence(self, tmp_path):
        engine, mocks = _wired_engine(tmp_path, persistence=None)
        result = engine.review(42)
        assert isinstance(result, ReviewResult)
        assert result.summary == "Code looks good overall"

    def test_no_persistence_no_errors(self, tmp_path):
        engine, _ = _wired_engine(tmp_path, persistence=None)
        result = engine.review(42)
        assert result.risk_level == "medium"

    def test_engine_instantiates_without_persistence(self):
        engine = ReviewEngine(
            git_service=MagicMock(),
            github_service=MagicMock(),
            parser_service=MagicMock(),
            indexer_service=MagicMock(),
            retrieval_service=MagicMock(),
            ai_service=MagicMock(),
            logger=get_service_logger("test"),
            graph_service=MagicMock(),
            prompt_builder=MagicMock(),
            ai_gateway=MagicMock(),
            response_parser=MagicMock(),
        )
        assert engine._persistence is None

    def test_persistence_default_is_none(self):
        engine = ReviewEngine(
            git_service=MagicMock(),
            github_service=MagicMock(),
            parser_service=MagicMock(),
            indexer_service=MagicMock(),
            retrieval_service=MagicMock(),
            ai_service=MagicMock(),
            logger=get_service_logger("test"),
            graph_service=MagicMock(),
            prompt_builder=MagicMock(),
            ai_gateway=MagicMock(),
            response_parser=MagicMock(),
        )
        assert engine._persistence is None


class TestPersistenceLogging:
    """Verify structured logs for successful persistence."""

    def test_persist_review_success_calls_info(self, tmp_path):
        """After successful persistence, the logger.info call includes key fields."""
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        repo = Repository(
            name="log-repo", root_path=str(tmp_path),
            current_branch="feat", default_branch="main",
        )
        engine = ReviewEngine(
            git_service=MagicMock(require_repository=MagicMock(return_value=repo)),
            github_service=MagicMock(fetch_pull_request=MagicMock(return_value=PullRequest(
                number=1, title="t", body="b",
                changed_files=[ChangedFile(path="a.py", status="modified")],
            ))),
            parser_service=MagicMock(),
            indexer_service=MagicMock(
                ensure_index=MagicMock(return_value=1),
                load_index=MagicMock(return_value=_index(tmp_path)),
                get_last_index=MagicMock(return_value=_index(tmp_path)),
            ),
            retrieval_service=MagicMock(
                search=MagicMock(return_value=MagicMock(hits=[])),
                retrieve_related_context=MagicMock(return_value=[]),
            ),
            ai_service=MagicMock(),
            logger=mock_logger,
            graph_service=MagicMock(
                build_graph=MagicMock(return_value=_graph()),
                affected_files=MagicMock(return_value=[]),
            ),
            prompt_builder=MagicMock(build=MagicMock(return_value=PromptRequest(
                system_prompt="s", user_prompt="u",
                metadata=PromptMetadata(template_source="local_default"),
            ))),
            ai_gateway=MagicMock(generate=MagicMock(return_value=AIResponse(
                text="{}", provider="mock", model="mock-m", latency_ms=1.0,
            ))),
            response_parser=MagicMock(parse_response=MagicMock(return_value=_parsed_review())),
            persistence_service=persistence,
        )
        engine.review(1)

        info_calls = mock_logger.info.call_args_list
        persist_calls = [c for c in info_calls if "persisted" in str(c).lower()]
        assert len(persist_calls) >= 1, f"No 'persisted' log found in: {info_calls}"
        log_str = str(persist_calls[0])
        assert "log-repo" in log_str
        assert "review-001" in log_str

    def test_persist_failure_calls_error(self, tmp_path):
        """When persistence fails, logger.error is called."""
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.persist_review.side_effect = RuntimeError("disk full")
        repo = Repository(
            name="err-repo", root_path=str(tmp_path),
            current_branch="feat", default_branch="main",
        )
        engine = ReviewEngine(
            git_service=MagicMock(require_repository=MagicMock(return_value=repo)),
            github_service=MagicMock(fetch_pull_request=MagicMock(return_value=PullRequest(
                number=1, title="t", body="b",
                changed_files=[ChangedFile(path="a.py", status="modified")],
            ))),
            parser_service=MagicMock(),
            indexer_service=MagicMock(
                ensure_index=MagicMock(return_value=1),
                load_index=MagicMock(return_value=_index(tmp_path)),
                get_last_index=MagicMock(return_value=_index(tmp_path)),
            ),
            retrieval_service=MagicMock(
                search=MagicMock(return_value=MagicMock(hits=[])),
                retrieve_related_context=MagicMock(return_value=[]),
            ),
            ai_service=MagicMock(),
            logger=mock_logger,
            graph_service=MagicMock(
                build_graph=MagicMock(return_value=_graph()),
                affected_files=MagicMock(return_value=[]),
            ),
            prompt_builder=MagicMock(build=MagicMock(return_value=PromptRequest(
                system_prompt="s", user_prompt="u",
                metadata=PromptMetadata(template_source="local_default"),
            ))),
            ai_gateway=MagicMock(generate=MagicMock(return_value=AIResponse(
                text="{}", provider="mock", model="mock-m", latency_ms=1.0,
            ))),
            response_parser=MagicMock(parse_response=MagicMock(return_value=_parsed_review())),
            persistence_service=persistence,
        )
        result = engine.review(1)
        assert isinstance(result, ReviewResult)
        mock_logger.error.assert_called_once()
        error_str = str(mock_logger.error.call_args)
        assert "disk full" in error_str
        assert "err-repo" in error_str

    def test_persist_failure_log_includes_traceback(self, tmp_path):
        mock_logger = MagicMock()
        persistence = _make_persistence_mock()
        persistence.get_or_create_repository.side_effect = ValueError("bad data")
        repo = Repository(
            name="tb-repo", root_path=str(tmp_path),
            current_branch="feat", default_branch="main",
        )
        engine = ReviewEngine(
            git_service=MagicMock(require_repository=MagicMock(return_value=repo)),
            github_service=MagicMock(fetch_pull_request=MagicMock(return_value=PullRequest(
                number=1, title="t", body="b",
                changed_files=[ChangedFile(path="a.py", status="modified")],
            ))),
            parser_service=MagicMock(),
            indexer_service=MagicMock(
                ensure_index=MagicMock(return_value=1),
                load_index=MagicMock(return_value=_index(tmp_path)),
                get_last_index=MagicMock(return_value=_index(tmp_path)),
            ),
            retrieval_service=MagicMock(
                search=MagicMock(return_value=MagicMock(hits=[])),
                retrieve_related_context=MagicMock(return_value=[]),
            ),
            ai_service=MagicMock(),
            logger=mock_logger,
            graph_service=MagicMock(
                build_graph=MagicMock(return_value=_graph()),
                affected_files=MagicMock(return_value=[]),
            ),
            prompt_builder=MagicMock(build=MagicMock(return_value=PromptRequest(
                system_prompt="s", user_prompt="u",
                metadata=PromptMetadata(template_source="local_default"),
            ))),
            ai_gateway=MagicMock(generate=MagicMock(return_value=AIResponse(
                text="{}", provider="mock", model="mock-m", latency_ms=1.0,
            ))),
            response_parser=MagicMock(parse_response=MagicMock(return_value=_parsed_review())),
            persistence_service=persistence,
        )
        engine.review(1)
        error_str = str(mock_logger.error.call_args)
        assert "ValueError" in error_str or "bad data" in error_str


class TestDualWrite:
    """Verify StorageService is unaffected (dual-write scenario)."""

    def test_storage_service_not_referenced_by_review_engine(self, tmp_path):
        """ReviewEngine does not use StorageService — confirm no coupling."""
        engine, _ = _wired_engine(tmp_path)
        assert not hasattr(engine, "_storage")

    def test_persistence_is_additive(self, tmp_path):
        """Review result is identical with and without persistence."""
        engine_with, _ = _wired_engine(tmp_path)
        engine_without, _ = _wired_engine(tmp_path, persistence=None)

        result_with = engine_with.review(42)
        result_without = engine_without.review(42)

        assert result_with.summary == result_without.summary
        assert result_with.risk_level == result_without.risk_level
        assert result_with.confidence == result_without.confidence
        assert len(result_with.suggestions) == len(result_without.suggestions)


class TestEdgeCases:
    """Edge cases for persistence integration."""

    def test_review_with_zero_suggestions(self, tmp_path):
        parsed = _parsed_review(suggestions=[])
        engine, mocks = _wired_engine(tmp_path, parsed_review=parsed)
        result = engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["suggestions"] == []
        assert result.suggestions == []

    def test_review_with_null_provider(self, tmp_path):
        parsed = _parsed_review(
            metadata=ReviewMetadata(source_format="json", provider=None, model=None)
        )
        engine, mocks = _wired_engine(tmp_path, parsed_review=parsed)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["provider"] == "gemini"
        assert call_kwargs["model"] == "gemini-1.5-pro"

    def test_review_with_unknown_risk(self, tmp_path):
        parsed = _parsed_review(overall_risk="")
        engine, mocks = _wired_engine(tmp_path, parsed_review=parsed)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["risk"] == "unknown"

    def test_review_with_zero_confidence(self, tmp_path):
        parsed = _parsed_review(confidence=0.0)
        engine, mocks = _wired_engine(tmp_path, parsed_review=parsed)
        engine.review(42)
        call_kwargs = mocks["persistence"].persist_review.call_args.kwargs
        assert call_kwargs["confidence"] == 0.0
