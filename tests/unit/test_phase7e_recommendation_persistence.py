"""Phase 7e — Normalized recommendation persistence tests.

Verifies that RecommendationEngine._persist_recommendations() writes
individual recommendation rows to db_recommendations via
PersistenceService.persist_recommendations(), while preserving the
existing analysis snapshot in db_analysis_runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from refactory.db.base import Base
from refactory.db.models import RepositoryModel
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.recommendation.models import (
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationReport,
)
from refactory.recommendation.service import RecommendationEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_storage():
    storage = MagicMock()
    storage.get_analyses.return_value = []
    storage.store_analysis.return_value = "id"
    storage.store_metric.return_value = None
    storage.get_metrics.return_value = []
    return storage


def _make_engine(
    storage=None, persistence=None, query_service=None
) -> RecommendationEngine:
    storage = storage or _mock_storage()
    return RecommendationEngine(
        logger=MagicMock(),
        parser_service=MagicMock(),
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        impact_service=MagicMock(),
        rule_engine=MagicMock(),
        policy_service=MagicMock(),
        storage_service=storage,
        ai_gateway=MagicMock(),
        prompt_service=MagicMock(),
        query_service=query_service,
        persistence_service=persistence,
    )


@pytest.fixture()
def engine_db():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine_db):
    return sessionmaker(bind=engine_db, expire_on_commit=False)


@pytest.fixture()
def persistence(session_factory) -> PersistenceService:
    return PersistenceService(session_factory)


@pytest.fixture()
def query_service(session_factory) -> RepositoryQueryService:
    return RepositoryQueryService(session_factory)


@pytest.fixture()
def repo_id(session_factory) -> str:
    sess = session_factory()
    repo = RepositoryModel(
        id=uuid.uuid4().hex[:36],
        name="test-repo",
        root_path=str(Path("/tmp/test-repo")),
        default_branch="main",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    sess.add(repo)
    sess.commit()
    rid = repo.id
    sess.close()
    return rid


def _sample_recommendations(n: int = 3) -> list[Recommendation]:
    categories = list(RecommendationCategory)
    priorities = list(RecommendationPriority)
    return [
        Recommendation(
            title=f"Recommendation {i}",
            description=f"Description for recommendation {i}",
            category=categories[i % len(categories)],
            priority=priorities[i % len(priorities)],
            score=float(10 - i),
        )
        for i in range(n)
    ]


def _sample_report(n: int = 3) -> RecommendationReport:
    recs = _sample_recommendations(n)
    return RecommendationReport(
        recommendations=recs,
        total_recommendations=len(recs),
    )


# ===========================================================================
# Recommendation Row Persistence
# ===========================================================================


class TestRecommendationRowPersistence:
    """Verify individual recommendation rows land in db_recommendations."""

    def test_n_recommendations_produce_n_rows(
        self, persistence, query_service, repo_id
    ):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(5)
        root = Path("/tmp/test-repo")

        engine._persist_recommendations(root, report, 100.0)

        recs = persistence.get_recommendations(repo_id)
        assert len(recs) == 5

    def test_single_recommendation(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(1)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 10.0)

        recs = persistence.get_recommendations(repo_id)
        assert len(recs) == 1

    def test_twelve_recommendations(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(12)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 50.0)

        recs = persistence.get_recommendations(repo_id)
        assert len(recs) == 12

    def test_zero_recommendations_no_rows(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(0)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 10.0)

        recs = persistence.get_recommendations(repo_id)
        assert len(recs) == 0


# ===========================================================================
# Field Mapping
# ===========================================================================


class TestFieldMapping:
    """Verify every persisted row contains the correct mapped fields."""

    def test_category_maps_to_type(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        recs = [
            Recommendation(
                title="Security fix",
                description="Fix vulnerability",
                category=RecommendationCategory.SECURITY,
                priority=RecommendationPriority.CRITICAL,
            ),
        ]
        report = RecommendationReport(
            recommendations=recs, total_recommendations=1
        )

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        rows = persistence.get_recommendations(repo_id)
        assert rows[0]["type"] == "security"

    def test_priority_preserved(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        recs = [
            Recommendation(
                title="High priority",
                priority=RecommendationPriority.HIGH,
            ),
        ]
        report = RecommendationReport(
            recommendations=recs, total_recommendations=1
        )

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        rows = persistence.get_recommendations(repo_id)
        assert rows[0]["priority"] == "high"

    def test_title_and_description(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        recs = [
            Recommendation(
                title="Extract helper method",
                description="The calculate() function is 200 lines long",
            ),
        ]
        report = RecommendationReport(
            recommendations=recs, total_recommendations=1
        )

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        rows = persistence.get_recommendations(repo_id)
        assert rows[0]["title"] == "Extract helper method"
        assert rows[0]["description"] == "The calculate() function is 200 lines long"

    def test_status_always_pending(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(3)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        rows = persistence.get_recommendations(repo_id)
        assert all(r["status"] == "pending" for r in rows)

    def test_repository_id_correct(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(2)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        rows = persistence.get_recommendations(repo_id)
        assert all(r["repository_id"] == repo_id for r in rows)

    def test_all_fields_present(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        recs = [
            Recommendation(
                title="Add unit tests",
                description="Coverage is below 50%",
                category=RecommendationCategory.TESTING,
                priority=RecommendationPriority.HIGH,
            ),
        ]
        report = RecommendationReport(
            recommendations=recs, total_recommendations=1
        )

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        row = persistence.get_recommendations(repo_id)[0]
        assert row["type"] == "testing"
        assert row["priority"] == "high"
        assert row["title"] == "Add unit tests"
        assert row["description"] == "Coverage is below 50%"
        assert row["status"] == "pending"
        assert row["repository_id"] == repo_id
        assert "id" in row
        assert "created_at" in row

    def test_multiple_categories_mapped(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        recs = [
            Recommendation(title="A", category=RecommendationCategory.SECURITY),
            Recommendation(title="B", category=RecommendationCategory.PERFORMANCE),
            Recommendation(title="C", category=RecommendationCategory.ARCHITECTURE),
        ]
        report = RecommendationReport(
            recommendations=recs, total_recommendations=3
        )

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        rows = persistence.get_recommendations(repo_id)
        types = {r["type"] for r in rows}
        assert types == {"security", "performance", "architecture"}


# ===========================================================================
# Repository Resolution
# ===========================================================================


class TestRepositoryResolution:
    """Verify recommendations are linked to the correct repository."""

    def test_linked_to_existing_repo(self, persistence, repo_id):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(2)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        rows = persistence.get_recommendations(repo_id)
        assert len(rows) == 2
        assert all(r["repository_id"] == repo_id for r in rows)

    def test_creates_repo_if_missing(self, persistence):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(1)

        engine._persist_recommendations(Path("/tmp/new-repo"), report, 1.0)

        repos = persistence.list_repositories()
        new_repo = [r for r in repos if r["root_path"] == str(Path("/tmp/new-repo"))]
        assert len(new_repo) == 1
        recs = persistence.get_recommendations(new_repo[0]["id"])
        assert len(recs) == 1


# ===========================================================================
# Backward Compatibility
# ===========================================================================


class TestBackwardCompatibility:
    """Verify graceful behavior when PersistenceService is unavailable."""

    def test_no_persistence_no_error(self):
        storage = _mock_storage()
        engine = _make_engine(storage=storage, persistence=None)
        report = _sample_report(3)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 10.0)

        storage.store_analysis.assert_called_once()
        storage.store_metric.assert_called_once()

    def test_persistence_error_still_saves_analysis(
        self, persistence, query_service, repo_id
    ):
        broken = MagicMock()
        broken.get_or_create_repository.return_value = {"id": repo_id}
        broken.persist_analysis_run.return_value = {"id": "a1"}
        broken.persist_metric.return_value = {"id": "m1"}
        broken.persist_recommendations.side_effect = RuntimeError("DB error")
        engine = _make_engine(persistence=broken)

        report = _sample_report(3)
        engine._persist_recommendations(Path("/tmp/test-repo"), report, 10.0)

        broken.persist_analysis_run.assert_called_once()
        broken.persist_metric.assert_called_once()
        broken.persist_recommendations.assert_called_once()

    def test_repo_resolution_error_skips_recs_silently(self):
        broken = MagicMock()
        broken.get_or_create_repository.side_effect = [
            {"id": "r1"},
            {"id": "r1"},
            RuntimeError("oops"),
        ]
        broken.persist_analysis_run.return_value = {"id": "a1"}
        broken.persist_metric.return_value = {"id": "m1"}
        engine = _make_engine(persistence=broken)

        report = _sample_report(2)
        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)

        broken.persist_analysis_run.assert_called_once()


# ===========================================================================
# Analysis Preservation
# ===========================================================================


class TestAnalysisPreservation:
    """Verify db_analysis_runs still receives the complete JSON report."""

    def test_analysis_run_still_created(
        self, persistence, query_service, repo_id
    ):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(5)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 77.0)

        runs = query_service.get_analyses(repo_id, command="recommend")
        assert len(runs) == 1
        assert runs[0]["result_type"] == "recommendations"
        assert runs[0]["duration_ms"] == pytest.approx(77.0, abs=0.1)

    def test_analysis_result_data_contains_all_recommendations(
        self, persistence, query_service, repo_id
    ):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(4)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 10.0)

        runs = query_service.get_analyses(repo_id, command="recommend")
        data = runs[0]["result_data"]
        assert data["total_recommendations"] == 4
        assert len(data["recommendations"]) == 4

    def test_metric_still_created(self, persistence, query_service, repo_id):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(7)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 10.0)

        metrics = query_service.get_metrics(
            repo_id, metric_name="recommendation_count"
        )
        assert len(metrics) == 1
        assert metrics[0]["metric_value"] == pytest.approx(7.0)

    def test_both_analysis_and_rows_created(
        self, persistence, query_service, repo_id
    ):
        engine = _make_engine(persistence=persistence)
        report = _sample_report(3)

        engine._persist_recommendations(Path("/tmp/test-repo"), report, 50.0)

        runs = query_service.get_analyses(repo_id, command="recommend")
        assert len(runs) == 1

        recs = persistence.get_recommendations(repo_id)
        assert len(recs) == 3

        metrics = query_service.get_metrics(
            repo_id, metric_name="recommendation_count"
        )
        assert len(metrics) == 1
