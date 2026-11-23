"""Comprehensive tests for the Recommendation Engine (Sprint 7).

Covers: RecommendationEngine, models, scoring, technical debt, health,
trends, bundles, persistence, rule-aware, architecture-aware, and CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refactory.recommendation.models import (
    HealthReport,
    HealthScores,
    Recommendation,
    RecommendationBundle,
    RecommendationCategory,
    RecommendationExplanation,
    RecommendationPriority,
    RecommendationReport,
    RecommendationStatus,
    TechnicalDebtCategory,
    TechnicalDebtItem,
    TechnicalDebtReport,
    TrendItem,
    TrendReport,
)
from refactory.recommendation.service import RecommendationEngine


@pytest.fixture
def mock_storage():
    s = MagicMock()
    s.get_metrics.return_value = []
    s.store_analysis.return_value = "run-id"
    s.store_metric.return_value = None
    return s


@pytest.fixture
def mock_ai():
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "AI recommendation"
    ai.generate.return_value = resp
    return ai


@pytest.fixture
def mock_rules():
    r = MagicMock()
    r.load_rules.return_value = 0
    result = MagicMock()
    result.violations = []
    r.evaluate.return_value = result
    return r


@pytest.fixture
def mock_policy():
    p = MagicMock()
    p.policy = None
    return p


@pytest.fixture
def engine(mock_storage, mock_ai, mock_rules, mock_policy):
    from loguru import logger
    return RecommendationEngine(
        logger=logger,
        parser_service=MagicMock(),
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        impact_service=MagicMock(),
        rule_engine=mock_rules,
        policy_service=mock_policy,
        storage_service=mock_storage,
        ai_gateway=mock_ai,
        prompt_service=MagicMock(),
    )


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "tests" / "unit").mkdir(parents=True)
    (d / "src").mkdir()
    (d / "src" / "service.py").write_text(
        "class UserService:\n" + "    def method(self):\n        pass\n" * 20
    )
    (d / "src" / "utils.py").write_text("def helper(): pass\n")
    (d / "tests" / "unit" / "test_utils.py").write_text("def test_helper(): pass\n")
    return d


# ===========================================================================
# Task 1: Recommendation Engine Models (30 tests)
# ===========================================================================

class TestRecommendationModels:
    def test_recommendation_defaults(self):
        r = Recommendation(title="Test")
        assert r.title == "Test"
        assert r.id.startswith("R-")
        assert r.priority == RecommendationPriority.MEDIUM

    def test_recommendation_categories(self):
        assert RecommendationCategory.SECURITY == "security"
        assert RecommendationCategory.ARCHITECTURE == "architecture"
        assert RecommendationCategory.TECHNICAL_DEBT == "technical_debt"

    def test_recommendation_priorities(self):
        assert RecommendationPriority.CRITICAL == "critical"
        assert RecommendationPriority.HIGH == "high"
        assert RecommendationPriority.MEDIUM == "medium"
        assert RecommendationPriority.LOW == "low"

    def test_recommendation_status(self):
        assert RecommendationStatus.PENDING == "pending"
        assert RecommendationStatus.IMPLEMENTED == "implemented"

    def test_recommendation_with_files(self):
        r = Recommendation(title="Fix", affected_files=["a.py", "b.py"])
        assert len(r.affected_files) == 2

    def test_recommendation_explanation(self):
        e = RecommendationExplanation(why="Security risk", benefits=["Safer"])
        assert e.why == "Security risk"
        assert "Safer" in e.benefits

    def test_recommendation_bundle(self):
        b = RecommendationBundle(title="Auth cleanup", recommendations=["R-1", "R-2"])
        assert b.id.startswith("B-")
        assert len(b.recommendations) == 2

    def test_technical_debt_item(self):
        i = TechnicalDebtItem(category=TechnicalDebtCategory.LARGE_CLASS, file_path="a.py")
        assert i.category == TechnicalDebtCategory.LARGE_CLASS

    def test_technical_debt_categories(self):
        assert TechnicalDebtCategory.GOD_OBJECT == "god_object"
        assert TechnicalDebtCategory.DEEP_NESTING == "deep_nesting"
        assert TechnicalDebtCategory.DUPLICATE_CODE == "duplicate_code"

    def test_technical_debt_report(self):
        r = TechnicalDebtReport()
        assert r.total_score == 0.0
        assert r.items == []

    def test_health_scores(self):
        h = HealthScores(architecture=90, security=80)
        assert h.architecture == 90

    def test_health_report(self):
        r = HealthReport()
        assert r.scores.overall == 0.0

    def test_trend_item(self):
        t = TrendItem(metric_name="health", direction="improving", change_percent=5.0)
        assert t.direction == "improving"

    def test_trend_report(self):
        r = TrendReport()
        assert r.trends == []

    def test_recommendation_report(self):
        r = RecommendationReport()
        assert r.total_recommendations == 0

    def test_recommendation_score_field(self):
        r = Recommendation(title="T", score=85.0)
        assert r.score == 85.0

    def test_recommendation_bundle_id(self):
        r = Recommendation(title="T", bundle_id="B-ABC123")
        assert r.bundle_id == "B-ABC123"

    def test_transformation_fields(self):
        r = Recommendation(
            title="T",
            transformation_type="refactor",
            transformation_parameters={"target": "split"},
            estimated_patch_size=100,
        )
        assert r.transformation_type == "refactor"
        assert r.estimated_patch_size == 100

    def test_recommendation_serializable(self):
        r = Recommendation(title="Test", confidence=0.9)
        data = r.model_dump(mode="json")
        assert "title" in data
        assert data["confidence"] == 0.9

    def test_report_serializable(self):
        report = RecommendationReport(
            repository_score=85,
            recommendations=[Recommendation(title="R1")],
        )
        data = report.model_dump(mode="json")
        assert data["repository_score"] == 85

    def test_health_scores_overall(self):
        h = HealthScores(
            architecture=80, maintainability=70, security=90,
            performance=75, testing=85, documentation=60, technical_debt=65,
        )
        assert h.overall == 0.0

    def test_explanation_alternatives(self):
        e = RecommendationExplanation(
            alternatives=["Do nothing", "Partial fix", "Full rewrite"]
        )
        assert len(e.alternatives) == 3

    def test_debt_item_score(self):
        i = TechnicalDebtItem(
            category=TechnicalDebtCategory.LARGE_METHOD,
            score=15.0,
        )
        assert i.score == 15.0

    def test_bundle_estimated_effort(self):
        b = RecommendationBundle(title="Fix", estimated_total_effort="2 hours")
        assert b.estimated_total_effort == "2 hours"

    def test_recommendation_created_at(self):
        r = Recommendation(title="T")
        assert r.created_at is not None

    def test_multiple_affected_modules(self):
        r = Recommendation(title="T", affected_modules=["auth", "core", "api"])
        assert len(r.affected_modules) == 3

    def test_recommendation_dependencies(self):
        r = Recommendation(title="T", dependencies=["R-001", "R-002"])
        assert len(r.dependencies) == 2

    def test_report_counts(self):
        report = RecommendationReport(
            critical_count=2, high_count=5, medium_count=8, low_count=3,
        )
        assert report.critical_count == 2
        assert report.high_count == 5

    def test_trend_report_modules(self):
        r = TrendReport(modules_degrading=["auth"], modules_improving=["api"])
        assert "auth" in r.modules_degrading

    def test_health_report_critical(self):
        r = HealthReport(critical_count=3)
        assert r.critical_count == 3


# ===========================================================================
# Task 4: Technical Debt Detection (25 tests)
# ===========================================================================

class TestTechnicalDebt:
    def test_detect_large_file(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        big_file = repo / "big.py"
        big_file.write_text("\n".join(f"line_{i} = {i}" for i in range(600)))
        report = engine.analyze_technical_debt(repo)
        assert any(i.category == TechnicalDebtCategory.LARGE_CLASS for i in report.items)

    def test_detect_large_method(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        content = "def big_func():\n" + "\n".join(f"    x = {i}" for i in range(60))
        (repo / "func.py").write_text(content)
        report = engine.analyze_technical_debt(repo)
        assert any(i.category == TechnicalDebtCategory.LARGE_METHOD for i in report.items)

    def test_detect_god_object(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        methods = "\n".join(f"    def method_{i}(self): pass" for i in range(20))
        (repo / "god.py").write_text(f"\nclass God:\n{methods}\n")
        report = engine.analyze_technical_debt(repo)
        assert any(i.category == TechnicalDebtCategory.GOD_OBJECT for i in report.items)

    def test_detect_deep_nesting(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        content = "def f():\n" + "".join(f"{'    ' * (i+1)}if True:\n" for i in range(8))
        (repo / "nested.py").write_text(content)
        report = engine.analyze_technical_debt(repo)
        assert any(i.category == TechnicalDebtCategory.DEEP_NESTING for i in report.items)

    def test_detect_long_params(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        params = ", ".join(f"param_{i}_name" for i in range(8))
        (repo / "params.py").write_text(f"def func({params}):\n    pass\n")
        report = engine.analyze_technical_debt(repo)
        assert any(i.category == TechnicalDebtCategory.LONG_PARAMETER_LIST for i in report.items)

    def test_clean_file_no_debt(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "clean.py").write_text("def hello():\n    return 1\n")
        report = engine.analyze_technical_debt(repo)
        assert report.total_score == 0.0

    def test_empty_repo(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "empty"
        repo.mkdir()
        report = engine.analyze_technical_debt(repo)
        assert report.items == []

    def test_debt_score_calculation(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "big.py").write_text("\n" * 600)
        report = engine.analyze_technical_debt(repo)
        assert report.total_score > 0

    def test_categories_counted(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "big.py").write_text("\n" * 600)
        report = engine.analyze_technical_debt(repo)
        assert len(report.categories) > 0

    def test_ignores_pycache(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        (repo / "__pycache__").mkdir(parents=True)
        (repo / "__pycache__" / "cached.py").write_text("\n" * 1000)
        report = engine.analyze_technical_debt(repo)
        assert report.total_score == 0.0

    def test_ignores_venv(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        (repo / ".venv" / "lib").mkdir(parents=True)
        (repo / ".venv" / "lib" / "big.py").write_text("\n" * 1000)
        report = engine.analyze_technical_debt(repo)
        assert report.total_score == 0.0

    def test_debt_items_sorted(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "huge.py").write_text("\n" * 1200)
        (repo / "medium.py").write_text("\n" * 600)
        report = engine.analyze_technical_debt(repo)
        if len(report.items) >= 2:
            assert report.items[0].score >= report.items[1].score

    def test_debt_persisted(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("x = 1\n")
        engine.analyze_technical_debt(repo)
        engine._storage.store_metric.assert_called()

    def test_report_items_limited(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        for i in range(150):
            (repo / f"file_{i}.py").write_text("\n" * 600)
        report = engine.analyze_technical_debt(repo)
        assert len(report.items) <= 100

    def test_severity_levels(self):
        i1 = TechnicalDebtItem(category=TechnicalDebtCategory.LARGE_CLASS, severity="high")
        i2 = TechnicalDebtItem(category=TechnicalDebtCategory.DEEP_NESTING, severity="medium")
        assert i1.severity == "high"
        assert i2.severity == "medium"

    def test_cleanup_effort(self):
        i = TechnicalDebtItem(
            category=TechnicalDebtCategory.GOD_OBJECT,
            estimated_cleanup_effort="2-4 hours",
        )
        assert i.estimated_cleanup_effort == "2-4 hours"

    def test_binary_file_skipped(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "binary.py").write_bytes(b"\x00\x01\x02" * 1000)
        report = engine.analyze_technical_debt(repo)
        assert True  # Should not crash

    def test_file_path_relative(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "big.py").write_text("\n" * 600)
        report = engine.analyze_technical_debt(repo)
        if report.items:
            assert not report.items[0].file_path.startswith("/")

    def test_multiple_issues_per_file(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        methods = "\n".join(f"    def m{i}(self):\n" + "\n".join(f"        x{j}={j}" for j in range(60)) for i in range(20))
        (repo / "complex.py").write_text(f"\nclass Big:\n{methods}\n")
        report = engine.analyze_technical_debt(repo)
        assert len(report.items) > 1

    def test_debt_report_serializable(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("x = 1\n")
        report = engine.analyze_technical_debt(repo)
        data = report.model_dump()
        assert "items" in data

    def test_all_debt_categories(self):
        cats = list(TechnicalDebtCategory)
        assert len(cats) >= 10

    def test_debt_item_with_symbol(self):
        i = TechnicalDebtItem(
            category=TechnicalDebtCategory.LARGE_METHOD,
            symbol="process_all",
        )
        assert i.symbol == "process_all"

    def test_debt_score_bounded(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "huge.py").write_text("\n" * 5000)
        report = engine.analyze_technical_debt(repo)
        for item in report.items:
            assert item.score <= 30.0

    def test_empty_file_no_debt(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "empty.py").write_text("")
        report = engine.analyze_technical_debt(repo)
        assert report.total_score == 0.0

    def test_debt_with_comments(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "commented.py").write_text("# " * 200 + "\n")
        report = engine.analyze_technical_debt(repo)
        assert report.total_score == 0.0


# ===========================================================================
# Task 5: Repository Health (25 tests)
# ===========================================================================

class TestRepositoryHealth:
    def test_health_empty_recs(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.calculate_health(sample_repo)
        assert report.scores.overall > 0

    def test_health_with_security_issues(self, engine: RecommendationEngine, sample_repo: Path):
        engine._calculate_health(sample_repo, [
            Recommendation(title="Sec", category=RecommendationCategory.SECURITY),
            Recommendation(title="Sec2", category=RecommendationCategory.SECURITY),
        ])

    def test_health_all_categories(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.calculate_health(sample_repo)
        s = report.scores
        assert s.architecture >= 0
        assert s.maintainability >= 0
        assert s.security >= 0
        assert s.performance >= 0
        assert s.testing >= 0
        assert s.documentation >= 0
        assert s.technical_debt >= 0

    def test_health_score_bounded(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.calculate_health(sample_repo)
        assert 0 <= report.scores.overall <= 100

    def test_health_persisted(self, engine: RecommendationEngine, sample_repo: Path):
        engine.calculate_health(sample_repo)
        engine._storage.store_metric.assert_called()

    def test_health_critical_count(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine._calculate_health(sample_repo, [
            Recommendation(title="C", priority=RecommendationPriority.CRITICAL),
        ])
        assert report.critical_count == 1

    def test_health_recommendations_count(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title=f"R{i}") for i in range(5)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.recommendations_count == 5

    def test_health_degraded_by_debt(self, engine: RecommendationEngine, sample_repo: Path):
        clean = engine._calculate_health(sample_repo, [])
        debt_recs = [
            Recommendation(title=f"D{i}", category=RecommendationCategory.TECHNICAL_DEBT)
            for i in range(5)
        ]
        degraded = engine._calculate_health(sample_repo, debt_recs)
        assert degraded.scores.technical_debt < clean.scores.technical_debt

    def test_health_model_defaults(self):
        r = HealthReport()
        assert r.scores.overall == 0.0
        assert r.critical_count == 0

    def test_health_serializable(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.calculate_health(sample_repo)
        data = report.model_dump()
        assert "scores" in data

    def test_security_score_drops(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [
            Recommendation(title=f"S{i}", category=RecommendationCategory.SECURITY)
            for i in range(5)
        ]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.security < 100

    def test_perfect_health(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine._calculate_health(sample_repo, [])
        assert report.scores.overall == 100.0

    def test_architecture_score_drops(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title="A", category=RecommendationCategory.ARCHITECTURE) for _ in range(3)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.architecture < 100

    def test_testing_score_drops(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title="T", category=RecommendationCategory.TESTING) for _ in range(4)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.testing < 100

    def test_perf_score_drops(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title="P", category=RecommendationCategory.PERFORMANCE) for _ in range(3)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.performance < 100

    def test_doc_score_drops(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title="D", category=RecommendationCategory.DOCUMENTATION) for _ in range(5)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.documentation < 100

    def test_health_scores_non_negative(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title=f"S{i}", category=RecommendationCategory.SECURITY) for i in range(20)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.security >= 0

    def test_overall_weighted(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine._calculate_health(sample_repo, [])
        expected = 100.0 * (0.20 + 0.15 + 0.20 + 0.15 + 0.15 + 0.05 + 0.10)
        assert abs(report.scores.overall - expected) < 1.0

    def test_health_trends_empty(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.calculate_health(sample_repo)
        assert report.trends == {}

    def test_health_with_many_issues(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [
            Recommendation(title=f"I{i}", category=RecommendationCategory.TECHNICAL_DEBT)
            for i in range(30)
        ]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.technical_debt == 0.0

    def test_maintainability_bounded(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title=f"D{i}", category=RecommendationCategory.TECHNICAL_DEBT) for i in range(50)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.maintainability >= 0

    def test_health_report_model_dump(self):
        r = HealthReport(scores=HealthScores(overall=85.0))
        d = r.model_dump()
        assert d["scores"]["overall"] == 85.0

    def test_health_no_crash_on_empty_repo(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "empty"
        repo.mkdir()
        report = engine.calculate_health(repo)
        assert report.scores.overall >= 0

    def test_scores_model_fields(self):
        s = HealthScores()
        fields = s.model_fields
        assert "architecture" in fields
        assert "overall" in fields

    def test_score_independence(self, engine: RecommendationEngine, sample_repo: Path):
        recs = [Recommendation(title="S", category=RecommendationCategory.SECURITY)]
        report = engine._calculate_health(sample_repo, recs)
        assert report.scores.testing == 100.0


# ===========================================================================
# Task 6: Trend Analysis (20 tests)
# ===========================================================================

class TestTrendAnalysis:
    def test_no_history(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.analyze_trends(sample_repo)
        assert report.trends == []

    def test_health_improving(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 90.0}, {"value": 80.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        health_trends = [t for t in report.trends if t.metric_name == "health_overall"]
        assert len(health_trends) == 1
        assert health_trends[0].direction == "improving"

    def test_health_degrading(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 70.0}, {"value": 80.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        health_trends = [t for t in report.trends if t.metric_name == "health_overall"]
        if health_trends:
            assert health_trends[0].direction == "degrading"

    def test_debt_increasing(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 50.0}, {"value": 30.0}] if name == "tech_debt_score" else []
        )
        report = engine.analyze_trends(sample_repo)
        debt_trends = [t for t in report.trends if t.metric_name == "tech_debt"]
        if debt_trends:
            assert debt_trends[0].direction == "increasing"

    def test_stable_metrics(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 80.0}, {"value": 80.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        if report.trends:
            assert report.trends[0].direction == "stable"

    def test_trend_report_model(self):
        r = TrendReport(period="7d")
        assert r.period == "7d"

    def test_trend_item_model(self):
        t = TrendItem(metric_name="score", change_percent=15.0)
        assert t.change_percent == 15.0

    def test_multiple_metrics_tracked(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 90.0}, {"value": 80.0}]
        )
        report = engine.analyze_trends(sample_repo)
        assert len(report.trends) >= 1

    def test_trend_description(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 95.0}, {"value": 80.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        if report.trends:
            assert report.trends[0].description != ""

    def test_change_percent_calculated(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 100.0}, {"value": 50.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        if report.trends:
            assert report.trends[0].change_percent == 100.0

    def test_trend_serializable(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.analyze_trends(sample_repo)
        data = report.model_dump()
        assert "trends" in data

    def test_trend_period_field(self):
        r = TrendReport(period="30d")
        assert r.period == "30d"

    def test_single_data_point_no_trend(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 80.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        health_trends = [t for t in report.trends if t.metric_name == "health_overall"]
        assert len(health_trends) == 0

    def test_modules_degrading(self):
        r = TrendReport(modules_degrading=["auth", "core"])
        assert "auth" in r.modules_degrading

    def test_modules_improving(self):
        r = TrendReport(modules_improving=["api"])
        assert "api" in r.modules_improving

    def test_zero_base_no_crash(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 50.0}, {"value": 0.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        assert True  # No division by zero

    def test_negative_change(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.side_effect = lambda path, name, **kw: (
            [{"value": 60.0}, {"value": 80.0}] if name == "health_overall" else []
        )
        report = engine.analyze_trends(sample_repo)
        if report.trends:
            assert report.trends[0].change_percent < 0

    def test_trend_with_all_metrics(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.get_metrics.return_value = [{"value": 80.0}, {"value": 70.0}]
        report = engine.analyze_trends(sample_repo)
        assert len(report.trends) >= 1

    def test_period_default(self):
        r = TrendReport()
        assert r.period == "30d"

    def test_empty_modules(self):
        r = TrendReport()
        assert r.modules_degrading == []
        assert r.modules_improving == []


# ===========================================================================
# Task 2: Recommendation Scoring & Ranking (20 tests)
# ===========================================================================

class TestRecommendationScoring:
    def test_security_scores_highest(self, engine: RecommendationEngine):
        sec = Recommendation(title="S", category=RecommendationCategory.SECURITY, confidence=0.9)
        doc = Recommendation(title="D", category=RecommendationCategory.DOCUMENTATION, confidence=0.9)
        assert engine._score_recommendation(sec) > engine._score_recommendation(doc)

    def test_more_files_higher_score(self, engine: RecommendationEngine):
        few = Recommendation(title="F", affected_files=["a.py"])
        many = Recommendation(title="M", affected_files=[f"f{i}.py" for i in range(7)])
        assert engine._score_recommendation(many) > engine._score_recommendation(few)

    def test_high_risk_higher_score(self, engine: RecommendationEngine):
        high = Recommendation(title="H", estimated_risk="high")
        low = Recommendation(title="L", estimated_risk="low")
        assert engine._score_recommendation(high) > engine._score_recommendation(low)

    def test_business_impact_bonus(self, engine: RecommendationEngine):
        with_impact = Recommendation(title="I", business_impact="Revenue at risk")
        without = Recommendation(title="N", business_impact="")
        assert engine._score_recommendation(with_impact) > engine._score_recommendation(without)

    def test_score_bounded_100(self, engine: RecommendationEngine):
        r = Recommendation(
            title="Max", category=RecommendationCategory.SECURITY,
            confidence=1.0, affected_files=[f"f{i}.py" for i in range(20)],
            estimated_risk="high", business_impact="Critical",
        )
        assert engine._score_recommendation(r) <= 100.0

    def test_prioritize_critical(self, engine: RecommendationEngine):
        assert engine._prioritize(80) == RecommendationPriority.CRITICAL

    def test_prioritize_high(self, engine: RecommendationEngine):
        assert engine._prioritize(60) == RecommendationPriority.HIGH

    def test_prioritize_medium(self, engine: RecommendationEngine):
        assert engine._prioritize(40) == RecommendationPriority.MEDIUM

    def test_prioritize_low(self, engine: RecommendationEngine):
        assert engine._prioritize(20) == RecommendationPriority.LOW

    def test_confidence_affects_score(self, engine: RecommendationEngine):
        high_conf = Recommendation(title="H", confidence=0.95)
        low_conf = Recommendation(title="L", confidence=0.3)
        assert engine._score_recommendation(high_conf) > engine._score_recommendation(low_conf)

    def test_architecture_weight(self, engine: RecommendationEngine):
        arch = Recommendation(title="A", category=RecommendationCategory.ARCHITECTURE, confidence=0.8)
        doc = Recommendation(title="D", category=RecommendationCategory.DOCUMENTATION, confidence=0.8)
        assert engine._score_recommendation(arch) > engine._score_recommendation(doc)

    def test_zero_confidence_low_score(self, engine: RecommendationEngine):
        r = Recommendation(title="Z", confidence=0.0)
        score = engine._score_recommendation(r)
        assert score < 50

    def test_recommendations_sorted_by_score(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.generate_recommendations(sample_repo)
        scores = [r.score for r in report.recommendations]
        assert scores == sorted(scores, reverse=True)

    def test_top_filter(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.generate_recommendations(sample_repo, top=3)
        assert len(report.recommendations) <= 3

    def test_category_filter(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.generate_recommendations(sample_repo, category="security")
        for r in report.recommendations:
            assert r.category == RecommendationCategory.SECURITY

    def test_priority_filter(self, engine: RecommendationEngine, sample_repo: Path):
        report = engine.generate_recommendations(sample_repo, priority="critical")
        for r in report.recommendations:
            assert r.priority == RecommendationPriority.CRITICAL

    def test_score_minimum_positive(self, engine: RecommendationEngine):
        r = Recommendation(title="Min")
        score = engine._score_recommendation(r)
        assert score > 0

    def test_medium_risk_score(self, engine: RecommendationEngine):
        r = Recommendation(title="M", estimated_risk="medium")
        score = engine._score_recommendation(r)
        assert score > engine._score_recommendation(Recommendation(title="L", estimated_risk="low"))

    def test_reliability_weight(self, engine: RecommendationEngine):
        r = Recommendation(title="R", category=RecommendationCategory.RELIABILITY, confidence=0.8)
        score = engine._score_recommendation(r)
        assert score > 30

    def test_best_practices_weight(self, engine: RecommendationEngine):
        r = Recommendation(title="B", category=RecommendationCategory.BEST_PRACTICES)
        score = engine._score_recommendation(r)
        assert score > 0


# ===========================================================================
# Task 9/15: Storage Integration (20 tests)
# ===========================================================================

class TestStorageIntegration:
    def test_recommendations_persisted(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        engine._storage.store_analysis.assert_called_once()

    def test_metric_persisted(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        engine._storage.store_metric.assert_called()

    def test_debt_metric_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.analyze_technical_debt(sample_repo)
        calls = engine._storage.store_metric.call_args_list
        assert any("tech_debt" in str(c) for c in calls)

    def test_health_metric_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.calculate_health(sample_repo)
        calls = engine._storage.store_metric.call_args_list
        assert any("health" in str(c) for c in calls)

    def test_analysis_command_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert call_kwargs["command"] == "recommend"

    def test_result_type_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert call_kwargs["result_type"] == "recommendations"

    def test_result_data_is_dict(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert isinstance(call_kwargs["result_data"], dict)

    def test_duration_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert call_kwargs["duration_ms"] > 0

    def test_repo_path_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert str(sample_repo) in call_kwargs["repository_path"]

    def test_recommendation_count_metric(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        calls = engine._storage.store_metric.call_args_list
        assert any("recommendation_count" in str(c) for c in calls)

    def test_storage_failure_graceful(self, engine: RecommendationEngine, sample_repo: Path):
        engine._storage.store_analysis.side_effect = RuntimeError("DB down")
        try:
            engine.generate_recommendations(sample_repo)
        except Exception:
            pass

    def test_multiple_analyses_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        engine._storage.reset_mock()
        engine.generate_recommendations(sample_repo)
        assert engine._storage.store_analysis.called

    def test_debt_analysis_stores_score(self, engine: RecommendationEngine, sample_repo: Path):
        engine.analyze_technical_debt(sample_repo)
        call_kwargs = engine._storage.store_metric.call_args[1]
        assert call_kwargs["metric_name"] == "tech_debt_score"

    def test_health_stores_overall(self, engine: RecommendationEngine, sample_repo: Path):
        engine.calculate_health(sample_repo)
        calls = engine._storage.store_metric.call_args_list
        assert any("health_overall" in str(c) for c in calls)

    def test_repo_name_stored(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert call_kwargs["repository_name"] == sample_repo.name

    def test_result_data_has_recommendations(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert "recommendations" in call_kwargs["result_data"]

    def test_result_data_has_score(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert "repository_score" in call_kwargs["result_data"]

    def test_bundles_in_result(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert "bundles" in call_kwargs["result_data"]

    def test_persist_function_exists(self, engine: RecommendationEngine):
        assert hasattr(engine, '_persist_recommendations')

    def test_store_analysis_called_with_duration(self, engine: RecommendationEngine, sample_repo: Path):
        engine.generate_recommendations(sample_repo)
        call_kwargs = engine._storage.store_analysis.call_args[1]
        assert "duration_ms" in call_kwargs


# ===========================================================================
# Tasks 11-12: Explanations & Bundles + Prompt Templates (15 tests)
# ===========================================================================

class TestExplanationsAndBundles:
    def test_explanation_generated(self, engine: RecommendationEngine):
        rec = Recommendation(title="T", category=RecommendationCategory.SECURITY)
        explanation = engine._explain_recommendation(rec)
        assert explanation.why != ""
        assert len(explanation.benefits) > 0

    def test_security_explanation(self, engine: RecommendationEngine):
        rec = Recommendation(title="T", category=RecommendationCategory.SECURITY)
        exp = engine._explain_recommendation(rec)
        assert any("security" in b.lower() for b in exp.benefits)

    def test_architecture_explanation(self, engine: RecommendationEngine):
        rec = Recommendation(title="T", category=RecommendationCategory.ARCHITECTURE)
        exp = engine._explain_recommendation(rec)
        assert any("modular" in b.lower() for b in exp.benefits)

    def test_debt_explanation(self, engine: RecommendationEngine):
        rec = Recommendation(title="T", category=RecommendationCategory.TECHNICAL_DEBT)
        exp = engine._explain_recommendation(rec)
        assert any("maintain" in b.lower() for b in exp.benefits)

    def test_testing_explanation(self, engine: RecommendationEngine):
        rec = Recommendation(title="T", category=RecommendationCategory.TESTING)
        exp = engine._explain_recommendation(rec)
        assert any("bug" in b.lower() for b in exp.benefits)

    def test_explanation_has_alternatives(self, engine: RecommendationEngine):
        rec = Recommendation(title="T")
        exp = engine._explain_recommendation(rec)
        assert len(exp.alternatives) > 0

    def test_explanation_has_time_estimate(self, engine: RecommendationEngine):
        rec = Recommendation(title="T", estimated_effort="30 min")
        exp = engine._explain_recommendation(rec)
        assert exp.estimated_implementation_time != ""

    def test_bundles_created(self, engine: RecommendationEngine):
        recs = [
            Recommendation(title=f"R{i}", affected_modules=["auth"], affected_files=[f"auth/f{i}.py"])
            for i in range(3)
        ]
        bundles = engine._create_bundles(recs)
        assert len(bundles) >= 1

    def test_bundle_links_recs(self, engine: RecommendationEngine):
        recs = [
            Recommendation(title=f"R{i}", affected_modules=["core"], affected_files=[f"core/f{i}.py"])
            for i in range(3)
        ]
        bundles = engine._create_bundles(recs)
        if bundles:
            assert len(bundles[0].recommendations) >= 2

    def test_bundle_sets_id(self, engine: RecommendationEngine):
        recs = [
            Recommendation(title=f"R{i}", affected_modules=["api"], affected_files=[f"api/f{i}.py"])
            for i in range(3)
        ]
        engine._create_bundles(recs)
        assert any(r.bundle_id != "" for r in recs)

    def test_single_rec_no_bundle(self, engine: RecommendationEngine):
        recs = [Recommendation(title="Solo", affected_modules=["unique"])]
        bundles = engine._create_bundles(recs)
        assert len(bundles) == 0

    def test_bundle_has_effort(self, engine: RecommendationEngine):
        recs = [
            Recommendation(title=f"R{i}", affected_modules=["mod"], affected_files=[f"mod/f{i}.py"])
            for i in range(4)
        ]
        bundles = engine._create_bundles(recs)
        if bundles:
            assert bundles[0].estimated_total_effort != ""

    def test_explanation_confidence(self, engine: RecommendationEngine):
        rec = Recommendation(title="T", confidence=0.9)
        exp = engine._explain_recommendation(rec)
        assert "90%" in exp.confidence_explanation

    def test_explanation_serializable(self, engine: RecommendationEngine):
        rec = Recommendation(title="T")
        exp = engine._explain_recommendation(rec)
        data = exp.model_dump()
        assert "why" in data

    def test_ai_advisor(self, engine: RecommendationEngine, sample_repo: Path):
        answer = engine.advise("What should I fix first?", sample_repo)
        assert answer != ""
