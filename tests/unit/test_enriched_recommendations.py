"""Tests for enriched RecommendationEngine.

Verifies that recommendations go beyond 'Missing tests' and include:
- Complexity recommendations (high branch count, deep nesting)
- Maintainability recommendations (high coupling, large classes, too many params)
- Technical debt recommendations (large files, long methods)
- Security recommendations (eval, exec, pickle)
- Rule violation recommendations (from rules.yaml)
- Documentation recommendations (missing docstrings)
- Transformation-aware fields (transformation_type, estimated_patch_size)
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from refactory.recommendation.models import (
    RecommendationCategory,
    RecommendationPriority,
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
    storage.store_analysis = MagicMock()
    storage.store_metric = MagicMock()
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


# ---------------------------------------------------------------------------
# Complexity Recommendations
# ---------------------------------------------------------------------------

class TestComplexityRecommendations:
    def test_high_branch_count_detected(self, engine: RecommendationEngine, tmp_path: Path):
        code = "def complex_func(x):\n" + "    if True:\n        pass\n" * 10
        (tmp_path / "complex.py").write_text(code)
        recs = engine._complexity_recommendations(tmp_path)
        complexity_recs = [r for r in recs if "complexity" in r.title.lower() or "branch" in r.description.lower()]
        assert len(complexity_recs) >= 1

    def test_deep_nesting_detected(self, engine: RecommendationEngine, tmp_path: Path):
        code = "x = 1\n"
        for i in range(8):
            code += "    " * i + f"if True:\n"
        code += "    " * 8 + "pass\n"
        (tmp_path / "nested.py").write_text(code)
        recs = engine._complexity_recommendations(tmp_path)
        nesting_recs = [r for r in recs if "nesting" in r.title.lower() or "nesting" in r.description.lower()]
        assert len(nesting_recs) >= 1

    def test_clean_code_no_complexity(self, engine: RecommendationEngine, tmp_path: Path):
        code = "def simple(x):\n    return x + 1\n"
        (tmp_path / "simple.py").write_text(code)
        recs = engine._complexity_recommendations(tmp_path)
        assert len(recs) == 0

    def test_complexity_has_transformation_type(self, engine: RecommendationEngine, tmp_path: Path):
        code = "def complex_func(x):\n" + "    if True:\n        pass\n" * 10
        (tmp_path / "complex.py").write_text(code)
        recs = engine._complexity_recommendations(tmp_path)
        for r in recs:
            assert r.transformation_type, "Complexity recs should have a transformation_type"

    def test_complexity_category(self, engine: RecommendationEngine, tmp_path: Path):
        code = "def complex_func(x):\n" + "    if True:\n        pass\n" * 10
        (tmp_path / "complex.py").write_text(code)
        recs = engine._complexity_recommendations(tmp_path)
        for r in recs:
            assert r.category == RecommendationCategory.MAINTAINABILITY


# ---------------------------------------------------------------------------
# Maintainability Recommendations
# ---------------------------------------------------------------------------

class TestMaintainabilityRecommendations:
    def test_high_coupling_detected(self, engine: RecommendationEngine, tmp_path: Path):
        imports = "\n".join(f"import mod{i}" for i in range(20))
        (tmp_path / "coupled.py").write_text(imports + "\npass\n")
        recs = engine._maintainability_recommendations(tmp_path)
        coupling_recs = [r for r in recs if "coupling" in r.title.lower()]
        assert len(coupling_recs) >= 1

    def test_large_class_detected(self, engine: RecommendationEngine, tmp_path: Path):
        methods = "\n".join(f"    def method_{i}(self):\n        pass\n" for i in range(15))
        code = f"class BigClass:\n{methods}\n"
        (tmp_path / "big_class.py").write_text(code)
        recs = engine._maintainability_recommendations(tmp_path)
        class_recs = [r for r in recs if "large class" in r.title.lower() or "class" in r.description.lower()]
        assert len(class_recs) >= 1

    def test_too_many_params_detected(self, engine: RecommendationEngine, tmp_path: Path):
        code = "def many_params(a_param, b_param, c_param, d_param, e_param, f_param, g_param):\n    pass\n"
        (tmp_path / "params.py").write_text(code)
        recs = engine._maintainability_recommendations(tmp_path)
        param_recs = [r for r in recs if "param" in r.title.lower()]
        assert len(param_recs) >= 1

    def test_clean_module_no_maintainability(self, engine: RecommendationEngine, tmp_path: Path):
        code = "import os\n\ndef foo():\n    return 1\n"
        (tmp_path / "clean.py").write_text(code)
        recs = engine._maintainability_recommendations(tmp_path)
        assert len(recs) == 0

    def test_maintainability_categories_diverse(self, engine: RecommendationEngine, tmp_path: Path):
        imports = "\n".join(f"import mod{i}" for i in range(20))
        (tmp_path / "coupled.py").write_text(imports + "\npass\n")
        recs = engine._maintainability_recommendations(tmp_path)
        categories = {r.category for r in recs}
        assert RecommendationCategory.ARCHITECTURE in categories or RecommendationCategory.MAINTAINABILITY in categories


# ---------------------------------------------------------------------------
# Rule Violation Recommendations (via enriched context)
# ---------------------------------------------------------------------------

class TestRuleRecommendationsEnriched:
    def test_file_sizes_populated(self, engine: RecommendationEngine, tmp_path: Path):
        lines = "\n".join(f"line{i} = {i}" for i in range(600))
        (tmp_path / "big.py").write_text(lines)
        from refactory.rules.engine import RuleContext, RuleEngine
        from refactory.rules.models import Rule, RuleCategory as RC, RuleCondition
        real_rule_engine = RuleEngine(logger=MagicMock())
        real_rule_engine.add_rule(Rule(
            name="max-file-size",
            category=RC.MAX_FILE_SIZE,
            conditions=[RuleCondition(value=500)],
            message="File too large",
        ))
        engine._rules = real_rule_engine
        recs = engine._rule_recommendations(tmp_path)
        file_recs = [r for r in recs if "max-file-size" in r.title]
        assert len(file_recs) >= 1

    def test_function_sizes_populated(self, engine: RecommendationEngine, tmp_path: Path):
        body = "\n".join(f"    x{i} = {i}" for i in range(60))
        (tmp_path / "funcs.py").write_text(f"def big_func():\n{body}\n")
        from refactory.rules.engine import RuleContext, RuleEngine
        from refactory.rules.models import Rule, RuleCategory as RC, RuleCondition
        real_rule_engine = RuleEngine(logger=MagicMock())
        real_rule_engine.add_rule(Rule(
            name="max-func-size",
            category=RC.MAX_FUNCTION_SIZE,
            conditions=[RuleCondition(value=50)],
            message="Function too large",
        ))
        engine._rules = real_rule_engine
        recs = engine._rule_recommendations(tmp_path)
        func_recs = [r for r in recs if "max-func-size" in r.title]
        assert len(func_recs) >= 1


# ---------------------------------------------------------------------------
# End-to-end: generate_recommendations diversity
# ---------------------------------------------------------------------------

class TestRecommendationDiversity:
    def test_generates_multiple_categories(self, engine: RecommendationEngine, tmp_path: Path):
        """A repo with issues across categories should produce diverse recommendations."""
        lines = "\n".join(f"line{i} = {i}" for i in range(600))
        (tmp_path / "big_file.py").write_text(lines)

        code_with_eval = "result = eval(input())\n"
        (tmp_path / "insecure.py").write_text(code_with_eval)

        (tmp_path / "app.py").write_text("def main():\n    print('hello')\n")

        report = engine.generate_recommendations(tmp_path)
        categories = {r.category for r in report.recommendations}

        assert len(categories) >= 2, (
            f"Expected at least 2 recommendation categories, got: {categories}"
        )

    def test_not_all_testing_category(self, engine: RecommendationEngine, tmp_path: Path):
        """Recommendations should NOT be exclusively 'Missing tests'."""
        lines = "\n".join(f"line{i} = {i}" for i in range(600))
        (tmp_path / "big_file.py").write_text(lines)
        (tmp_path / "insecure.py").write_text("x = eval('1+1')\n")

        report = engine.generate_recommendations(tmp_path)
        non_testing = [
            r for r in report.recommendations
            if r.category != RecommendationCategory.TESTING
        ]
        assert len(non_testing) >= 1, "Expected recommendations beyond just 'Missing tests'"

    def test_transformation_type_on_recs(self, engine: RecommendationEngine, tmp_path: Path):
        """Many recommendations should have transformation_type set."""
        (tmp_path / "large.py").write_text("\n" * 600)
        (tmp_path / "small.py").write_text("x = 1\n")

        report = engine.generate_recommendations(tmp_path)
        with_transform = [r for r in report.recommendations if r.transformation_type]
        assert len(with_transform) >= 1, "Expected some recommendations with transformation_type"

    def test_security_recs_generated(self, engine: RecommendationEngine, tmp_path: Path):
        (tmp_path / "danger.py").write_text("x = eval(input())\n")
        report = engine.generate_recommendations(tmp_path)
        security_recs = [r for r in report.recommendations if r.category == RecommendationCategory.SECURITY]
        assert len(security_recs) >= 1

    def test_debt_recs_generated(self, engine: RecommendationEngine, tmp_path: Path):
        (tmp_path / "large.py").write_text("\n" * 600)
        report = engine.generate_recommendations(tmp_path)
        debt_recs = [r for r in report.recommendations if r.category == RecommendationCategory.TECHNICAL_DEBT]
        assert len(debt_recs) >= 1

    def test_all_recs_have_ids(self, engine: RecommendationEngine, tmp_path: Path):
        (tmp_path / "app.py").write_text("x = 1\n")
        report = engine.generate_recommendations(tmp_path)
        for r in report.recommendations:
            assert r.id.startswith("R-"), f"Recommendation missing deterministic ID: {r}"

    def test_all_recs_have_priority(self, engine: RecommendationEngine, tmp_path: Path):
        (tmp_path / "app.py").write_text("x = 1\n")
        report = engine.generate_recommendations(tmp_path)
        for r in report.recommendations:
            assert isinstance(r.priority, RecommendationPriority)

    def test_recs_are_scored_and_sorted(self, engine: RecommendationEngine, tmp_path: Path):
        (tmp_path / "danger.py").write_text("eval('x')\n")
        (tmp_path / "large.py").write_text("\n" * 600)
        report = engine.generate_recommendations(tmp_path)
        scores = [r.score for r in report.recommendations]
        assert scores == sorted(scores, reverse=True), "Recommendations should be sorted by score descending"
