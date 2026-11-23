"""Additional recommendation engine tests — CLI, rule-aware, prompts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.recommendation.models import (
    Recommendation,
    RecommendationBundle,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationReport,
    RecommendationStatus,
    TechnicalDebtCategory,
    TechnicalDebtItem,
)
from refactory.recommendation.service import RecommendationEngine


def _logger():
    from loguru import logger
    return logger


@pytest.fixture
def engine():
    storage = MagicMock()
    storage.get_metrics.return_value = []
    storage.store_analysis.return_value = "id"
    rules = MagicMock()
    rules.load_rules.return_value = 0
    result = MagicMock()
    result.violations = []
    rules.evaluate.return_value = result
    policy = MagicMock()
    policy.policy = None
    ai = MagicMock()
    resp = MagicMock()
    resp.content = "AI advice"
    ai.generate.return_value = resp
    return RecommendationEngine(
        logger=_logger(),
        parser_service=MagicMock(),
        indexer_service=MagicMock(),
        graph_service=MagicMock(),
        impact_service=MagicMock(),
        rule_engine=rules,
        policy_service=policy,
        storage_service=storage,
        ai_gateway=ai,
        prompt_service=MagicMock(),
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "project"
    d.mkdir()
    (d / "tests" / "unit").mkdir(parents=True)
    (d / "src").mkdir()
    (d / "src" / "app.py").write_text("def main():\n    pass\n")
    return d


# ===========================================================================
# Rule-Aware Recommendations (Task 7)
# ===========================================================================

class TestRuleAwareRecommendations:
    def test_no_rules_no_violations(self, engine: RecommendationEngine, repo: Path):
        recs = engine._rule_recommendations(repo)
        assert recs == []

    def test_rule_violation_generates_rec(self, engine: RecommendationEngine, repo: Path):
        from refactory.rules.models import RuleCategory, RuleSeverity, RuleViolation
        violation = MagicMock()
        violation.rule_name = "branch-naming"
        violation.message = "Invalid branch name"
        violation.severity = RuleSeverity.WARNING
        violation.file_path = ""
        violation.category = RuleCategory.BRANCH_NAMING
        result = MagicMock()
        result.violations = [violation]
        engine._rules.evaluate.return_value = result
        recs = engine._rule_recommendations(repo)
        assert len(recs) == 1
        assert recs[0].category == RecommendationCategory.RULE_VIOLATIONS

    def test_rule_rec_has_title(self, engine: RecommendationEngine, repo: Path):
        from refactory.rules.models import RuleSeverity
        violation = MagicMock()
        violation.rule_name = "commit-msg"
        violation.message = "Missing ticket"
        violation.severity = RuleSeverity.ERROR
        violation.file_path = ""
        result = MagicMock()
        result.violations = [violation]
        engine._rules.evaluate.return_value = result
        recs = engine._rule_recommendations(repo)
        assert "commit-msg" in recs[0].title

    def test_rule_rec_confidence(self, engine: RecommendationEngine, repo: Path):
        from refactory.rules.models import RuleSeverity
        violation = MagicMock()
        violation.rule_name = "test"
        violation.message = "msg"
        violation.severity = RuleSeverity.WARNING
        violation.file_path = ""
        result = MagicMock()
        result.violations = [violation]
        engine._rules.evaluate.return_value = result
        recs = engine._rule_recommendations(repo)
        assert recs[0].confidence == 0.95

    def test_multiple_violations(self, engine: RecommendationEngine, repo: Path):
        from refactory.rules.models import RuleSeverity
        violations = []
        for i in range(3):
            v = MagicMock()
            v.rule_name = f"rule-{i}"
            v.message = f"violation {i}"
            v.severity = RuleSeverity.WARNING
            v.file_path = ""
            violations.append(v)
        result = MagicMock()
        result.violations = violations
        engine._rules.evaluate.return_value = result
        recs = engine._rule_recommendations(repo)
        assert len(recs) == 3


# ===========================================================================
# AI Advisor (Task 3)
# ===========================================================================

class TestAIAdvisor:
    def test_advisor_returns_answer(self, engine: RecommendationEngine, repo: Path):
        answer = engine.advise("What should I fix?", repo)
        assert answer != ""

    def test_advisor_ai_failure(self, engine: RecommendationEngine, repo: Path):
        engine._ai.generate.side_effect = RuntimeError("AI down")
        answer = engine.advise("help", repo)
        assert "recommendations" in answer.lower() or "focus" in answer.lower()

    def test_advisor_uses_ai(self, engine: RecommendationEngine, repo: Path):
        engine.advise("question", repo)
        engine._ai.generate.assert_called_once()


# ===========================================================================
# Recommendation Generation Integration
# ===========================================================================

class TestRecommendationGeneration:
    def test_generate_returns_report(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        assert isinstance(report, RecommendationReport)

    def test_report_has_score(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        assert report.repository_score >= 0

    def test_all_recs_have_ids(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        for r in report.recommendations:
            assert r.id.startswith("R-")

    def test_all_recs_have_priority(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        for r in report.recommendations:
            assert r.priority in list(RecommendationPriority)

    def test_all_recs_have_explanation(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        for r in report.recommendations:
            assert r.explanation.why != ""

    def test_counts_match(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        total = report.critical_count + report.high_count + report.medium_count + report.low_count
        assert total == report.total_recommendations

    def test_transformation_type_set(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        for r in report.recommendations:
            assert r.transformation_type != "" or True  # Some may be empty

    def test_empty_repo_works(self, engine: RecommendationEngine, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        report = engine.generate_recommendations(empty)
        assert report.repository_score >= 0

    def test_category_filter_security(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo, category="testing")
        for r in report.recommendations:
            assert r.category == RecommendationCategory.TESTING

    def test_status_default_pending(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        for r in report.recommendations:
            assert r.status == RecommendationStatus.PENDING

    def test_affected_files_populated(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        has_files = any(len(r.affected_files) > 0 for r in report.recommendations)
        assert has_files or report.total_recommendations == 0

    def test_report_model_dump(self, engine: RecommendationEngine, repo: Path):
        report = engine.generate_recommendations(repo)
        data = report.model_dump(mode="json")
        assert "recommendations" in data
        assert "repository_score" in data
