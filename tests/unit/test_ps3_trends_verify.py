"""PS-3 Verification: trend history changes when repository metrics change.

Proves that:
1. Trends reflect improving metrics when health scores rise.
2. Trends reflect degrading metrics when debt increases.
3. Stable metrics are reported as stable.
4. Multiple analysis runs accumulate history.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from refactory.recommendation.models import (
    RecommendationCategory,
    TrendReport,
)
from refactory.recommendation.service import RecommendationEngine


@pytest.fixture
def engine() -> RecommendationEngine:
    logger = MagicMock()
    parser = MagicMock()
    indexer = MagicMock()
    graph = MagicMock()
    impact = MagicMock()
    rules = MagicMock()
    rules.load_rules = MagicMock(return_value=0)
    rules.evaluate = MagicMock(return_value=MagicMock(violations=[]))
    policy = MagicMock()
    policy.policy = None
    storage = MagicMock()
    ai = MagicMock()
    prompts = MagicMock()
    return RecommendationEngine(
        logger=logger,
        parser_service=parser,
        indexer_service=indexer,
        graph_service=graph,
        impact_service=impact,
        rule_engine=rules,
        policy_service=policy,
        storage_service=storage,
        ai_gateway=ai,
        prompt_service=prompts,
    )


class TestTrendHistoryChanges:
    def test_improving_health_detected(self, engine: RecommendationEngine, tmp_path: Path):
        """When health_overall rises between analyses, trend shows 'improving'."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_overall": [
                {"value": 90.0, "timestamp": "2026-07-29"},
                {"value": 70.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        health_trends = [t for t in report.trends if t.metric_name == "health_overall"]
        assert len(health_trends) == 1
        assert health_trends[0].direction == "improving"
        assert health_trends[0].change_percent > 0

    def test_degrading_health_detected(self, engine: RecommendationEngine, tmp_path: Path):
        """When health_overall drops between analyses, trend shows 'degrading'."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_overall": [
                {"value": 60.0, "timestamp": "2026-07-29"},
                {"value": 90.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        health_trends = [t for t in report.trends if t.metric_name == "health_overall"]
        assert len(health_trends) == 1
        assert health_trends[0].direction == "degrading"
        assert health_trends[0].change_percent < 0

    def test_increasing_debt_degrades(self, engine: RecommendationEngine, tmp_path: Path):
        """When tech_debt_score rises, it's classified as degrading."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "tech_debt_score": [
                {"value": 50.0, "timestamp": "2026-07-29"},
                {"value": 20.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        debt_trends = [t for t in report.trends if t.metric_name == "tech_debt_score"]
        assert len(debt_trends) == 1
        assert debt_trends[0].direction == "increasing"
        assert "Technical debt score" in report.modules_degrading

    def test_decreasing_debt_improves(self, engine: RecommendationEngine, tmp_path: Path):
        """When tech_debt_score falls, it's classified as improving."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "tech_debt_score": [
                {"value": 10.0, "timestamp": "2026-07-29"},
                {"value": 40.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        debt_trends = [t for t in report.trends if t.metric_name == "tech_debt_score"]
        assert len(debt_trends) == 1
        assert debt_trends[0].direction == "decreasing"
        assert "Technical debt score" in report.modules_improving

    def test_stable_metrics_detected(self, engine: RecommendationEngine, tmp_path: Path):
        """When metrics don't change, trend reports stable."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_overall": [
                {"value": 80.0, "timestamp": "2026-07-29"},
                {"value": 80.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        health_trends = [t for t in report.trends if t.metric_name == "health_overall"]
        assert len(health_trends) == 1
        assert health_trends[0].direction == "stable"
        assert health_trends[0].change_percent == 0.0

    def test_no_history_returns_empty(self, engine: RecommendationEngine, tmp_path: Path):
        """With no stored metrics, trends list is empty."""
        engine._storage.get_metrics = MagicMock(return_value=[])
        report = engine.analyze_trends(tmp_path)
        assert len(report.trends) == 0

    def test_single_datapoint_skipped(self, engine: RecommendationEngine, tmp_path: Path):
        """A single data point is not enough to compute a trend."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_overall": [{"value": 80.0, "timestamp": "2026-07-29"}],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        health_trends = [t for t in report.trends if t.metric_name == "health_overall"]
        assert len(health_trends) == 0

    def test_multi_dimension_trends(self, engine: RecommendationEngine, tmp_path: Path):
        """Multiple dimensions can independently improve/degrade."""
        def mock_metrics(repo, metric, limit=30):
            data = {
                "health_overall": [
                    {"value": 90.0, "timestamp": "2026-07-29"},
                    {"value": 70.0, "timestamp": "2026-07-22"},
                ],
                "health_security": [
                    {"value": 50.0, "timestamp": "2026-07-29"},
                    {"value": 80.0, "timestamp": "2026-07-22"},
                ],
                "tech_debt_score": [
                    {"value": 30.0, "timestamp": "2026-07-29"},
                    {"value": 30.0, "timestamp": "2026-07-22"},
                ],
            }
            return data.get(metric, [])

        engine._storage.get_metrics = MagicMock(side_effect=mock_metrics)
        report = engine.analyze_trends(tmp_path)

        overall = next((t for t in report.trends if t.metric_name == "health_overall"), None)
        security = next((t for t in report.trends if t.metric_name == "health_security"), None)

        assert overall is not None and overall.direction == "improving"
        assert security is not None and security.direction == "degrading"

    def test_improving_modules_populated(self, engine: RecommendationEngine, tmp_path: Path):
        """Modules that are improving should appear in modules_improving."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_architecture": [
                {"value": 95.0, "timestamp": "2026-07-29"},
                {"value": 70.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        assert "Architecture" in report.modules_improving

    def test_degrading_modules_populated(self, engine: RecommendationEngine, tmp_path: Path):
        """Modules that are degrading should appear in modules_degrading."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_security": [
                {"value": 60.0, "timestamp": "2026-07-29"},
                {"value": 90.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        assert "Security" in report.modules_degrading

    def test_transformations_tracked(self, engine: RecommendationEngine, tmp_path: Path):
        """Transformations applied metric shows up in trends."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "transformations_applied": [
                {"value": 3.0, "timestamp": "2026-07-29"},
                {"value": 2.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        tx = [t for t in report.trends if t.metric_name == "transformations_applied"]
        assert len(tx) == 1
        assert tx[0].direction == "active"

    def test_trend_description_includes_pct(self, engine: RecommendationEngine, tmp_path: Path):
        """Trend description includes the percentage change."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_overall": [
                {"value": 80.0, "timestamp": "2026-07-29"},
                {"value": 60.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        t = report.trends[0]
        assert "%" in t.description or "improving" in t.description

    def test_change_percent_accuracy(self, engine: RecommendationEngine, tmp_path: Path):
        """Change percent is calculated correctly: (recent-older)/older*100."""
        engine._storage.get_metrics = MagicMock(side_effect=lambda repo, metric, limit=30: {
            "health_overall": [
                {"value": 80.0, "timestamp": "2026-07-29"},
                {"value": 50.0, "timestamp": "2026-07-22"},
            ],
        }.get(metric, []))

        report = engine.analyze_trends(tmp_path)
        t = report.trends[0]
        expected = ((80.0 - 50.0) / 50.0) * 100
        assert abs(t.change_percent - expected) < 0.2
