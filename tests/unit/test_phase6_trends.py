"""Tests for Phase 6: PS-3 (Trends) + PS-5 (Recommendation enrichment)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.recommendation.models import (
    Recommendation,
    RecommendationCategory,
    RecommendationExplanation,
)
from refactory.recommendation.service import RecommendationEngine


def _engine(metric_data=None):
    storage = MagicMock()
    if metric_data:
        storage.get_metrics.side_effect = lambda path, name, **kw: metric_data.get(name, [])
    else:
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


# ===========================================================================
# PS-3: Historical metrics and trends
# ===========================================================================

class TestTrendsFromStorage:
    def test_trends_with_health_data(self):
        engine = _engine({
            "health_overall": [{"value": 90}, {"value": 80}],
        })
        report = engine.analyze_trends(Path("/repo"))
        assert len(report.trends) >= 1
        health_trend = next(t for t in report.trends if t.metric_name == "health_overall")
        assert health_trend.direction == "improving"

    def test_trends_degrading_security(self):
        engine = _engine({
            "health_security": [{"value": 60}, {"value": 80}],
        })
        report = engine.analyze_trends(Path("/repo"))
        sec = next(t for t in report.trends if t.metric_name == "health_security")
        assert sec.direction == "degrading"
        assert "Security" in report.modules_degrading

    def test_trends_improving_testing(self):
        engine = _engine({
            "health_testing": [{"value": 90}, {"value": 70}],
        })
        report = engine.analyze_trends(Path("/repo"))
        test_trend = next(t for t in report.trends if t.metric_name == "health_testing")
        assert test_trend.direction == "improving"
        assert "Testing" in report.modules_improving

    def test_trends_stable(self):
        engine = _engine({
            "health_overall": [{"value": 80}, {"value": 80}],
        })
        report = engine.analyze_trends(Path("/repo"))
        assert report.trends[0].direction == "stable"

    def test_trends_transformations_tracked(self):
        engine = _engine({
            "transformations_applied": [{"value": 1}, {"value": 1}],
        })
        report = engine.analyze_trends(Path("/repo"))
        tf = next((t for t in report.trends if t.metric_name == "transformations_applied"), None)
        assert tf is not None
        assert "2 transformations" in tf.description

    def test_trends_empty_returns_empty(self):
        engine = _engine()
        report = engine.analyze_trends(Path("/repo"))
        assert len(report.trends) == 0

    def test_trends_multi_dimension(self):
        engine = _engine({
            "health_overall": [{"value": 90}, {"value": 80}],
            "health_security": [{"value": 95}, {"value": 70}],
            "health_testing": [{"value": 60}, {"value": 80}],
        })
        report = engine.analyze_trends(Path("/repo"))
        assert len(report.trends) >= 3


# ===========================================================================
# PS-5: Enriched Recommendations
# ===========================================================================

class TestEnrichedRecommendations:
    def test_score_includes_severity(self):
        engine = _engine()
        high = Recommendation(
            title="T", severity="high",
            category=RecommendationCategory.SECURITY, confidence=0.9,
        )
        low = Recommendation(
            title="T", severity="low",
            category=RecommendationCategory.SECURITY, confidence=0.9,
        )
        assert engine._score_recommendation(high) > engine._score_recommendation(low)

    def test_score_transformation_bonus(self):
        engine = _engine()
        with_transform = Recommendation(
            title="T", category=RecommendationCategory.TECHNICAL_DEBT,
            confidence=0.8, transformation_type="refactor",
            estimated_patch_size=50,
        )
        without_transform = Recommendation(
            title="T", category=RecommendationCategory.TECHNICAL_DEBT,
            confidence=0.8,
        )
        assert engine._score_recommendation(with_transform) > engine._score_recommendation(without_transform)

    def test_explanation_includes_auto_fix(self):
        engine = _engine()
        rec = Recommendation(
            title="T", category=RecommendationCategory.TECHNICAL_DEBT,
            transformation_type="refactor", estimated_patch_size=30,
        )
        explanation = engine._explain_recommendation(rec)
        assert any("Auto-fixable" in b for b in explanation.benefits)

    def test_explanation_documentation_benefits(self):
        engine = _engine()
        rec = Recommendation(
            title="T", category=RecommendationCategory.DOCUMENTATION,
            transformation_type="doc_generation",
        )
        explanation = engine._explain_recommendation(rec)
        assert any("onboarding" in b.lower() for b in explanation.benefits)

    def test_explanation_rule_violations(self):
        engine = _engine()
        rec = Recommendation(
            title="T", category=RecommendationCategory.RULE_VIOLATIONS,
            transformation_type="rule_fix",
        )
        explanation = engine._explain_recommendation(rec)
        assert any("consistency" in b.lower() for b in explanation.benefits)

    def test_explanation_patch_size_tradeoff(self):
        engine = _engine()
        rec = Recommendation(
            title="T", category=RecommendationCategory.TECHNICAL_DEBT,
            transformation_type="refactor", estimated_patch_size=50,
        )
        explanation = engine._explain_recommendation(rec)
        assert any("50 lines" in t for t in explanation.tradeoffs)

    def test_debt_recs_have_transform_type(self, tmp_path: Path):
        engine = _engine()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "big.py").write_text("\n" * 600)
        (repo / "tests" / "unit").mkdir(parents=True)
        recs = engine._debt_recommendations(repo)
        for rec in recs:
            assert rec.transformation_type == "refactor"
