"""Phase 7b — Migration tests for RecommendationEngine read path.

Verifies that RecommendationEngine produces identical results when reading
from RepositoryQueryService versus StorageService for trend analysis.
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
from refactory.db.models import MetricModel, RepositoryModel
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.recommendation.service import RecommendationEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_services():
    """Create standard mock services for RecommendationEngine."""
    storage = MagicMock()
    storage.get_metrics.return_value = []
    storage.store_analysis.return_value = "id"
    storage.store_metric.return_value = None
    rules = MagicMock()
    rules.load_rules.return_value = 0
    result = MagicMock()
    result.violations = []
    rules.evaluate.return_value = result
    policy = MagicMock()
    policy.policy = None
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "AI"
    ai.generate.return_value = resp
    return {
        "parser_service": MagicMock(),
        "indexer_service": MagicMock(),
        "graph_service": MagicMock(),
        "impact_service": MagicMock(),
        "rule_engine": rules,
        "policy_service": policy,
        "storage_service": storage,
        "ai_gateway": ai,
        "prompt_service": MagicMock(),
    }


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def repo_id(session_factory) -> str:
    """Create a repository at /tmp/test-repo and return its ID."""
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


@pytest.fixture()
def persistence(session_factory) -> PersistenceService:
    return PersistenceService(session_factory)


@pytest.fixture()
def query_service(session_factory) -> RepositoryQueryService:
    return RepositoryQueryService(session_factory)


def _engine_with_query(query_service, storage_mock=None):
    """Create engine wired to both query_service and storage mock."""
    from loguru import logger
    mocks = _mock_services()
    if storage_mock:
        mocks["storage_service"] = storage_mock
    return RecommendationEngine(
        logger=logger, **mocks, query_service=query_service,
    )


def _engine_with_storage(storage_mock):
    """Create engine wired only to storage (no query_service)."""
    from loguru import logger
    mocks = _mock_services()
    mocks["storage_service"] = storage_mock
    return RecommendationEngine(logger=logger, **mocks)


def _engine_without_query():
    """Create engine without query_service (backward compat)."""
    from loguru import logger
    mocks = _mock_services()
    return RecommendationEngine(logger=logger, **mocks)


# ===========================================================================
# Backward Compatibility Tests
# ===========================================================================


class TestBackwardCompatibility:
    """Verify RecommendationEngine works identically without query_service."""

    def test_no_query_service_uses_storage(self):
        storage = MagicMock()
        storage.get_metrics.return_value = [{"value": 90}, {"value": 80}]
        storage.store_analysis.return_value = "id"
        storage.store_metric.return_value = None
        engine = _engine_with_storage(storage)
        report = engine.analyze_trends(Path("/tmp/test-repo"))
        assert len(report.trends) >= 1
        assert storage.get_metrics.called

    def test_no_query_service_empty_data(self):
        engine = _engine_without_query()
        report = engine.analyze_trends(Path("/tmp/test-repo"))
        assert report.trends == []

    def test_constructor_without_query_service(self):
        from loguru import logger
        mocks = _mock_services()
        engine = RecommendationEngine(logger=logger, **mocks)
        assert engine._query is None

    def test_constructor_with_query_service(self, query_service):
        from loguru import logger
        mocks = _mock_services()
        engine = RecommendationEngine(logger=logger, **mocks, query_service=query_service)
        assert engine._query is query_service


# ===========================================================================
# Migration Equivalence Tests
# ===========================================================================


class TestMigrationEquivalence:
    """Verify that QueryService produces identical results to StorageService."""

    def test_identical_trend_improving(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=80.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=90.0,
        )
        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))

        storage_mock = MagicMock()
        storage_mock.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 90}, {"value": 80}] if name == "health_overall" else []
        )
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine_st = _engine_with_storage(storage_mock)
        report_st = engine_st.analyze_trends(Path("/tmp/test-repo"))

        assert len(report_qs.trends) == len(report_st.trends)
        for tqs, tst in zip(report_qs.trends, report_st.trends):
            assert tqs.metric_name == tst.metric_name
            assert tqs.direction == tst.direction
            assert tqs.change_percent == tst.change_percent

    def test_identical_trend_degrading(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_security",
            metric_value=80.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_security",
            metric_value=60.0,
        )
        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))

        storage_mock = MagicMock()
        storage_mock.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 60}, {"value": 80}] if name == "health_security" else []
        )
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine_st = _engine_with_storage(storage_mock)
        report_st = engine_st.analyze_trends(Path("/tmp/test-repo"))

        assert report_qs.trends[0].direction == report_st.trends[0].direction == "degrading"
        assert report_qs.trends[0].change_percent == report_st.trends[0].change_percent

    def test_identical_trend_stable(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=80.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=80.0,
        )
        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))

        storage_mock = MagicMock()
        storage_mock.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 80}, {"value": 80}] if name == "health_overall" else []
        )
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine_st = _engine_with_storage(storage_mock)
        report_st = engine_st.analyze_trends(Path("/tmp/test-repo"))

        assert report_qs.trends[0].direction == report_st.trends[0].direction == "stable"

    def test_identical_debt_metric_trend(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="tech_debt_score",
            metric_value=30.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="tech_debt_score",
            metric_value=50.0,
        )
        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))

        storage_mock = MagicMock()
        storage_mock.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 50}, {"value": 30}] if name == "tech_debt_score" else []
        )
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine_st = _engine_with_storage(storage_mock)
        report_st = engine_st.analyze_trends(Path("/tmp/test-repo"))

        assert report_qs.trends[0].direction == report_st.trends[0].direction == "increasing"

    def test_identical_transformations_trend(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="transformations_applied",
            metric_value=2.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="transformations_applied",
            metric_value=3.0,
        )
        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))

        storage_mock = MagicMock()
        storage_mock.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 3}, {"value": 2}] if name == "transformations_applied" else []
        )
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine_st = _engine_with_storage(storage_mock)
        report_st = engine_st.analyze_trends(Path("/tmp/test-repo"))

        qs_tf = next(t for t in report_qs.trends if t.metric_name == "transformations_applied")
        st_tf = next(t for t in report_st.trends if t.metric_name == "transformations_applied")
        assert qs_tf.change_percent == st_tf.change_percent == 5.0
        assert qs_tf.direction == st_tf.direction == "active"

    def test_identical_multi_dimension(self, persistence, query_service, repo_id):
        metrics = [
            ("health_overall", [80.0, 90.0]),
            ("health_security", [70.0, 95.0]),
            ("health_testing", [80.0, 60.0]),
        ]
        for name, values in metrics:
            for v in values:
                persistence.persist_metric(
                    repository_id=repo_id, metric_name=name, metric_value=v,
                )

        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))

        def storage_side_effect(path, name, **kw):
            mapping = {
                "health_overall": [{"value": 90}, {"value": 80}],
                "health_security": [{"value": 95}, {"value": 70}],
                "health_testing": [{"value": 60}, {"value": 80}],
            }
            return mapping.get(name, [])

        storage_mock = MagicMock()
        storage_mock.get_metrics.side_effect = storage_side_effect
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine_st = _engine_with_storage(storage_mock)
        report_st = engine_st.analyze_trends(Path("/tmp/test-repo"))

        assert len(report_qs.trends) == len(report_st.trends)
        for tqs, tst in zip(
            sorted(report_qs.trends, key=lambda t: t.metric_name),
            sorted(report_st.trends, key=lambda t: t.metric_name),
        ):
            assert tqs.direction == tst.direction
            assert tqs.change_percent == tst.change_percent

    def test_modules_degrading_identical(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_security",
            metric_value=80.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_security",
            metric_value=60.0,
        )
        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))
        assert "Security" in report_qs.modules_degrading

    def test_modules_improving_identical(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_testing",
            metric_value=70.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_testing",
            metric_value=90.0,
        )
        engine_qs = _engine_with_query(query_service)
        report_qs = engine_qs.analyze_trends(Path("/tmp/test-repo"))
        assert "Testing" in report_qs.modules_improving


# ===========================================================================
# QueryService Read Path Tests
# ===========================================================================


class TestQueryServiceReadPath:
    """Verify the RepositoryQueryService-based read path directly."""

    def test_read_metrics_returns_value_key(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=85.0, git_commit="a" * 40, branch="main",
        )
        engine = _engine_with_query(query_service)
        data = engine._read_metrics(str(Path("/tmp/test-repo")), "health_overall")
        assert len(data) == 1
        assert data[0]["value"] == 85.0
        assert data[0]["git_commit"] == "a" * 40
        assert data[0]["branch"] == "main"
        assert data[0]["timestamp"] is not None

    def test_read_metrics_empty_repo(self, query_service):
        engine = _engine_with_query(query_service)
        data = engine._read_metrics(str(Path("/nonexistent/repo")), "health_overall")
        assert data == []

    def test_read_metrics_no_matching_metric(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=80.0,
        )
        engine = _engine_with_query(query_service)
        data = engine._read_metrics(str(Path("/tmp/test-repo")), "nonexistent_metric")
        assert data == []

    def test_read_metrics_ordering(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=90.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=80.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=70.0,
        )
        engine = _engine_with_query(query_service)
        data = engine._read_metrics(str(Path("/tmp/test-repo")), "health_overall")
        assert len(data) == 3
        assert data[0]["value"] == 70.0
        assert data[2]["value"] == 90.0

    def test_read_metrics_limit(self, persistence, query_service, repo_id):
        for i in range(10):
            persistence.persist_metric(
                repository_id=repo_id, metric_name="health_overall",
                metric_value=float(i * 10),
            )
        engine = _engine_with_query(query_service)
        data = engine._read_metrics(str(Path("/tmp/test-repo")), "health_overall", limit=5)
        assert len(data) == 5

    def test_read_metrics_fallback_on_query_failure(self):
        bad_query = MagicMock()
        bad_query.get_repository_by_root.side_effect = RuntimeError("db error")
        storage_mock = MagicMock()
        storage_mock.get_metrics.return_value = [{"value": 42}]
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine = _engine_with_query(bad_query, storage_mock)
        data = engine._read_metrics(str(Path("/tmp/test-repo")), "health_overall")
        assert data == [{"value": 42}]
        assert storage_mock.get_metrics.called


# ===========================================================================
# Missing Data Behavior Tests
# ===========================================================================


class TestMissingDataBehavior:
    """Verify behavior with missing or insufficient data."""

    def test_single_data_point_no_trend(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=80.0,
        )
        engine = _engine_with_query(query_service)
        report = engine.analyze_trends(Path("/tmp/test-repo"))
        assert len(report.trends) == 0

    def test_no_data_no_trend(self, query_service):
        engine = _engine_with_query(query_service)
        report = engine.analyze_trends(Path("/tmp/test-repo"))
        assert report.trends == []
        assert report.modules_degrading == []
        assert report.modules_improving == []

    def test_repository_not_in_query_service(self, query_service):
        engine = _engine_with_query(query_service)
        report = engine.analyze_trends(Path("/tmp/nonexistent-repo"))
        assert report.trends == []

    def test_partial_metrics_only_populated_trends(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=80.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=90.0,
        )
        engine = _engine_with_query(query_service)
        report = engine.analyze_trends(Path("/tmp/test-repo"))
        assert len(report.trends) == 1
        assert report.trends[0].metric_name == "health_overall"


# ===========================================================================
# Write Path Unchanged Tests
# ===========================================================================


class TestWritePathUnchanged:
    """Verify that writes still go through StorageService."""

    def test_persist_recommendations_uses_storage(self, query_service):
        storage_mock = MagicMock()
        storage_mock.get_metrics.return_value = []
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine = _engine_with_query(query_service, storage_mock)
        report = engine.generate_recommendations(Path("/tmp/test-repo"))
        assert storage_mock.store_analysis.called
        assert storage_mock.store_metric.called

    def test_health_calculation_writes_to_storage(self, query_service):
        storage_mock = MagicMock()
        storage_mock.get_metrics.return_value = []
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine = _engine_with_query(query_service, storage_mock)
        engine.calculate_health(Path("/tmp/test-repo"))
        assert storage_mock.store_metric.called

    def test_technical_debt_writes_to_storage(self, query_service, tmp_path):
        storage_mock = MagicMock()
        storage_mock.get_metrics.return_value = []
        storage_mock.store_analysis.return_value = "id"
        storage_mock.store_metric.return_value = None
        engine = _engine_with_query(query_service, storage_mock)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "small.py").write_text("x = 1\n")
        engine.analyze_technical_debt(repo)
        assert storage_mock.store_metric.called


# ===========================================================================
# Numerical Precision Tests
# ===========================================================================


class TestNumericalPrecision:
    """Verify trend calculations are numerically identical."""

    def test_percentage_calculation(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=75.0,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="health_overall",
            metric_value=95.0,
        )
        engine = _engine_with_query(query_service)
        report = engine.analyze_trends(Path("/tmp/test-repo"))
        trend = report.trends[0]
        expected_change = ((95.0 - 75.0) / max(75.0, 0.01)) * 100
        assert trend.change_percent == round(expected_change, 1)

    def test_near_zero_denominator(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="tech_debt_score",
            metric_value=0.001,
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="tech_debt_score",
            metric_value=5.0,
        )
        engine = _engine_with_query(query_service)
        report = engine.analyze_trends(Path("/tmp/test-repo"))
        assert len(report.trends) == 1
        assert report.trends[0].change_percent is not None
