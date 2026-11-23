"""Tests for StorageService, database models, and historical queries."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from refactory.storage.database import DatabaseEngine
from refactory.storage.models import AnalysisRun, Base, HistoricalMetric, RepositoryRecord
from refactory.storage.service import StorageService


@pytest.fixture
def db_engine(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = DatabaseEngine(url)
    engine.create_tables()
    return engine


@pytest.fixture
def storage(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    svc = StorageService(
        logger=_logger(),
        database_url=url,
        background=False,
    )
    return svc


def _logger():
    from loguru import logger
    return logger


# ===========================================================================
# Database Engine Tests
# ===========================================================================

class TestDatabaseEngine:
    def test_create_engine(self, tmp_path: Path):
        url = f"sqlite:///{tmp_path / 'test.db'}"
        engine = DatabaseEngine(url)
        assert engine.engine is not None

    def test_create_tables(self, db_engine: DatabaseEngine):
        session = db_engine.get_session()
        assert session is not None
        session.close()

    def test_drop_tables(self, db_engine: DatabaseEngine):
        db_engine.drop_tables()
        db_engine.create_tables()
        session = db_engine.get_session()
        repos = session.query(RepositoryRecord).all()
        assert repos == []
        session.close()

    def test_session_scope(self, db_engine: DatabaseEngine):
        gen = db_engine.session_scope()
        session = next(gen)
        repo = RepositoryRecord(name="test", path="/tmp/test")
        session.add(repo)
        try:
            gen.send(None)
        except StopIteration:
            pass

    def test_default_url(self):
        engine = DatabaseEngine()
        assert engine.engine is not None


# ===========================================================================
# Storage Service Tests
# ===========================================================================

class TestStorageService:
    def test_store_analysis(self, storage: StorageService):
        run_id = storage.store_analysis(
            repository_path="/tmp/repo",
            repository_name="test-repo",
            command="review",
            result_type="review_result",
            result_data={"score": 85},
            git_commit="abc123",
            branch="main",
            duration_ms=1500.0,
        )
        assert run_id != ""

    def test_get_analyses(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/tmp/repo",
            repository_name="test-repo",
            command="review",
            result_type="review_result",
            result_data={"score": 85},
        )
        analyses = storage.get_analyses("/tmp/repo")
        assert len(analyses) == 1
        assert analyses[0]["command"] == "review"

    def test_get_analyses_by_command(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="review", result_type="review", result_data={},
        )
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="refactor", result_type="refactor", result_data={},
        )
        reviews = storage.get_analyses("/tmp/repo", command="review")
        assert len(reviews) == 1

    def test_get_analyses_limit(self, storage: StorageService):
        for i in range(10):
            storage.store_analysis(
                repository_path="/tmp/repo", repository_name="r",
                command="review", result_type="review", result_data={"i": i},
            )
        analyses = storage.get_analyses("/tmp/repo", limit=3)
        assert len(analyses) == 3

    def test_get_analyses_empty(self, storage: StorageService):
        analyses = storage.get_analyses("/nonexistent")
        assert analyses == []

    def test_store_metric(self, storage: StorageService):
        storage.store_metric(
            repository_path="/tmp/repo",
            repository_name="test-repo",
            metric_name="health_score",
            metric_value=85.0,
            git_commit="abc123",
            branch="main",
        )
        metrics = storage.get_metrics("/tmp/repo", "health_score")
        assert len(metrics) == 1
        assert metrics[0]["value"] == 85.0

    def test_get_metrics_empty(self, storage: StorageService):
        metrics = storage.get_metrics("/nonexistent", "score")
        assert metrics == []

    def test_get_metrics_limit(self, storage: StorageService):
        for i in range(20):
            storage.store_metric(
                repository_path="/tmp/repo", repository_name="r",
                metric_name="score", metric_value=float(i),
            )
        metrics = storage.get_metrics("/tmp/repo", "score", limit=5)
        assert len(metrics) == 5

    def test_get_repositories(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/tmp/repo1", repository_name="repo1",
            command="review", result_type="review", result_data={},
        )
        repos = storage.get_repositories()
        assert len(repos) >= 1
        assert any(r["name"] == "repo1" for r in repos)

    def test_compare_analyses(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="review", result_type="review", result_data={"run": 1},
        )
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="review", result_type="review", result_data={"run": 2},
        )
        compared = storage.compare_analyses("/tmp/repo", "review", count=2)
        assert len(compared) == 2

    def test_repository_reuse(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="a", result_type="a", result_data={},
        )
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="b", result_type="b", result_data={},
        )
        repos = storage.get_repositories()
        paths = [r["path"] for r in repos]
        assert paths.count("/tmp/repo") == 1

    def test_analysis_with_error(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="review", result_type="review",
            result_data={}, status="failed",
        )
        analyses = storage.get_analyses("/tmp/repo")
        assert analyses[0]["status"] == "failed"

    def test_analysis_result_data_preserved(self, storage: StorageService):
        data = {"issues": [{"file": "a.py", "line": 10}], "score": 92}
        storage.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="review", result_type="review", result_data=data,
        )
        analyses = storage.get_analyses("/tmp/repo")
        assert analyses[0]["result_data"] == data

    def test_shutdown(self, storage: StorageService):
        storage.shutdown()

    def test_background_mode(self, tmp_path: Path):
        url = f"sqlite:///{tmp_path / 'bg.db'}"
        svc = StorageService(logger=_logger(), database_url=url, background=True)
        svc.store_analysis(
            repository_path="/tmp/repo", repository_name="r",
            command="review", result_type="review", result_data={},
        )
        svc.shutdown()
        analyses = svc.get_analyses("/tmp/repo")
        assert len(analyses) == 1


# ===========================================================================
# ORM Model Tests
# ===========================================================================

class TestORMModels:
    def test_repository_record(self, db_engine: DatabaseEngine):
        session = db_engine.get_session()
        repo = RepositoryRecord(name="test", path="/tmp")
        session.add(repo)
        session.commit()
        assert repo.id is not None
        session.close()

    def test_analysis_run(self, db_engine: DatabaseEngine):
        session = db_engine.get_session()
        repo = RepositoryRecord(name="r", path="/tmp")
        session.add(repo)
        session.commit()
        run = AnalysisRun(
            repository_id=repo.id, command="review",
            result_type="review", result_data={"x": 1},
        )
        session.add(run)
        session.commit()
        assert run.id is not None
        session.close()

    def test_historical_metric(self, db_engine: DatabaseEngine):
        session = db_engine.get_session()
        repo = RepositoryRecord(name="r", path="/tmp")
        session.add(repo)
        session.commit()
        m = HistoricalMetric(
            repository_id=repo.id, metric_name="score", metric_value=85.0,
        )
        session.add(m)
        session.commit()
        assert m.id is not None
        session.close()

    def test_relationship(self, db_engine: DatabaseEngine):
        session = db_engine.get_session()
        repo = RepositoryRecord(name="r", path="/tmp")
        session.add(repo)
        session.commit()
        run = AnalysisRun(
            repository_id=repo.id, command="review",
            result_type="review", result_data={},
        )
        session.add(run)
        session.commit()
        session.refresh(repo)
        assert len(repo.analyses) == 1
        session.close()
