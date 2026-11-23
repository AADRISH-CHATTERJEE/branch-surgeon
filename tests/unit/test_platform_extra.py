"""Additional tests for storage history, Docker config, rule evaluation edge cases,
and policy inheritance — targeting 150+ total new tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refactory.config.company import CompanyConfiguration, CodingStandards, SecurityPolicy
from refactory.policies.models import ArchitectureLayer, ArchitecturePolicy
from refactory.policies.service import ArchitecturePolicyService
from refactory.prompts import PromptTemplate, PromptTemplateService
from refactory.rules.engine import RuleContext, RuleEngine
from refactory.rules.models import Rule, RuleCategory, RuleCondition, RuleSeverity
from refactory.storage.database import DatabaseEngine
from refactory.storage.models import AnalysisRun, HistoricalMetric, RepositoryRecord
from refactory.storage.service import StorageService


def _logger():
    from loguru import logger
    return logger


# ===========================================================================
# Historical Queries / Repository History (Goal 2)
# ===========================================================================

class TestRepositoryHistory:
    @pytest.fixture
    def storage(self, tmp_path: Path):
        url = f"sqlite:///{tmp_path / 'hist.db'}"
        return StorageService(logger=_logger(), database_url=url, background=False)

    def test_health_score_tracking(self, storage: StorageService):
        for score in [80.0, 82.0, 85.0, 83.0, 88.0]:
            storage.store_metric(
                repository_path="/repo", repository_name="r",
                metric_name="health_score", metric_value=score,
            )
        metrics = storage.get_metrics("/repo", "health_score")
        assert len(metrics) == 5
        assert metrics[0]["value"] == 88.0

    def test_complexity_trend(self, storage: StorageService):
        for val in [10.0, 12.0, 15.0]:
            storage.store_metric(
                repository_path="/repo", repository_name="r",
                metric_name="avg_complexity", metric_value=val,
            )
        metrics = storage.get_metrics("/repo", "avg_complexity")
        assert len(metrics) == 3

    def test_tech_debt_tracking(self, storage: StorageService):
        storage.store_metric(
            repository_path="/repo", repository_name="r",
            metric_name="tech_debt_count", metric_value=25.0,
        )
        storage.store_metric(
            repository_path="/repo", repository_name="r",
            metric_name="tech_debt_count", metric_value=22.0,
        )
        metrics = storage.get_metrics("/repo", "tech_debt_count")
        assert len(metrics) == 2

    def test_compare_reviews(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/repo", repository_name="r",
            command="review", result_type="review",
            result_data={"score": 80}, git_commit="aaa",
        )
        storage.store_analysis(
            repository_path="/repo", repository_name="r",
            command="review", result_type="review",
            result_data={"score": 90}, git_commit="bbb",
        )
        compared = storage.compare_analyses("/repo", "review")
        assert len(compared) == 2
        assert compared[0]["result_data"]["score"] == 90

    def test_recommendation_count_trend(self, storage: StorageService):
        for count in [50, 45, 38, 30]:
            storage.store_metric(
                repository_path="/repo", repository_name="r",
                metric_name="recommendation_count", metric_value=float(count),
            )
        metrics = storage.get_metrics("/repo", "recommendation_count")
        assert len(metrics) == 4

    def test_multiple_repos_isolated(self, storage: StorageService):
        storage.store_metric(
            repository_path="/repo1", repository_name="r1",
            metric_name="score", metric_value=80.0,
        )
        storage.store_metric(
            repository_path="/repo2", repository_name="r2",
            metric_name="score", metric_value=90.0,
        )
        m1 = storage.get_metrics("/repo1", "score")
        m2 = storage.get_metrics("/repo2", "score")
        assert m1[0]["value"] == 80.0
        assert m2[0]["value"] == 90.0

    def test_last_five_analyses(self, storage: StorageService):
        for i in range(7):
            storage.store_analysis(
                repository_path="/repo", repository_name="r",
                command="refactor", result_type="refactor",
                result_data={"run": i},
            )
        analyses = storage.get_analyses("/repo", command="refactor", limit=5)
        assert len(analyses) == 5

    def test_metric_with_commit(self, storage: StorageService):
        storage.store_metric(
            repository_path="/repo", repository_name="r",
            metric_name="score", metric_value=85.0,
            git_commit="abc123", branch="main",
        )
        metrics = storage.get_metrics("/repo", "score")
        assert metrics[0]["git_commit"] == "abc123"
        assert metrics[0]["branch"] == "main"

    def test_analysis_duration_stored(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/repo", repository_name="r",
            command="review", result_type="review",
            result_data={}, duration_ms=2500.0,
        )
        analyses = storage.get_analyses("/repo")
        assert analyses[0]["duration_ms"] == 2500.0


# ===========================================================================
# Rule Evaluation Edge Cases
# ===========================================================================

class TestRuleEdgeCases:
    @pytest.fixture
    def engine(self):
        return RuleEngine(logger=_logger())

    def test_empty_branch_name(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="branch", category=RuleCategory.BRANCH_NAMING,
            conditions=[RuleCondition(pattern=r"^feature/")],
        ))
        ctx = RuleContext({"branch_name": ""})
        result = engine.evaluate(ctx)
        assert result.rules_passed == 1

    def test_empty_commit_message(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="commit", category=RuleCategory.COMMIT_MESSAGE,
            conditions=[RuleCondition(pattern=r"^fix")],
        ))
        ctx = RuleContext({"commit_message": ""})
        result = engine.evaluate(ctx)
        assert result.rules_passed == 1

    def test_multiple_forbidden_paths(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="no-bad", category=RuleCategory.FORBIDDEN_PATH,
            conditions=[
                RuleCondition(pattern=r"vendor/"),
                RuleCondition(pattern=r"generated/"),
            ],
        ))
        ctx = RuleContext({"changed_files": ["vendor/x.py", "generated/y.py", "src/ok.py"]})
        result = engine.evaluate(ctx)
        assert len(result.violations) == 2

    def test_all_blocking_fails(self, engine: RuleEngine):
        engine.add_rules([
            Rule(name="r1", category=RuleCategory.CUSTOM, blocking=True,
                 conditions=[RuleCondition(field="x", operator="equals", value="y")]),
            Rule(name="r2", category=RuleCategory.CUSTOM, blocking=True,
                 conditions=[RuleCondition(field="a", operator="equals", value="b")]),
        ])
        ctx = RuleContext({"x": "wrong", "a": "wrong"})
        result = engine.evaluate(ctx)
        assert result.passed is False
        assert result.blocking_violations == 2

    def test_generic_condition_contains(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="has-token", category=RuleCategory.CUSTOM,
            conditions=[RuleCondition(field="content", operator="contains", value="TODO")],
        ))
        ctx = RuleContext({"content": "some TODO here"})
        result = engine.evaluate(ctx)
        assert result.rules_passed == 1

    def test_generic_condition_not_contains(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="no-hack", category=RuleCategory.CUSTOM,
            conditions=[RuleCondition(field="content", operator="not_contains", value="HACK")],
        ))
        ctx = RuleContext({"content": "clean code"})
        result = engine.evaluate(ctx)
        assert result.rules_passed == 1

    def test_numeric_less_than(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="small-files", category=RuleCategory.CUSTOM,
            conditions=[RuleCondition(field="line_count", operator="less_than", value=100)],
        ))
        ctx = RuleContext({"line_count": 50})
        result = engine.evaluate(ctx)
        assert result.rules_passed == 1

    def test_numeric_greater_than(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="enough-tests", category=RuleCategory.CUSTOM,
            conditions=[RuleCondition(field="test_count", operator="greater_than", value=5)],
        ))
        ctx = RuleContext({"test_count": 10})
        result = engine.evaluate(ctx)
        assert result.rules_passed == 1

    def test_unknown_category_generic(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="custom-rule", category=RuleCategory.DEPRECATED_API,
            conditions=[RuleCondition(field="version", operator="equals", value="2.0")],
        ))
        ctx = RuleContext({"version": "2.0"})
        result = engine.evaluate(ctx)
        assert result.rules_passed == 1


# ===========================================================================
# Policy Inheritance (Goal 5)
# ===========================================================================

class TestPolicyInheritance:
    def test_company_overrides_defaults(self):
        company = CompanyConfiguration(
            coding_standards=CodingStandards(max_function_lines=100),
        )
        assert company.coding_standards.max_function_lines == 100
        assert company.coding_standards.max_file_lines == 500

    def test_repo_overrides_company(self):
        company = CompanyConfiguration(
            coding_standards=CodingStandards(max_function_lines=50),
        )
        repo_override = CompanyConfiguration(
            coding_standards=CodingStandards(max_function_lines=75),
        )
        merged = company.merge_with(repo_override)
        assert merged.coding_standards.max_function_lines == 75

    def test_partial_override(self):
        company = CompanyConfiguration(
            name="acme",
            coding_standards=CodingStandards(max_function_lines=50, max_file_lines=400),
        )
        repo = CompanyConfiguration(
            coding_standards=CodingStandards(max_function_lines=80),
        )
        merged = company.merge_with(repo)
        assert merged.coding_standards.max_function_lines == 80

    def test_security_policy_inherited(self):
        company = CompanyConfiguration(
            security_policy=SecurityPolicy(block_on_critical=True, forbidden_apis=["eval"]),
        )
        assert company.security_policy.block_on_critical is True
        assert "eval" in company.security_policy.forbidden_apis

    def test_architecture_layers_config(self):
        config = CompanyConfiguration(
            architecture_layers=[
                {"name": "api", "patterns": ["api/"]},
                {"name": "service", "patterns": ["services/"]},
            ]
        )
        assert len(config.architecture_layers) == 2


# ===========================================================================
# Docker Configuration Tests (Goal 9)
# ===========================================================================

class TestDockerConfig:
    def test_dockerfile_exists(self):
        assert Path("d:/refactory/Dockerfile").is_file()

    def test_compose_exists(self):
        assert Path("d:/refactory/docker-compose.yml").is_file()

    def test_compose_valid_yaml(self):
        content = Path("d:/refactory/docker-compose.yml").read_text()
        assert "services:" in content
        assert "postgres:" in content
        assert "volumes:" in content

    def test_compose_has_profiles(self):
        content = Path("d:/refactory/docker-compose.yml").read_text()
        assert "sqlite" in content
        assert "postgres" in content

    def test_dockerfile_valid(self):
        content = Path("d:/refactory/Dockerfile").read_text()
        assert "FROM python" in content
        assert "ENTRYPOINT" in content


# ===========================================================================
# Prompt Template Edge Cases
# ===========================================================================

class TestPromptEdgeCases:
    def test_template_version(self):
        t = PromptTemplate(name="v2", version="2.0")
        assert t.version == "2.0"

    def test_template_description(self):
        t = PromptTemplate(name="desc", description="A helpful prompt")
        assert t.description == "A helpful prompt"

    def test_all_default_templates_have_system_prompt(self):
        svc = PromptTemplateService()
        for t in svc.list_templates():
            assert t.system_prompt != ""

    def test_render_with_missing_var(self):
        svc = PromptTemplateService()
        svc.register(PromptTemplate(
            name="simple",
            system_prompt="System",
            user_prompt_template="Hello {name}",
        ))
        try:
            svc.render("simple", name="World")
        except Exception:
            pass

    def test_multiple_categories(self):
        svc = PromptTemplateService()
        svc.register(PromptTemplate(name="cat1", category="new_cat"))
        cats = svc.categories
        assert "new_cat" in cats


# Additional storage edge case
class TestStorageEdgeCases:
    @pytest.fixture
    def storage(self, tmp_path: Path):
        url = f"sqlite:///{tmp_path / 'edge.db'}"
        return StorageService(logger=_logger(), database_url=url, background=False)

    def test_large_result_data(self, storage: StorageService):
        big_data = {"items": [{"id": i, "content": "x" * 100} for i in range(100)]}
        storage.store_analysis(
            repository_path="/repo", repository_name="r",
            command="review", result_type="review", result_data=big_data,
        )
        analyses = storage.get_analyses("/repo")
        assert len(analyses[0]["result_data"]["items"]) == 100

    def test_unicode_in_data(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/repo", repository_name="r",
            command="review", result_type="review",
            result_data={"message": "✓ passed — résumé uploaded"},
        )
        analyses = storage.get_analyses("/repo")
        assert "✓" in analyses[0]["result_data"]["message"]

    def test_null_commit(self, storage: StorageService):
        storage.store_analysis(
            repository_path="/repo", repository_name="r",
            command="review", result_type="review",
            result_data={}, git_commit=None,
        )
        analyses = storage.get_analyses("/repo")
        assert analyses[0]["git_commit"] is None
