"""Tests for RuleEngine — rule loading, evaluation, and violation detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refactory.rules.engine import RuleContext, RuleEngine
from refactory.rules.models import (
    Rule,
    RuleCategory,
    RuleCondition,
    RuleEvaluationResult,
    RuleSet,
    RuleSeverity,
    RuleViolation,
)


@pytest.fixture
def engine():
    from loguru import logger
    return RuleEngine(logger=logger)


@pytest.fixture
def ctx():
    return RuleContext({
        "branch_name": "feature/add-auth",
        "commit_message": "feat(auth): add login endpoint",
        "changed_files": ["src/auth/login.py", "tests/test_auth.py"],
        "imports": ["flask", "sqlalchemy", "os"],
        "file_sizes": {"src/auth/login.py": 200, "src/big.py": 600},
        "function_sizes": {"login": 30, "process_all": 80},
    })


# ===========================================================================
# Rule Model Tests
# ===========================================================================

class TestRuleModels:
    def test_rule_defaults(self):
        r = Rule(name="test")
        assert r.enabled is True
        assert r.severity == RuleSeverity.WARNING
        assert r.blocking is False

    def test_rule_severity_enum(self):
        assert RuleSeverity.ERROR == "error"
        assert RuleSeverity.WARNING == "warning"
        assert RuleSeverity.INFO == "info"

    def test_rule_category_enum(self):
        assert RuleCategory.BRANCH_NAMING == "branch_naming"
        assert RuleCategory.FORBIDDEN_IMPORT == "forbidden_import"
        assert RuleCategory.MAX_FILE_SIZE == "max_file_size"

    def test_rule_condition(self):
        c = RuleCondition(field="branch", operator="matches", pattern=r"^feature/")
        assert c.operator == "matches"

    def test_rule_violation(self):
        v = RuleViolation(
            rule_name="test", category=RuleCategory.CUSTOM,
            severity=RuleSeverity.ERROR, message="violated",
        )
        assert v.rule_name == "test"

    def test_rule_set(self):
        rs = RuleSet(rules=[Rule(name="a"), Rule(name="b")])
        assert len(rs.rules) == 2

    def test_evaluation_result_defaults(self):
        r = RuleEvaluationResult()
        assert r.passed is True
        assert r.violations == []


# ===========================================================================
# Rule Engine Tests
# ===========================================================================

class TestRuleEngine:
    def test_add_rule(self, engine: RuleEngine):
        engine.add_rule(Rule(name="test"))
        assert len(engine.rules) == 1

    def test_add_rules(self, engine: RuleEngine):
        engine.add_rules([Rule(name="a"), Rule(name="b")])
        assert len(engine.rules) == 2

    def test_clear_rules(self, engine: RuleEngine):
        engine.add_rule(Rule(name="test"))
        engine.clear_rules()
        assert len(engine.rules) == 0

    def test_evaluate_empty(self, engine: RuleEngine, ctx: RuleContext):
        result = engine.evaluate(ctx)
        assert result.passed is True
        assert result.rules_evaluated == 0

    def test_disabled_rule_skipped(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(name="disabled", enabled=False))
        result = engine.evaluate(ctx)
        assert result.rules_evaluated == 0

    def test_branch_naming_pass(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="branch-pattern",
            category=RuleCategory.BRANCH_NAMING,
            conditions=[RuleCondition(pattern=r"^(feature|fix)/")],
        ))
        result = engine.evaluate(ctx)
        assert result.passed is True
        assert result.rules_passed == 1

    def test_branch_naming_fail(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="branch-pattern",
            category=RuleCategory.BRANCH_NAMING,
            conditions=[RuleCondition(pattern=r"^release/")],
            message="Branch must start with release/",
        ))
        ctx = RuleContext({"branch_name": "feature/foo"})
        result = engine.evaluate(ctx)
        assert result.rules_failed == 1
        assert len(result.violations) == 1

    def test_commit_message_pass(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="commit-conv",
            category=RuleCategory.COMMIT_MESSAGE,
            conditions=[RuleCondition(pattern=r"^(feat|fix|docs)")],
        ))
        result = engine.evaluate(ctx)
        assert result.passed is True

    def test_commit_message_fail(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="commit-conv",
            category=RuleCategory.COMMIT_MESSAGE,
            conditions=[RuleCondition(pattern=r"^(feat|fix)")],
        ))
        ctx = RuleContext({"commit_message": "wip stuff"})
        result = engine.evaluate(ctx)
        assert result.rules_failed == 1

    def test_forbidden_path(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="no-vendor",
            category=RuleCategory.FORBIDDEN_PATH,
            conditions=[RuleCondition(pattern=r"vendor/")],
        ))
        result = engine.evaluate(ctx)
        assert result.passed is True

    def test_forbidden_path_violation(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="no-vendor",
            category=RuleCategory.FORBIDDEN_PATH,
            conditions=[RuleCondition(pattern=r"vendor/")],
        ))
        ctx = RuleContext({"changed_files": ["vendor/lib.py"]})
        result = engine.evaluate(ctx)
        assert len(result.violations) == 1

    def test_forbidden_import(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="no-requests",
            category=RuleCategory.FORBIDDEN_IMPORT,
            conditions=[RuleCondition(pattern=r"^requests$")],
        ))
        result = engine.evaluate(ctx)
        assert result.passed is True

    def test_forbidden_import_violation(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="no-os",
            category=RuleCategory.FORBIDDEN_IMPORT,
            conditions=[RuleCondition(pattern=r"^os$")],
        ))
        result = engine.evaluate(ctx)
        assert len(result.violations) == 1

    def test_max_function_size_pass(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="func-size",
            category=RuleCategory.MAX_FUNCTION_SIZE,
            conditions=[RuleCondition(value=100)],
        ))
        result = engine.evaluate(ctx)
        assert result.passed is True

    def test_max_function_size_fail(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="func-size",
            category=RuleCategory.MAX_FUNCTION_SIZE,
            conditions=[RuleCondition(value=50)],
        ))
        result = engine.evaluate(ctx)
        assert len(result.violations) == 1
        assert "process_all" in result.violations[0].message

    def test_max_file_size_pass(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="file-size",
            category=RuleCategory.MAX_FILE_SIZE,
            conditions=[RuleCondition(value=700)],
        ))
        result = engine.evaluate(ctx)
        assert result.passed is True

    def test_max_file_size_fail(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rule(Rule(
            name="file-size",
            category=RuleCategory.MAX_FILE_SIZE,
            conditions=[RuleCondition(value=500)],
        ))
        result = engine.evaluate(ctx)
        assert len(result.violations) == 1
        assert "big.py" in result.violations[0].file_path

    def test_blocking_violation(self, engine: RuleEngine):
        engine.add_rule(Rule(
            name="block-vendor",
            category=RuleCategory.FORBIDDEN_PATH,
            conditions=[RuleCondition(pattern=r"vendor/")],
            blocking=True,
        ))
        ctx = RuleContext({"changed_files": ["vendor/x.py"]})
        result = engine.evaluate(ctx)
        assert result.passed is False
        assert result.blocking_violations == 1

    def test_multiple_rules(self, engine: RuleEngine, ctx: RuleContext):
        engine.add_rules([
            Rule(name="branch", category=RuleCategory.BRANCH_NAMING,
                 conditions=[RuleCondition(pattern=r"^feature/")]),
            Rule(name="commit", category=RuleCategory.COMMIT_MESSAGE,
                 conditions=[RuleCondition(pattern=r"^feat")]),
        ])
        result = engine.evaluate(ctx)
        assert result.rules_evaluated == 2
        assert result.rules_passed == 2

    def test_load_json_rules(self, engine: RuleEngine, tmp_path: Path):
        rules_dir = tmp_path / ".refactory"
        rules_dir.mkdir()
        (rules_dir / "rules.json").write_text(json.dumps({
            "rules": [
                {"name": "test-rule", "category": "custom", "severity": "warning",
                 "message": "test", "conditions": []}
            ]
        }))
        count = engine.load_rules(tmp_path)
        assert count == 1
        assert len(engine.rules) == 1

    def test_load_nonexistent(self, engine: RuleEngine, tmp_path: Path):
        count = engine.load_rules(tmp_path)
        assert count == 0

    def test_load_invalid_json_raises(self, engine: RuleEngine, tmp_path: Path):
        rules_dir = tmp_path / ".refactory"
        rules_dir.mkdir()
        (rules_dir / "rules.json").write_text("invalid json{{{")
        with pytest.raises(ValueError, match="Cannot read"):
            engine.load_rules(tmp_path)


# ===========================================================================
# Rule Context Tests
# ===========================================================================

class TestRuleContext:
    def test_empty_context(self):
        ctx = RuleContext()
        assert ctx.branch_name == ""
        assert ctx.changed_files == []

    def test_set_get(self):
        ctx = RuleContext()
        ctx.set("key", "value")
        assert ctx.get("key") == "value"

    def test_data_property(self):
        ctx = RuleContext({"a": 1, "b": 2})
        assert ctx.data == {"a": 1, "b": 2}

    def test_branch_name(self):
        ctx = RuleContext({"branch_name": "main"})
        assert ctx.branch_name == "main"

    def test_imports(self):
        ctx = RuleContext({"imports": ["os", "sys"]})
        assert ctx.imports == ["os", "sys"]

    def test_function_sizes(self):
        ctx = RuleContext({"function_sizes": {"main": 100}})
        assert ctx.function_sizes == {"main": 100}
