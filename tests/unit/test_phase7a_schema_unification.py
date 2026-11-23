"""Comprehensive tests for Phase 7a — MetricModel, AnalysisRunModel, and their
repositories, PersistenceService extensions, and RepositoryQueryService extensions.

Uses real SQLite databases for integration testing (same pattern as test_query_service.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from refactory.db.base import Base
from refactory.db.models import (
    AnalysisRunModel,
    MetricModel,
    RepositoryModel,
)
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.db.repositories.analysis_run import AnalysisRunRepository
from refactory.db.repositories.metric import MetricRepository
from refactory.db.uow import UnitOfWork


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory


@pytest.fixture()
def session(session_factory) -> Session:
    sess = session_factory()
    yield sess
    sess.close()


@pytest.fixture()
def repo_id(session) -> str:
    """Create a repository and return its ID."""
    repo = RepositoryModel(
        id=uuid.uuid4().hex[:36],
        name="test-repo",
        root_path="/tmp/test-repo",
        default_branch="main",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(repo)
    session.commit()
    return repo.id


@pytest.fixture()
def persistence(session_factory) -> PersistenceService:
    return PersistenceService(session_factory)


@pytest.fixture()
def query_service(session_factory) -> RepositoryQueryService:
    return RepositoryQueryService(session_factory)


# ===========================================================================
# MetricModel ORM Tests
# ===========================================================================


class TestMetricModel:
    def test_create_metric(self, session, repo_id):
        m = MetricModel(
            repository_id=repo_id,
            metric_name="complexity",
            metric_value=42.5,
            git_commit="a" * 40,
            branch="main",
            created_at=datetime.now(timezone.utc),
            metadata_={"tool": "radon"},
        )
        session.add(m)
        session.commit()
        assert m.id is not None
        assert len(m.id) == 32

    def test_metric_defaults(self, session, repo_id):
        m = MetricModel(
            repository_id=repo_id,
            metric_name="lines_of_code",
            metric_value=1000.0,
        )
        session.add(m)
        session.commit()
        assert m.git_commit is None
        assert m.branch is None
        assert m.metadata_ is None

    def test_metric_repository_relationship(self, session, repo_id):
        m = MetricModel(
            repository_id=repo_id,
            metric_name="coverage",
            metric_value=85.5,
            created_at=datetime.now(timezone.utc),
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        assert m.repository is not None
        assert m.repository.id == repo_id


# ===========================================================================
# AnalysisRunModel ORM Tests
# ===========================================================================


class TestAnalysisRunModel:
    def test_create_analysis_run(self, session, repo_id):
        r = AnalysisRunModel(
            repository_id=repo_id,
            command="review",
            status="completed",
            git_commit="b" * 40,
            branch="feature-x",
            duration_ms=1234.5,
            result_type="review",
            result_data={"risk": "high"},
            error_message=None,
            created_at=datetime.now(timezone.utc),
            metadata_={"provider": "openai"},
        )
        session.add(r)
        session.commit()
        assert r.id is not None
        assert len(r.id) == 32

    def test_analysis_run_defaults(self, session, repo_id):
        r = AnalysisRunModel(
            repository_id=repo_id,
            command="recommend",
            result_type="recommendations",
            created_at=datetime.now(timezone.utc),
        )
        session.add(r)
        session.commit()
        assert r.status == "completed"
        assert r.duration_ms == 0.0
        assert r.git_commit is None
        assert r.branch is None
        assert r.error_message is None
        assert r.result_data is None

    def test_analysis_run_relationship(self, session, repo_id):
        r = AnalysisRunModel(
            repository_id=repo_id,
            command="transform",
            result_type="transformations",
            created_at=datetime.now(timezone.utc),
        )
        session.add(r)
        session.commit()
        session.refresh(r)
        assert r.repository is not None
        assert r.repository.id == repo_id

    def test_analysis_run_failed_status(self, session, repo_id):
        r = AnalysisRunModel(
            repository_id=repo_id,
            command="review",
            status="failed",
            result_type="review",
            error_message="API timeout",
            created_at=datetime.now(timezone.utc),
        )
        session.add(r)
        session.commit()
        assert r.status == "failed"
        assert r.error_message == "API timeout"


# ===========================================================================
# MetricRepository Tests
# ===========================================================================


class TestMetricRepository:
    def test_list_by_repository(self, session, repo_id):
        repo = MetricRepository(session)
        repo.create(
            repository_id=repo_id,
            metric_name="complexity",
            metric_value=10.0,
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            metric_name="coverage",
            metric_value=80.0,
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_repository(repo_id)
        assert len(results) == 2

    def test_list_by_repository_filtered_by_name(self, session, repo_id):
        repo = MetricRepository(session)
        repo.create(
            repository_id=repo_id,
            metric_name="complexity",
            metric_value=10.0,
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            metric_name="coverage",
            metric_value=80.0,
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_repository(repo_id, metric_name="complexity")
        assert len(results) == 1
        assert results[0].metric_name == "complexity"

    def test_list_by_repository_filtered_by_branch(self, session, repo_id):
        repo = MetricRepository(session)
        repo.create(
            repository_id=repo_id,
            metric_name="loc",
            metric_value=500.0,
            branch="main",
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            metric_name="loc",
            metric_value=600.0,
            branch="develop",
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_repository(repo_id, branch="main")
        assert len(results) == 1
        assert results[0].branch == "main"

    def test_list_by_commit(self, session, repo_id):
        repo = MetricRepository(session)
        commit = "c" * 40
        repo.create(
            repository_id=repo_id,
            metric_name="complexity",
            metric_value=12.0,
            git_commit=commit,
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            metric_name="coverage",
            metric_value=70.0,
            git_commit=commit,
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_commit(repo_id, commit)
        assert len(results) == 2

    def test_list_by_commit_empty(self, session, repo_id):
        repo = MetricRepository(session)
        results = repo.list_by_commit(repo_id, "x" * 40)
        assert results == []

    def test_delete_by_repository(self, session, repo_id):
        repo = MetricRepository(session)
        repo.create(
            repository_id=repo_id,
            metric_name="a",
            metric_value=1.0,
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            metric_name="b",
            metric_value=2.0,
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        count = repo.delete_by_repository(repo_id)
        session.commit()
        assert count == 2
        assert repo.list_by_repository(repo_id) == []

    def test_bulk_insert(self, session, repo_id):
        repo = MetricRepository(session)
        now = datetime.now(timezone.utc)
        data = [
            {"repository_id": repo_id, "metric_name": f"m{i}", "metric_value": float(i), "created_at": now}
            for i in range(5)
        ]
        repo.bulk_insert(data)
        session.commit()
        results = repo.list_by_repository(repo_id)
        assert len(results) == 5


# ===========================================================================
# AnalysisRunRepository Tests
# ===========================================================================


class TestAnalysisRunRepository:
    def test_list_by_repository(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        repo.create(
            repository_id=repo_id,
            command="review",
            result_type="review",
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            command="recommend",
            result_type="recommendations",
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_repository(repo_id)
        assert len(results) == 2

    def test_list_by_repository_filtered_by_command(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        repo.create(
            repository_id=repo_id,
            command="review",
            result_type="review",
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            command="recommend",
            result_type="recommendations",
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_repository(repo_id, command="review")
        assert len(results) == 1
        assert results[0].command == "review"

    def test_list_by_repository_filtered_by_status(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        repo.create(
            repository_id=repo_id,
            command="review",
            status="completed",
            result_type="review",
            created_at=datetime.now(timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            command="review",
            status="failed",
            result_type="review",
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_repository(repo_id, status="failed")
        assert len(results) == 1
        assert results[0].status == "failed"

    def test_get_latest(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        repo.create(
            repository_id=repo_id,
            command="review",
            result_type="review",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            command="review",
            result_type="review",
            created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        session.commit()
        latest = repo.get_latest(repo_id)
        assert latest is not None
        assert latest.created_at.year == 2026
        assert latest.created_at.month == 7

    def test_get_latest_with_command_filter(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        repo.create(
            repository_id=repo_id,
            command="review",
            result_type="review",
            created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        repo.create(
            repository_id=repo_id,
            command="recommend",
            result_type="recommendations",
            created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
        )
        session.commit()
        latest = repo.get_latest(repo_id, command="review")
        assert latest is not None
        assert latest.command == "review"

    def test_get_latest_empty(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        assert repo.get_latest(repo_id) is None

    def test_list_by_commit(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        commit = "d" * 40
        repo.create(
            repository_id=repo_id,
            command="review",
            result_type="review",
            git_commit=commit,
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        results = repo.list_by_commit(repo_id, commit)
        assert len(results) == 1

    def test_delete_by_repository(self, session, repo_id):
        repo = AnalysisRunRepository(session)
        repo.create(
            repository_id=repo_id,
            command="review",
            result_type="review",
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        count = repo.delete_by_repository(repo_id)
        session.commit()
        assert count == 1
        assert repo.list_by_repository(repo_id) == []


# ===========================================================================
# UnitOfWork Integration Tests
# ===========================================================================


class TestUnitOfWorkExtensions:
    def test_metrics_accessible(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            assert hasattr(uow, "metrics")
            assert isinstance(uow.metrics, MetricRepository)

    def test_analysis_runs_accessible(self, session_factory):
        with UnitOfWork(session_factory) as uow:
            assert hasattr(uow, "analysis_runs")
            assert isinstance(uow.analysis_runs, AnalysisRunRepository)

    def test_create_metric_via_uow(self, session_factory, repo_id):
        with UnitOfWork(session_factory) as uow:
            m = uow.metrics.create(
                repository_id=repo_id,
                metric_name="test",
                metric_value=1.0,
                created_at=datetime.now(timezone.utc),
            )
            assert m.id is not None

    def test_create_analysis_run_via_uow(self, session_factory, repo_id):
        with UnitOfWork(session_factory) as uow:
            r = uow.analysis_runs.create(
                repository_id=repo_id,
                command="review",
                result_type="review",
                created_at=datetime.now(timezone.utc),
            )
            assert r.id is not None


# ===========================================================================
# PersistenceService Tests
# ===========================================================================


class TestPersistenceServiceMetric:
    def test_persist_metric(self, persistence, repo_id):
        result = persistence.persist_metric(
            repository_id=repo_id,
            metric_name="complexity",
            metric_value=15.5,
            git_commit="a" * 40,
            branch="main",
            metadata={"tool": "radon"},
        )
        assert result["metric_name"] == "complexity"
        assert result["metric_value"] == 15.5
        assert result["git_commit"] == "a" * 40
        assert result["branch"] == "main"
        assert result["metadata"] == {"tool": "radon"}
        assert result["id"] is not None
        assert result["created_at"] is not None

    def test_persist_metric_minimal(self, persistence, repo_id):
        result = persistence.persist_metric(
            repository_id=repo_id,
            metric_name="lines",
            metric_value=1000.0,
        )
        assert result["metric_name"] == "lines"
        assert result["git_commit"] is None
        assert result["branch"] is None
        assert result["metadata"] is None

    def test_persist_metrics_bulk(self, persistence, repo_id):
        metrics = [
            {"metric_name": f"m{i}", "metric_value": float(i), "created_at": datetime.now(timezone.utc)}
            for i in range(3)
        ]
        count = persistence.persist_metrics_bulk(repo_id, metrics)
        assert count == 3

    def test_persist_metric_returns_dict(self, persistence, repo_id):
        result = persistence.persist_metric(
            repository_id=repo_id,
            metric_name="test",
            metric_value=1.0,
        )
        assert isinstance(result, dict)
        expected_keys = {"id", "repository_id", "metric_name", "metric_value", "git_commit", "branch", "created_at", "metadata"}
        assert set(result.keys()) == expected_keys


class TestPersistenceServiceAnalysisRun:
    def test_persist_analysis_run(self, persistence, repo_id):
        result = persistence.persist_analysis_run(
            repository_id=repo_id,
            command="review",
            result_type="review",
            status="completed",
            git_commit="b" * 40,
            branch="main",
            duration_ms=2500.0,
            result_data={"risk": "high", "suggestions": 3},
            metadata={"model": "gpt-4"},
        )
        assert result["command"] == "review"
        assert result["result_type"] == "review"
        assert result["status"] == "completed"
        assert result["git_commit"] == "b" * 40
        assert result["branch"] == "main"
        assert result["duration_ms"] == 2500.0
        assert result["result_data"] == {"risk": "high", "suggestions": 3}
        assert result["metadata"] == {"model": "gpt-4"}
        assert result["error_message"] is None
        assert result["id"] is not None
        assert result["created_at"] is not None

    def test_persist_analysis_run_minimal(self, persistence, repo_id):
        result = persistence.persist_analysis_run(
            repository_id=repo_id,
            command="recommend",
            result_type="recommendations",
        )
        assert result["command"] == "recommend"
        assert result["status"] == "completed"
        assert result["duration_ms"] == 0.0
        assert result["git_commit"] is None
        assert result["branch"] is None
        assert result["result_data"] is None
        assert result["error_message"] is None

    def test_persist_analysis_run_failed(self, persistence, repo_id):
        result = persistence.persist_analysis_run(
            repository_id=repo_id,
            command="review",
            result_type="review",
            status="failed",
            error_message="Rate limit exceeded",
        )
        assert result["status"] == "failed"
        assert result["error_message"] == "Rate limit exceeded"

    def test_persist_analysis_run_returns_dict(self, persistence, repo_id):
        result = persistence.persist_analysis_run(
            repository_id=repo_id,
            command="review",
            result_type="review",
        )
        assert isinstance(result, dict)
        expected_keys = {
            "id", "repository_id", "command", "status", "git_commit",
            "branch", "duration_ms", "result_type", "result_data",
            "error_message", "created_at", "metadata",
        }
        assert set(result.keys()) == expected_keys


# ===========================================================================
# RepositoryQueryService Tests
# ===========================================================================


class TestQueryServiceMetrics:
    def test_get_metrics_empty(self, query_service, repo_id):
        result = query_service.get_metrics(repo_id)
        assert result == []

    def test_get_metrics(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id,
            metric_name="complexity",
            metric_value=10.0,
        )
        persistence.persist_metric(
            repository_id=repo_id,
            metric_name="coverage",
            metric_value=80.0,
        )
        results = query_service.get_metrics(repo_id)
        assert len(results) == 2

    def test_get_metrics_filtered_by_name(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="complexity", metric_value=10.0
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="coverage", metric_value=80.0
        )
        results = query_service.get_metrics(repo_id, metric_name="complexity")
        assert len(results) == 1
        assert results[0]["metric_name"] == "complexity"

    def test_get_metrics_filtered_by_branch(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="loc", metric_value=500.0, branch="main"
        )
        persistence.persist_metric(
            repository_id=repo_id, metric_name="loc", metric_value=600.0, branch="dev"
        )
        results = query_service.get_metrics(repo_id, branch="main")
        assert len(results) == 1
        assert results[0]["branch"] == "main"

    def test_get_metrics_by_commit(self, persistence, query_service, repo_id):
        commit = "e" * 40
        persistence.persist_metric(
            repository_id=repo_id,
            metric_name="complexity",
            metric_value=12.0,
            git_commit=commit,
        )
        results = query_service.get_metrics_by_commit(repo_id, commit)
        assert len(results) == 1
        assert results[0]["git_commit"] == commit

    def test_get_metrics_by_commit_empty(self, query_service, repo_id):
        results = query_service.get_metrics_by_commit(repo_id, "z" * 40)
        assert results == []

    def test_get_metrics_returns_dicts(self, persistence, query_service, repo_id):
        persistence.persist_metric(
            repository_id=repo_id, metric_name="test", metric_value=1.0
        )
        results = query_service.get_metrics(repo_id)
        assert isinstance(results[0], dict)
        expected_keys = {"id", "repository_id", "metric_name", "metric_value", "git_commit", "branch", "created_at", "metadata"}
        assert set(results[0].keys()) == expected_keys

    def test_get_metrics_limit(self, persistence, query_service, repo_id):
        for i in range(5):
            persistence.persist_metric(
                repository_id=repo_id, metric_name=f"m{i}", metric_value=float(i)
            )
        results = query_service.get_metrics(repo_id, limit=2)
        assert len(results) == 2


class TestQueryServiceAnalyses:
    def test_get_analyses_empty(self, query_service, repo_id):
        result = query_service.get_analyses(repo_id)
        assert result == []

    def test_get_analyses(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id, command="review", result_type="review"
        )
        persistence.persist_analysis_run(
            repository_id=repo_id, command="recommend", result_type="recommendations"
        )
        results = query_service.get_analyses(repo_id)
        assert len(results) == 2

    def test_get_analyses_filtered_by_command(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id, command="review", result_type="review"
        )
        persistence.persist_analysis_run(
            repository_id=repo_id, command="recommend", result_type="recommendations"
        )
        results = query_service.get_analyses(repo_id, command="review")
        assert len(results) == 1
        assert results[0]["command"] == "review"

    def test_get_analyses_filtered_by_status(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id, command="review", result_type="review", status="completed"
        )
        persistence.persist_analysis_run(
            repository_id=repo_id, command="review", result_type="review", status="failed",
            error_message="timeout"
        )
        results = query_service.get_analyses(repo_id, status="failed")
        assert len(results) == 1
        assert results[0]["status"] == "failed"

    def test_get_latest_analysis(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id, command="review", result_type="review"
        )
        persistence.persist_analysis_run(
            repository_id=repo_id, command="recommend", result_type="recommendations"
        )
        latest = query_service.get_latest_analysis(repo_id)
        assert latest is not None
        assert latest["command"] in ("review", "recommend")

    def test_get_latest_analysis_with_command(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id, command="review", result_type="review"
        )
        persistence.persist_analysis_run(
            repository_id=repo_id, command="recommend", result_type="recommendations"
        )
        latest = query_service.get_latest_analysis(repo_id, command="review")
        assert latest is not None
        assert latest["command"] == "review"

    def test_get_latest_analysis_empty(self, query_service, repo_id):
        result = query_service.get_latest_analysis(repo_id)
        assert result is None

    def test_get_analyses_by_commit(self, persistence, query_service, repo_id):
        commit = "f" * 40
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="review",
            result_type="review",
            git_commit=commit,
        )
        results = query_service.get_analyses_by_commit(repo_id, commit)
        assert len(results) == 1
        assert results[0]["git_commit"] == commit

    def test_get_analyses_by_commit_empty(self, query_service, repo_id):
        results = query_service.get_analyses_by_commit(repo_id, "y" * 40)
        assert results == []

    def test_get_analyses_returns_dicts(self, persistence, query_service, repo_id):
        persistence.persist_analysis_run(
            repository_id=repo_id, command="review", result_type="review"
        )
        results = query_service.get_analyses(repo_id)
        assert isinstance(results[0], dict)
        expected_keys = {
            "id", "repository_id", "command", "status", "git_commit",
            "branch", "duration_ms", "result_type", "result_data",
            "error_message", "created_at", "metadata",
        }
        assert set(results[0].keys()) == expected_keys

    def test_get_analyses_limit(self, persistence, query_service, repo_id):
        for _ in range(5):
            persistence.persist_analysis_run(
                repository_id=repo_id, command="review", result_type="review"
            )
        results = query_service.get_analyses(repo_id, limit=3)
        assert len(results) == 3

    def test_get_analyses_result_data_preserved(self, persistence, query_service, repo_id):
        data = {"risk": "high", "suggestions": [{"title": "Fix it"}]}
        persistence.persist_analysis_run(
            repository_id=repo_id,
            command="review",
            result_type="review",
            result_data=data,
        )
        results = query_service.get_analyses(repo_id)
        assert results[0]["result_data"] == data


# ===========================================================================
# Backward Compatibility Tests
# ===========================================================================


class TestBackwardCompatibility:
    """Ensure existing PersistenceService and QueryService methods still work."""

    def test_persist_review_still_works(self, persistence, repo_id):
        result = persistence.persist_review(
            repository_id=repo_id,
            risk="low",
            confidence=0.9,
            summary="All good",
        )
        assert result["risk"] == "low"

    def test_get_or_create_repository_still_works(self, persistence):
        result = persistence.get_or_create_repository(
            name="compat-repo",
            root_path="/tmp/compat-repo",
        )
        assert result["name"] == "compat-repo"

    def test_query_list_repositories_still_works(self, query_service, repo_id):
        repos = query_service.list_repositories()
        assert len(repos) >= 1

    def test_query_get_repository_still_works(self, query_service, repo_id):
        result = query_service.get_repository(repo_id)
        assert result is not None
        assert result["id"] == repo_id


# ===========================================================================
# Schema Superset Verification Tests
# ===========================================================================


class TestSchemaSupersetVerification:
    """Verify that new schema covers all StorageService fields."""

    def test_metric_has_all_historical_metric_fields(self, persistence, repo_id):
        result = persistence.persist_metric(
            repository_id=repo_id,
            metric_name="cyclomatic_complexity",
            metric_value=4.7,
            git_commit="a" * 40,
            branch="main",
            metadata={"extra": "info"},
        )
        assert "id" in result
        assert "repository_id" in result
        assert "metric_name" in result
        assert "metric_value" in result
        assert "git_commit" in result
        assert "branch" in result
        assert "created_at" in result
        assert "metadata" in result

    def test_analysis_run_has_all_storage_fields(self, persistence, repo_id):
        result = persistence.persist_analysis_run(
            repository_id=repo_id,
            command="review",
            status="completed",
            git_commit="b" * 40,
            branch="main",
            duration_ms=999.0,
            result_type="review",
            result_data={"key": "value"},
            error_message=None,
            metadata={"source": "cli"},
        )
        assert "id" in result
        assert "repository_id" in result
        assert "command" in result
        assert "status" in result
        assert "git_commit" in result
        assert "branch" in result
        assert "duration_ms" in result
        assert "result_type" in result
        assert "result_data" in result
        assert "error_message" in result
        assert "created_at" in result
        assert "metadata" in result
