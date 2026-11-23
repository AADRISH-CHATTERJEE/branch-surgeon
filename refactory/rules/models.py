"""Strongly typed models for the Rule Engine."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RuleSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    BLOCKER = "blocker"


class RuleCategory(str, Enum):
    BRANCH_NAMING = "branch_naming"
    COMMIT_MESSAGE = "commit_message"
    PR_TITLE = "pr_title"
    REQUIRED_REVIEWERS = "required_reviewers"
    MERGE_STRATEGY = "merge_strategy"
    FORBIDDEN_PATH = "forbidden_path"
    FORBIDDEN_IMPORT = "forbidden_import"
    FORBIDDEN_DEPENDENCY = "forbidden_dependency"
    ALLOWED_DEPENDENCY = "allowed_dependency"
    ARCHITECTURE_LAYER = "architecture_layer"
    MODULE_OWNERSHIP = "module_ownership"
    NAMING_CONVENTION = "naming_convention"
    MAX_FUNCTION_SIZE = "max_function_size"
    MAX_FILE_SIZE = "max_file_size"
    FORBIDDEN_API = "forbidden_api"
    DEPRECATED_API = "deprecated_api"
    SECURITY_POLICY = "security_policy"
    NO_HARDCODED_SECRETS = "no_hardcoded_secrets"
    LICENSE_POLICY = "license_policy"
    REQUIRED_TESTS = "required_tests"
    MIN_COVERAGE = "min_coverage"
    TEST_NAMING = "test_naming"
    REQUIRE_DOCSTRINGS = "require_docstrings"
    REQUIRE_README = "require_readme"
    STALE_DOCS = "stale_docs"
    MAX_PR_SIZE = "max_pr_size"
    MIN_SEVERITY = "min_severity"
    CUSTOM = "custom"


class RuleCondition(BaseModel):
    """A condition for rule evaluation."""

    field: str = ""
    operator: str = "matches"
    value: str | int | float | list[str] | None = None
    pattern: str = ""


class Rule(BaseModel):
    """A single configurable rule."""

    name: str
    description: str = ""
    severity: RuleSeverity = RuleSeverity.WARNING
    enabled: bool = True
    category: RuleCategory = RuleCategory.CUSTOM
    conditions: list[RuleCondition] = Field(default_factory=list)
    message: str = ""
    blocking: bool = False
    # Phase 11.2 — organization rules metadata (built-ins leave defaults)
    source: str = "builtin"  # builtin | organization
    rule_type: str = ""
    documentation_url: str = ""
    condition_logic: str = "and"  # and | or
    id: str = ""


class RuleViolation(BaseModel):
    """A rule violation detected during evaluation."""

    rule_name: str
    category: RuleCategory
    severity: RuleSeverity
    message: str = ""
    file_path: str = ""
    line: int = 0
    blocking: bool = False
    context: dict[str, str] = Field(default_factory=dict)
    source: str = "builtin"  # builtin | organization
    documentation_url: str = ""


class RuleEvaluationResult(BaseModel):
    """Result of evaluating all rules."""

    violations: list[RuleViolation] = Field(default_factory=list)
    rules_evaluated: int = 0
    rules_passed: int = 0
    rules_failed: int = 0
    blocking_violations: int = 0
    passed: bool = True


class RuleSet(BaseModel):
    """A collection of rules, typically loaded from a config file."""

    version: str = "1.0"
    rules: list[Rule] = Field(default_factory=list)
