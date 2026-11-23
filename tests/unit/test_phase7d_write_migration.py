"""Phase 7d — Write-path migration tests.

Verifies that TransformationService and RecommendationEngine write
operations are routed through PersistenceService when available,
with automatic fallback to StorageService when PersistenceService
is unavailable or fails.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from refactory.db.base import Base
from refactory.db.models import AnalysisRunModel, MetricModel, RepositoryModel
from refactory.db.persistence import PersistenceService
from refactory.db.query_service import RepositoryQueryService
from refactory.transformation.models import (
    TransformationStatus,
    TransformationType,
    ValidationStatus,
)
from refactory.transformation.service import TransformationService
from refactory.recommendation.service import RecommendationEngine


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture()
def global_repo_id(session_factory) -> str:
    """Repository with empty root_path (used by TransformationService)."""
    sess = session_factory()
    repo = RepositoryModel(
        id=uuid.uuid4().hex[:36],
        name="",
        root_path="",
        default_branch="main",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    sess.add(repo)
    sess.commit()
    rid = repo.id
    sess.close()
    return rid


def _mock_storage():
    storage = MagicMock()
    storage.get_analyses.return_value = []
    storage.store_analysis.return_value = "id"
    storage.store_metric.return_value = None
    storage.get_metrics.return_value = []
    return storage


def _make_transform_service(
    storage=None, persistence=None, query_service=None
) -> TransformationService:
    storage = storage or _mock_storage()
    parser = MagicMock()
    parser.parse_file.return_value = None
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "new code"
    ai.generate.return_value = resp
    return TransformationService(
        logger=MagicMock(),
        parser_service=parser,
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        rule_engine=MagicMock(),
        policy_service=MagicMock(),
        storage_service=storage,
        ai_gateway=ai,
        prompt_service=MagicMock(),
        query_service=query_service,
        persistence_service=persistence,
    )


def _make_recommendation_engine(
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


# ===========================================================================
# TransformationService — Write-Path Tests
# ===========================================================================


class TestTransformWritePersistPlan:
    """_persist_plan writes via PersistenceService."""

    def test_persist_plan_uses_persistence(self, persistence, global_repo_id):
        storage = _mock_storage()
        svc = _make_transform_service(storage=storage, persistence=persistence)

        plan = MagicMock()
        plan.id = "plan-1"
        plan.transformation_type.value = "rename_function"
        plan.affected_files = ["a.py"]
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-1"
        patch_obj.additions = 5
        patch_obj.deletions = 2

        svc._persist_plan(plan, patch_obj, 42.0)

        storage.store_analysis.assert_not_called()

    def test_persist_plan_data_in_db(self, persistence, query_service, global_repo_id):
        svc = _make_transform_service(persistence=persistence)

        plan = MagicMock()
        plan.id = "plan-2"
        plan.transformation_type.value = "extract_method"
        plan.affected_files = ["b.py", "c.py"]
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-2"
        patch_obj.additions = 10
        patch_obj.deletions = 3

        svc._persist_plan(plan, patch_obj, 99.0)

        runs = query_service.get_analyses(global_repo_id, command="transform")
        assert len(runs) == 1
        run = runs[0]
        assert run["command"] == "transform"
        assert run["result_type"] == "transformation_plan"
        assert run["result_data"]["plan_id"] == "plan-2"
        assert run["result_data"]["additions"] == 10
        assert run["duration_ms"] == pytest.approx(99.0, abs=0.1)

    def test_persist_plan_fallback_no_persistence(self):
        storage = _mock_storage()
        svc = _make_transform_service(storage=storage, persistence=None)

        plan = MagicMock()
        plan.id = "plan-fb"
        plan.transformation_type.value = "rename_function"
        plan.affected_files = []
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-fb"
        patch_obj.additions = 0
        patch_obj.deletions = 0

        svc._persist_plan(plan, patch_obj, 10.0)
        storage.store_analysis.assert_called_once()


class TestTransformWritePersistResult:
    """_persist_result writes both analysis and metric via PersistenceService."""

    def test_persist_result_uses_persistence(self, persistence, global_repo_id):
        storage = _mock_storage()
        svc = _make_transform_service(storage=storage, persistence=persistence)

        plan = MagicMock()
        plan.id = "plan-r1"
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-r1"

        history = MagicMock()
        history.id = "h1"
        history.status.value = "applied"
        history.files_modified = ["x.py"]
        history.validation_status.value = "passed"
        history.transformation_type.value = "rename_function"
        history.patch_content = "diff"
        history.rollback_patch = "rollback"

        svc._persist_result(plan, patch_obj, history, 55.0)

        storage.store_analysis.assert_not_called()
        storage.store_metric.assert_not_called()

    def test_persist_result_analysis_in_db(
        self, persistence, query_service, global_repo_id
    ):
        svc = _make_transform_service(persistence=persistence)

        plan = MagicMock()
        plan.id = "plan-r2"
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-r2"

        history = MagicMock()
        history.id = "h2"
        history.status.value = "applied"
        history.files_modified = ["y.py"]
        history.validation_status.value = "passed"
        history.transformation_type.value = "extract_method"
        history.patch_content = "diff-content"
        history.rollback_patch = "rollback-content"

        svc._persist_result(plan, patch_obj, history, 77.0)

        runs = query_service.get_analyses(global_repo_id, command="apply")
        assert len(runs) == 1
        run = runs[0]
        assert run["result_data"]["history_id"] == "h2"
        assert run["result_data"]["status"] == "applied"
        assert run["result_data"]["patch_content"] == "diff-content"

    def test_persist_result_metric_in_db(
        self, persistence, query_service, global_repo_id
    ):
        svc = _make_transform_service(persistence=persistence)

        plan = MagicMock()
        plan.id = "plan-r3"
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-r3"

        history = MagicMock()
        history.id = "h3"
        history.status.value = "applied"
        history.files_modified = []
        history.validation_status.value = "passed"
        history.transformation_type.value = "rename_function"
        history.patch_content = ""
        history.rollback_patch = ""

        svc._persist_result(plan, patch_obj, history, 33.0)

        metrics = query_service.get_metrics(global_repo_id)
        assert len(metrics) == 1
        assert metrics[0]["metric_name"] == "transformations_applied"
        assert metrics[0]["metric_value"] == pytest.approx(1.0)

    def test_persist_result_fallback_no_persistence(self):
        storage = _mock_storage()
        svc = _make_transform_service(storage=storage, persistence=None)

        plan = MagicMock()
        plan.id = "p"
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "pa"

        history = MagicMock()
        history.id = "h"
        history.status.value = "applied"
        history.files_modified = []
        history.validation_status.value = "passed"
        history.transformation_type.value = "rename_function"
        history.patch_content = ""
        history.rollback_patch = ""

        svc._persist_result(plan, patch_obj, history, 1.0)
        storage.store_analysis.assert_called_once()
        storage.store_metric.assert_called_once()


class TestTransformWriteRollback:
    """rollback() writes via PersistenceService."""

    def test_rollback_writes_to_persistence(self, persistence, query_service, global_repo_id):
        storage = _mock_storage()
        svc = _make_transform_service(storage=storage, persistence=persistence)

        from refactory.transformation.models import TransformationHistory
        h = TransformationHistory(
            plan_id="p1",
            patch_id="pa1",
            status=TransformationStatus.APPLIED,
            transformation_type=TransformationType.RENAME_FUNCTION,
            files_modified=["z.py"],
            patch_content="diff",
            rollback_patch="",
            validation_status=ValidationStatus.PASSED,
        )
        svc._history.append(h)

        root = Path("/tmp/test-repo")
        result = svc.rollback(root)

        assert result.status == TransformationStatus.ROLLED_BACK
        storage.store_analysis.assert_not_called()

        repo = query_service.get_repository_by_root(str(root))
        if repo:
            runs = query_service.get_analyses(repo["id"], command="rollback")
            assert len(runs) == 1
            assert runs[0]["result_type"] == "transformation_rollback"

    def test_rollback_fallback_no_persistence(self):
        storage = _mock_storage()
        svc = _make_transform_service(storage=storage, persistence=None)

        from refactory.transformation.models import TransformationHistory
        h = TransformationHistory(
            plan_id="p1",
            patch_id="pa1",
            status=TransformationStatus.APPLIED,
            transformation_type=TransformationType.RENAME_FUNCTION,
            files_modified=[],
            patch_content="",
            rollback_patch="",
            validation_status=ValidationStatus.PASSED,
        )
        svc._history.append(h)

        result = svc.rollback(Path("/tmp/test-repo"))
        assert result.status == TransformationStatus.ROLLED_BACK
        storage.store_analysis.assert_called_once()


class TestTransformWriteFallbackOnError:
    """If PersistenceService raises, falls back to StorageService."""

    def test_persist_plan_fallback_on_persistence_error(self):
        storage = _mock_storage()
        broken_persistence = MagicMock()
        broken_persistence.get_or_create_repository.side_effect = RuntimeError("DB error")
        svc = _make_transform_service(storage=storage, persistence=broken_persistence)

        plan = MagicMock()
        plan.id = "p"
        plan.transformation_type.value = "rename_function"
        plan.affected_files = []
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "pa"
        patch_obj.additions = 0
        patch_obj.deletions = 0

        svc._persist_plan(plan, patch_obj, 1.0)
        storage.store_analysis.assert_called_once()

    def test_persist_result_fallback_on_persistence_error(self):
        storage = _mock_storage()
        broken_persistence = MagicMock()
        broken_persistence.get_or_create_repository.side_effect = RuntimeError("DB error")
        svc = _make_transform_service(storage=storage, persistence=broken_persistence)

        plan = MagicMock()
        plan.id = "p"
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "pa"

        history = MagicMock()
        history.id = "h"
        history.status.value = "applied"
        history.files_modified = []
        history.validation_status.value = "passed"
        history.transformation_type.value = "rename_function"
        history.patch_content = ""
        history.rollback_patch = ""

        svc._persist_result(plan, patch_obj, history, 1.0)
        storage.store_analysis.assert_called_once()
        storage.store_metric.assert_called_once()


class TestTransformRepositoryIdResolution:
    """Verify _get_repository_id resolves correctly."""

    def test_normal_repo(self, persistence, session_factory, global_repo_id):
        svc = _make_transform_service(persistence=persistence)
        rid = svc._get_repository_id("", "")
        assert rid == global_repo_id

    def test_creates_repo_if_missing(self, persistence):
        svc = _make_transform_service(persistence=persistence)
        rid = svc._get_repository_id("/new/path", "new-repo")
        assert isinstance(rid, str)
        assert len(rid) > 0


# ===========================================================================
# RecommendationEngine — Write-Path Tests
# ===========================================================================


class TestRecommendWriteTechDebt:
    """analyze_technical_debt() writes metric via PersistenceService."""

    def test_tech_debt_metric_uses_persistence(
        self, persistence, query_service, repo_id
    ):
        storage = _mock_storage()
        engine = _make_recommendation_engine(
            storage=storage, persistence=persistence
        )

        root = Path("/tmp/test-repo")
        with patch.object(engine, "_analyze_file_debt", return_value=[]):
            engine._indexer.load_index.return_value = MagicMock(files={})
            report = engine.analyze_technical_debt(root)

        storage.store_metric.assert_not_called()
        metrics = query_service.get_metrics(repo_id, metric_name="tech_debt_score")
        assert len(metrics) == 1
        assert metrics[0]["metric_value"] == pytest.approx(report.total_score)

    def test_tech_debt_fallback_no_persistence(self):
        storage = _mock_storage()
        engine = _make_recommendation_engine(storage=storage, persistence=None)

        root = Path("/tmp/test-repo")
        with patch.object(engine, "_analyze_file_debt", return_value=[]):
            engine._indexer.load_index.return_value = MagicMock(files={})
            engine.analyze_technical_debt(root)

        storage.store_metric.assert_called_once()
        assert storage.store_metric.call_args.kwargs["metric_name"] == "tech_debt_score"


class TestRecommendWriteHealth:
    """_calculate_health() writes all health metrics via PersistenceService."""

    def _run_health(self, engine, root):
        from refactory.recommendation.models import (
            Recommendation,
            RecommendationCategory,
            RecommendationPriority,
        )
        recs = [
            Recommendation(
                id="r1",
                title="Fix",
                description="desc",
                category=RecommendationCategory.REFACTORING,
                priority=RecommendationPriority.MEDIUM,
                score=5.0,
            )
        ]
        return engine._calculate_health(root, recs)

    def test_health_metrics_use_persistence(
        self, persistence, query_service, repo_id
    ):
        storage = _mock_storage()
        engine = _make_recommendation_engine(
            storage=storage, persistence=persistence
        )
        root = Path("/tmp/test-repo")
        report = self._run_health(engine, root)

        storage.store_metric.assert_not_called()

        metrics = query_service.get_metrics(repo_id)
        metric_names = {m["metric_name"] for m in metrics}
        assert "health_overall" in metric_names
        assert "health_architecture" in metric_names
        assert "health_security" in metric_names
        assert "health_testing" in metric_names
        assert "health_documentation" in metric_names
        assert "health_technical_debt" in metric_names
        assert "health_maintainability" in metric_names
        assert "health_performance" in metric_names
        assert len(metrics) == 8

    def test_health_overall_value(self, persistence, query_service, repo_id):
        engine = _make_recommendation_engine(persistence=persistence)
        root = Path("/tmp/test-repo")
        report = self._run_health(engine, root)

        metrics = query_service.get_metrics(repo_id, metric_name="health_overall")
        assert len(metrics) == 1
        assert metrics[0]["metric_value"] == pytest.approx(report.scores.overall)

    def test_health_fallback_no_persistence(self):
        storage = _mock_storage()
        engine = _make_recommendation_engine(storage=storage, persistence=None)
        root = Path("/tmp/test-repo")
        self._run_health(engine, root)

        assert storage.store_metric.call_count == 8


class TestRecommendWritePersistRecommendations:
    """_persist_recommendations writes analysis + metric via PersistenceService."""

    def _make_report(self):
        from refactory.recommendation.models import RecommendationReport
        return RecommendationReport(
            recommendations=[],
            total_recommendations=42,
        )

    def test_persist_recommendations_uses_persistence(
        self, persistence, query_service, repo_id
    ):
        storage = _mock_storage()
        engine = _make_recommendation_engine(
            storage=storage, persistence=persistence
        )
        root = Path("/tmp/test-repo")
        report = self._make_report()

        engine._persist_recommendations(root, report, 123.0)

        storage.store_analysis.assert_not_called()
        storage.store_metric.assert_not_called()

        runs = query_service.get_analyses(repo_id, command="recommend")
        assert len(runs) == 1
        assert runs[0]["result_type"] == "recommendations"
        assert runs[0]["duration_ms"] == pytest.approx(123.0, abs=0.1)

        metrics = query_service.get_metrics(repo_id, metric_name="recommendation_count")
        assert len(metrics) == 1
        assert metrics[0]["metric_value"] == pytest.approx(42.0)

    def test_persist_recommendations_result_data_intact(
        self, persistence, query_service, repo_id
    ):
        engine = _make_recommendation_engine(persistence=persistence)
        root = Path("/tmp/test-repo")
        report = self._make_report()
        engine._persist_recommendations(root, report, 50.0)

        runs = query_service.get_analyses(repo_id, command="recommend")
        data = runs[0]["result_data"]
        assert data["total_recommendations"] == 42
        assert data["recommendations"] == []

    def test_persist_recommendations_fallback_no_persistence(self):
        storage = _mock_storage()
        engine = _make_recommendation_engine(storage=storage, persistence=None)
        root = Path("/tmp/test-repo")
        report = self._make_report()

        engine._persist_recommendations(root, report, 10.0)
        storage.store_analysis.assert_called_once()
        storage.store_metric.assert_called_once()


class TestRecommendWriteFallbackOnError:
    """If PersistenceService raises, falls back to StorageService."""

    def test_tech_debt_fallback_on_error(self):
        storage = _mock_storage()
        broken = MagicMock()
        broken.get_or_create_repository.side_effect = RuntimeError("DB down")
        engine = _make_recommendation_engine(storage=storage, persistence=broken)

        root = Path("/tmp/test-repo")
        with patch.object(engine, "_analyze_file_debt", return_value=[]):
            engine._indexer.load_index.return_value = MagicMock(files={})
            engine.analyze_technical_debt(root)

        storage.store_metric.assert_called_once()

    def test_persist_recommendations_fallback_on_error(self):
        storage = _mock_storage()
        broken = MagicMock()
        broken.get_or_create_repository.side_effect = RuntimeError("DB down")
        engine = _make_recommendation_engine(storage=storage, persistence=broken)

        from refactory.recommendation.models import RecommendationReport
        report = RecommendationReport(
            recommendations=[], total_recommendations=5, categories={},
        )
        engine._persist_recommendations(Path("/tmp/test-repo"), report, 1.0)
        storage.store_analysis.assert_called_once()
        storage.store_metric.assert_called_once()


class TestRecommendRepositoryIdResolution:
    """Verify _get_repository_id resolves correctly for RecommendationEngine."""

    def test_resolves_existing_repo(self, persistence, repo_id):
        engine = _make_recommendation_engine(persistence=persistence)
        rid = engine._get_repository_id(str(Path("/tmp/test-repo")), "test-repo")
        assert rid == repo_id

    def test_creates_repo_if_missing(self, persistence):
        engine = _make_recommendation_engine(persistence=persistence)
        rid = engine._get_repository_id("/brand/new", "brand-new")
        assert isinstance(rid, str)
        assert len(rid) > 0


# ===========================================================================
# Backward Compatibility — Constructor Tests
# ===========================================================================


class TestConstructorBackwardCompat:
    """Both services work without persistence_service."""

    def test_transform_without_persistence(self):
        svc = _make_transform_service(persistence=None)
        assert svc._persistence is None

    def test_transform_with_persistence(self, persistence):
        svc = _make_transform_service(persistence=persistence)
        assert svc._persistence is persistence

    def test_recommend_without_persistence(self):
        engine = _make_recommendation_engine(persistence=None)
        assert engine._persistence is None

    def test_recommend_with_persistence(self, persistence):
        engine = _make_recommendation_engine(persistence=persistence)
        assert engine._persistence is persistence


# ===========================================================================
# Cross-service: Identical payloads between Persistence and Storage fallback
# ===========================================================================


class TestPayloadEquivalence:
    """Verify that data written via PersistenceService is identical
    to what StorageService would have received."""

    def test_transform_plan_payload_fields(
        self, persistence, query_service, global_repo_id
    ):
        svc = _make_transform_service(persistence=persistence)

        plan = MagicMock()
        plan.id = "plan-eq"
        plan.transformation_type.value = "rename_function"
        plan.affected_files = ["a.py", "b.py"]
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-eq"
        patch_obj.additions = 7
        patch_obj.deletions = 3

        svc._persist_plan(plan, patch_obj, 50.0)

        runs = query_service.get_analyses(global_repo_id, command="transform")
        data = runs[0]["result_data"]
        assert data["plan_id"] == "plan-eq"
        assert data["patch_id"] == "patch-eq"
        assert data["type"] == "rename_function"
        assert data["files"] == ["a.py", "b.py"]
        assert data["additions"] == 7
        assert data["deletions"] == 3

    def test_recommend_analysis_payload_fields(
        self, persistence, query_service, repo_id
    ):
        from refactory.recommendation.models import RecommendationReport
        engine = _make_recommendation_engine(persistence=persistence)

        report = RecommendationReport(
            recommendations=[],
            total_recommendations=17,
            critical_count=3,
            high_count=5,
        )
        engine._persist_recommendations(Path("/tmp/test-repo"), report, 200.0)

        runs = query_service.get_analyses(repo_id, command="recommend")
        data = runs[0]["result_data"]
        assert data["total_recommendations"] == 17
        assert data["critical_count"] == 3
        assert data["high_count"] == 5

    def test_transform_result_all_fields(
        self, persistence, query_service, global_repo_id
    ):
        svc = _make_transform_service(persistence=persistence)

        plan = MagicMock()
        plan.id = "plan-full"
        plan.steps = []

        patch_obj = MagicMock()
        patch_obj.id = "patch-full"

        history = MagicMock()
        history.id = "hist-full"
        history.status.value = "applied"
        history.files_modified = ["m.py", "n.py"]
        history.validation_status.value = "passed"
        history.transformation_type.value = "extract_method"
        history.patch_content = "diff-data"
        history.rollback_patch = "rollback-data"

        svc._persist_result(plan, patch_obj, history, 88.0)

        runs = query_service.get_analyses(global_repo_id, command="apply")
        data = runs[0]["result_data"]
        assert data["history_id"] == "hist-full"
        assert data["plan_id"] == "plan-full"
        assert data["patch_id"] == "patch-full"
        assert data["status"] == "applied"
        assert data["files_modified"] == ["m.py", "n.py"]
        assert data["validation_status"] == "passed"
        assert data["transformation_type"] == "extract_method"
        assert data["patch_content"] == "diff-data"
        assert data["rollback_patch"] == "rollback-data"
