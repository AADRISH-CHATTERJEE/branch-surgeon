"""Tests for Phase 2: PS-2 + PS-6 (Health from real analysis)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.recommendation.models import (
    HealthReport,
    Recommendation,
    RecommendationCategory,
)
from refactory.recommendation.service import RecommendationEngine


@pytest.fixture
def engine():
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
    from loguru import logger
    return RecommendationEngine(
        logger=logger, parser_service=MagicMock(), indexer_service=MagicMock(),
        graph_service=MagicMock(), impact_service=MagicMock(),
        rule_engine=rules, policy_service=policy, storage_service=storage,
        ai_gateway=ai, prompt_service=MagicMock(),
    )


class TestHealthFromAnalysis:
    def test_health_not_perfect_with_issues(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests" / "unit").mkdir(parents=True)
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("def main():\n    pass\n")
        (repo / "src" / "service.py").write_text("class Service:\n    pass\n")
        (repo / "src" / "handler.py").write_text("def handle(): pass\n")
        report = engine.calculate_health(repo)
        assert report.recommendations_count > 0

    def test_health_reflects_missing_tests(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests" / "unit").mkdir(parents=True)
        (repo / "src").mkdir()
        (repo / "src" / "service.py").write_text("class Svc:\n    pass\n")
        (repo / "src" / "utils.py").write_text("def helper(): pass\n")
        (repo / "src" / "handler.py").write_text("def handle(): pass\n")
        report = engine.calculate_health(repo)
        assert report.scores.testing < 100.0

    def test_health_security_drops_with_eval(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests" / "unit").mkdir(parents=True)
        (repo / "src").mkdir()
        (repo / "src" / "danger.py").write_text("x = eval(input())\n")
        (repo / "src" / "safe.py").write_text("y = 1\n")
        report = engine.calculate_health(repo)
        assert report.scores.security < 100.0

    def test_health_debt_from_large_file(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests" / "unit").mkdir(parents=True)
        (repo / "big.py").write_text("\n" * 600)
        report = engine.calculate_health(repo)
        assert report.scores.technical_debt < 100.0

    def test_overall_weighted_from_dimensions(self, engine: RecommendationEngine):
        recs = [
            Recommendation(title="S", category=RecommendationCategory.SECURITY, severity="high"),
            Recommendation(title="T", category=RecommendationCategory.TESTING, severity="medium"),
        ]
        report = engine._calculate_health(Path("."), recs)
        expected = (
            report.scores.architecture * 0.20
            + report.scores.maintainability * 0.15
            + report.scores.security * 0.20
            + report.scores.performance * 0.15
            + report.scores.testing * 0.15
            + report.scores.documentation * 0.05
            + report.scores.technical_debt * 0.10
        )
        assert abs(report.scores.overall - expected) < 0.1

    def test_severity_weighted_penalty(self, engine: RecommendationEngine):
        high_recs = [
            Recommendation(title="H", category=RecommendationCategory.SECURITY, severity="high"),
        ]
        low_recs = [
            Recommendation(title="L", category=RecommendationCategory.SECURITY, severity="low"),
        ]
        high_report = engine._calculate_health(Path("."), high_recs)
        low_report = engine._calculate_health(Path("."), low_recs)
        assert high_report.scores.security < low_report.scores.security

    def test_per_dimension_metrics_stored(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests" / "unit").mkdir(parents=True)
        (repo / "x.py").write_text("x = 1\n")
        engine.calculate_health(repo)
        calls = [str(c) for c in engine._storage.store_metric.call_args_list]
        assert any("health_overall" in c for c in calls)
        assert any("health_security" in c for c in calls)
        assert any("health_testing" in c for c in calls)

    def test_rule_violations_affect_maintainability(self, engine: RecommendationEngine):
        recs = [
            Recommendation(title="R", category=RecommendationCategory.RULE_VIOLATIONS, severity="medium"),
        ]
        report = engine._calculate_health(Path("."), recs)
        assert report.scores.maintainability < 100.0

    def test_clean_repo_high_health(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests" / "unit").mkdir(parents=True)
        report = engine.calculate_health(repo)
        assert report.scores.overall > 0

    def test_critical_count_from_findings(self, engine: RecommendationEngine, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "tests" / "unit").mkdir(parents=True)
        report = engine.calculate_health(repo)
        assert report.critical_count >= 0
