"""Tests for Phase 1: PS-1 (Persistent SQLite) + PS-7 (Deterministic IDs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from refactory.recommendation.models import (
    Recommendation,
    RecommendationCategory,
    generate_recommendation_id,
)
from refactory.storage.database import DatabaseEngine, get_repo_db_path
from refactory.storage.service import StorageService


# ===========================================================================
# PS-1: Persistent SQLite database
# ===========================================================================

class TestPersistentSQLite:
    def test_db_created_at_repo_path(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        db_path = get_repo_db_path(repo)
        assert db_path == repo / ".refactory" / "storage" / "refactory.db"

    def test_db_file_created_on_init(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        engine = DatabaseEngine(repo_root=repo)
        engine.create_tables()
        db_path = repo / ".refactory" / "storage" / "refactory.db"
        assert db_path.is_file()

    def test_storage_service_creates_db(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        from loguru import logger
        svc = StorageService(logger=logger, background=False, repo_root=repo)
        db_path = repo / ".refactory" / "storage" / "refactory.db"
        assert db_path.is_file()

    def test_data_persists_across_sessions(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        from loguru import logger
        svc1 = StorageService(logger=logger, background=False, repo_root=repo)
        svc1.store_analysis(
            repository_path=str(repo), repository_name="myrepo",
            command="test", result_type="test", result_data={"key": "value"},
        )
        svc1.shutdown()

        svc2 = StorageService(logger=logger, background=False, repo_root=repo)
        analyses = svc2.get_analyses(str(repo))
        assert len(analyses) == 1
        assert analyses[0]["result_data"]["key"] == "value"
        svc2.shutdown()

    def test_metrics_persist_across_sessions(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        from loguru import logger
        svc1 = StorageService(logger=logger, background=False, repo_root=repo)
        svc1.store_metric(
            repository_path=str(repo), repository_name="myrepo",
            metric_name="health", metric_value=85.0,
        )
        svc1.shutdown()

        svc2 = StorageService(logger=logger, background=False, repo_root=repo)
        metrics = svc2.get_metrics(str(repo), "health")
        assert len(metrics) == 1
        assert metrics[0]["value"] == 85.0
        svc2.shutdown()

    def test_multiple_metrics_accumulate(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        from loguru import logger
        svc = StorageService(logger=logger, background=False, repo_root=repo)
        for i in range(5):
            svc.store_metric(
                repository_path=str(repo), repository_name="myrepo",
                metric_name="score", metric_value=float(i * 10),
            )
        metrics = svc.get_metrics(str(repo), "score")
        assert len(metrics) == 5
        svc.shutdown()

    def test_default_fallback_path(self):
        db_path = get_repo_db_path(None)
        assert "refactory.db" in str(db_path)

    def test_directory_structure_created(self, tmp_path: Path):
        repo = tmp_path / "project"
        repo.mkdir()
        DatabaseEngine(repo_root=repo).create_tables()
        assert (repo / ".refactory" / "storage").is_dir()

    def test_repo_record_persists(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        from loguru import logger
        svc = StorageService(logger=logger, background=False, repo_root=repo)
        svc.store_analysis(
            repository_path=str(repo), repository_name="myrepo",
            command="test", result_type="t", result_data={},
        )
        repos = svc.get_repositories()
        assert len(repos) == 1
        assert repos[0]["name"] == "myrepo"
        svc.shutdown()

    def test_analyses_ordered_by_time(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        from loguru import logger
        svc = StorageService(logger=logger, background=False, repo_root=repo)
        svc.store_analysis(
            repository_path=str(repo), repository_name="myrepo",
            command="first", result_type="t", result_data={"order": 1},
        )
        svc.store_analysis(
            repository_path=str(repo), repository_name="myrepo",
            command="second", result_type="t", result_data={"order": 2},
        )
        analyses = svc.get_analyses(str(repo))
        assert analyses[0]["command"] == "second"
        svc.shutdown()


# ===========================================================================
# PS-7: Deterministic Recommendation IDs
# ===========================================================================

class TestDeterministicIDs:
    def test_same_inputs_same_id(self):
        id1 = generate_recommendation_id(
            repository="myrepo", file_path="auth.py",
            category="security", title="SQL injection",
        )
        id2 = generate_recommendation_id(
            repository="myrepo", file_path="auth.py",
            category="security", title="SQL injection",
        )
        assert id1 == id2

    def test_different_file_different_id(self):
        id1 = generate_recommendation_id(
            repository="myrepo", file_path="auth.py",
            category="security", title="Issue",
        )
        id2 = generate_recommendation_id(
            repository="myrepo", file_path="api.py",
            category="security", title="Issue",
        )
        assert id1 != id2

    def test_different_category_different_id(self):
        id1 = generate_recommendation_id(
            repository="myrepo", file_path="auth.py",
            category="security", title="Issue",
        )
        id2 = generate_recommendation_id(
            repository="myrepo", file_path="auth.py",
            category="testing", title="Issue",
        )
        assert id1 != id2

    def test_different_repo_different_id(self):
        id1 = generate_recommendation_id(
            repository="repo_a", file_path="auth.py",
            category="security", title="Issue",
        )
        id2 = generate_recommendation_id(
            repository="repo_b", file_path="auth.py",
            category="security", title="Issue",
        )
        assert id1 != id2

    def test_id_format(self):
        rid = generate_recommendation_id(
            repository="myrepo", file_path="x.py",
            category="testing", title="Missing",
        )
        assert rid.startswith("R-")
        assert len(rid) == 10  # R- + 8 hex chars

    def test_symbol_used_when_provided(self):
        id1 = generate_recommendation_id(
            repository="r", file_path="f.py",
            category="refactoring", symbol="my_func",
        )
        id2 = generate_recommendation_id(
            repository="r", file_path="f.py",
            category="refactoring", symbol="other_func",
        )
        assert id1 != id2

    def test_symbol_takes_precedence_over_title(self):
        id_with_symbol = generate_recommendation_id(
            repository="r", file_path="f.py",
            category="refactoring", symbol="my_func", title="Some Title",
        )
        id_symbol_only = generate_recommendation_id(
            repository="r", file_path="f.py",
            category="refactoring", symbol="my_func",
        )
        assert id_with_symbol == id_symbol_only

    def test_empty_inputs_valid(self):
        rid = generate_recommendation_id()
        assert rid.startswith("R-")

    def test_deterministic_across_runs(self):
        results = set()
        for _ in range(100):
            rid = generate_recommendation_id(
                repository="stable", file_path="a.py",
                category="testing", title="test",
            )
            results.add(rid)
        assert len(results) == 1

    def test_recommendation_model_default_still_works(self):
        r = Recommendation(title="Test")
        assert r.id.startswith("R-")
