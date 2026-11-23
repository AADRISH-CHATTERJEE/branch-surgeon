"""Review suggestion lifecycle + recommendation synchronization."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from refactory.db.base import Base
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.db.session import SessionFactory
from refactory.recommendation.stats import RecommendationStatsService
from refactory.review.suggestion_status import (
    ReviewSuggestionStatusService,
    suggestion_matches_recommendation,
)


@pytest.fixture()
def persistence():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    factory = SessionFactory(eng)
    svc = PersistenceService(factory, logger=MagicMock())
    yield svc
    eng.dispose()


def _logger():
    from loguru import logger

    return logger


class TestSuggestionMatching:
    def test_title_match(self):
        assert suggestion_matches_recommendation(
            {"title": "Security risk in auth.py", "file": "auth.py"},
            {"title": "Security risk in auth.py", "type": "security"},
        )

    def test_file_and_category_match(self):
        assert suggestion_matches_recommendation(
            {
                "title": "Missing auth check",
                "file": "src/auth.py",
                "category": "security",
            },
            {
                "title": "Harden login",
                "description": "See src/auth.py for details",
                "type": "security",
            },
        )


class TestSuggestionStatusService:
    def test_resolve_syncs_matching_recommendation(self, persistence: PersistenceService):
        repo = persistence.get_or_create_repository(
            name="demo", root_path="/tmp/review-sug"
        )
        rid = repo["id"]
        persistence.persist_recommendations(
            rid,
            [
                {
                    "id": "R-SEC1",
                    "type": "security",
                    "priority": "critical",
                    "title": "Security risk in auth.py",
                    "status": "pending",
                }
            ],
        )
        review = persistence.persist_review(
            repository_id=rid,
            pr_number=1,
            summary="test",
            suggestions=[
                {
                    "file": "auth.py",
                    "line": 10,
                    "severity": "critical",
                    "category": "security",
                    "title": "Security risk in auth.py",
                    "explanation": "xss",
                }
            ],
        )
        query = RepositoryQueryService(persistence._sf)
        suggestions = query.get_review_suggestions(review["id"])
        assert len(suggestions) == 1
        sid = suggestions[0]["id"]
        assert suggestions[0]["status"] == "pending"

        stats = RecommendationStatsService(
            _logger(), query, persistence_service=persistence
        )
        svc = ReviewSuggestionStatusService(
            _logger(),
            query_service=query,
            persistence_service=persistence,
            recommendation_stats_service=stats,
        )
        outcome = svc.update_status(
            review_id=review["id"],
            suggestion_id=sid,
            status="resolved",
            repository_id=rid,
        )
        assert outcome["suggestion"]["status"] == "resolved"
        assert outcome["suggestion"]["resolved_at"] is not None
        assert "R-SEC1" in outcome["synced_recommendation_ids"]

        rec = query.get_recommendation("R-SEC1")
        assert rec is not None
        assert rec["status"] == "resolved"
        summary = stats.get_repository_summary(
            repo_root="/tmp/review-sug", repository_id=rid, force_refresh=True
        )
        # Severity tiles are pending-only; resolved critical drops out.
        assert summary.critical == 0
        assert summary.pending == 0
        assert summary.resolved == 1

    def test_ignore_syncs_recommendation(self, persistence: PersistenceService):
        repo = persistence.get_or_create_repository(
            name="demo2", root_path="/tmp/review-ignore"
        )
        rid = repo["id"]
        persistence.persist_recommendations(
            rid,
            [
                {
                    "id": "R-T1",
                    "type": "testing",
                    "priority": "medium",
                    "title": "Missing tests for foo.py",
                    "status": "pending",
                }
            ],
        )
        review = persistence.persist_review(
            repository_id=rid,
            suggestions=[
                {
                    "file": "foo.py",
                    "category": "testing",
                    "title": "Missing tests for foo.py",
                }
            ],
        )
        query = RepositoryQueryService(persistence._sf)
        sid = query.get_review_suggestions(review["id"])[0]["id"]
        stats = RecommendationStatsService(
            _logger(), query, persistence_service=persistence
        )
        svc = ReviewSuggestionStatusService(
            _logger(),
            query_service=query,
            persistence_service=persistence,
            recommendation_stats_service=stats,
        )
        outcome = svc.update_status(
            review_id=review["id"],
            suggestion_id=sid,
            status="ignored",
            repository_id=rid,
        )
        assert outcome["suggestion"]["status"] == "ignored"
        assert outcome["suggestion"]["ignored_at"] is not None
        rec = query.get_recommendation("R-T1")
        assert rec["status"] == "ignored"

    def test_auto_resolve_when_recommendation_gone(
        self, persistence: PersistenceService
    ):
        repo = persistence.get_or_create_repository(
            name="demo3", root_path="/tmp/review-auto"
        )
        rid = repo["id"]
        review = persistence.persist_review(
            repository_id=rid,
            suggestions=[
                {
                    "file": "old.py",
                    "category": "security",
                    "title": "Gone finding",
                }
            ],
        )
        query = RepositoryQueryService(persistence._sf)
        sid = query.get_review_suggestions(review["id"])[0]["id"]
        stats = RecommendationStatsService(
            _logger(), query, persistence_service=persistence
        )
        svc = ReviewSuggestionStatusService(
            _logger(),
            query_service=query,
            persistence_service=persistence,
            recommendation_stats_service=stats,
        )
        result = svc.auto_resolve_for_repository(rid)
        assert result["resolved"] == 1
        row = persistence.get_review_suggestion(sid)
        assert row is not None
        assert row["status"] == "resolved"

    def test_resolve_via_pr_number_lookup(self, persistence: PersistenceService):
        """UI often opens reviews by PR number; PATCH must still find suggestions."""
        repo = persistence.get_or_create_repository(
            name="demo-pr", root_path="/tmp/review-pr"
        )
        rid = repo["id"]
        review = persistence.persist_review(
            repository_id=rid,
            pr_number=42,
            suggestions=[
                {
                    "file": "x.py",
                    "category": "security",
                    "title": "PR lookup finding",
                }
            ],
        )
        query = RepositoryQueryService(persistence._sf)
        sid = query.get_review_suggestions(review["id"])[0]["id"]
        svc = ReviewSuggestionStatusService(
            _logger(),
            query_service=query,
            persistence_service=persistence,
        )
        outcome = svc.update_status(
            review_id="42",
            suggestion_id=sid,
            status="resolved",
            repository_id=rid,
            sync_recommendations=False,
        )
        assert outcome["review_id"] == review["id"]
        assert outcome["suggestion"]["status"] == "resolved"
        assert outcome["suggestion"]["created_at"] is not None

    def test_suggestion_lifecycle_fields_persisted(
        self, persistence: PersistenceService
    ):
        repo = persistence.get_or_create_repository(
            name="demo-fields", root_path="/tmp/review-fields"
        )
        review = persistence.persist_review(
            repository_id=repo["id"],
            suggestions=[{"file": "a.py", "title": "t", "category": "style"}],
        )
        query = RepositoryQueryService(persistence._sf)
        row = query.get_review_suggestions(review["id"])[0]
        for key in (
            "id",
            "status",
            "created_at",
            "updated_at",
            "resolved_at",
            "ignored_at",
            "updated_by",
        ):
            assert key in row
        assert row["status"] == "pending"
        assert row["created_at"] is not None
