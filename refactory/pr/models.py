"""Strongly typed models for PR intelligence features."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Git Diff Models (Task 1)
# ---------------------------------------------------------------------------


class DiffChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class ChangedSymbol(BaseModel):
    """A symbol affected by a diff."""

    name: str
    kind: str = "function"
    file_path: str = ""
    change_type: DiffChangeKind = DiffChangeKind.MODIFIED
    start_line: int = 0
    end_line: int = 0


class ChangedFile(BaseModel):
    """A file affected by a diff."""

    path: str
    change_kind: DiffChangeKind = DiffChangeKind.MODIFIED
    old_path: str | None = None
    insertions: int = 0
    deletions: int = 0
    hunks: list[str] = Field(default_factory=list)
    changed_symbols: list[ChangedSymbol] = Field(default_factory=list)
    is_binary: bool = False


class DiffSummary(BaseModel):
    """Summary of a diff between two points."""

    base_ref: str = ""
    head_ref: str = ""
    changed_files: list[ChangedFile] = Field(default_factory=list)
    total_insertions: int = 0
    total_deletions: int = 0
    files_added: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_renamed: int = 0


# ---------------------------------------------------------------------------
# PR Summary (Task 2)
# ---------------------------------------------------------------------------


class PRSummary(BaseModel):
    """Generated PR summary."""

    title: str = ""
    description: str = ""
    files_changed: int = 0
    modules_affected: list[str] = Field(default_factory=list)
    architectural_impact: str = ""
    breaking_changes: list[str] = Field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Merge Risk (Task 3)
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskFactor(BaseModel):
    """A single factor contributing to merge risk."""

    name: str
    description: str = ""
    severity: RiskLevel = RiskLevel.LOW
    confidence: float = 0.0


class MergeRiskReport(BaseModel):
    """Merge risk analysis result."""

    overall_risk: RiskLevel = RiskLevel.LOW
    risk_score: float = 0.0
    factors: list[RiskFactor] = Field(default_factory=list)
    central_modules_modified: int = 0
    api_changes: int = 0
    public_method_changes: int = 0
    configuration_changes: int = 0
    recommendation: str = ""


# ---------------------------------------------------------------------------
# Reviewer Recommendation (Task 4)
# ---------------------------------------------------------------------------


class ReviewerCandidate(BaseModel):
    """A recommended reviewer."""

    name: str
    email: str = ""
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    files_owned: int = 0
    modules_owned: list[str] = Field(default_factory=list)


class ReviewerReport(BaseModel):
    """Reviewer recommendation result."""

    reviewers: list[ReviewerCandidate] = Field(default_factory=list)
    changed_files: int = 0
    modules_affected: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Test Recommendation (Task 5)
# ---------------------------------------------------------------------------


class TestRecommendation(BaseModel):
    """A recommended test."""

    test_file: str = ""
    test_name: str = ""
    kind: str = "unit"
    reason: str = ""
    confidence: float = 0.0
    missing: bool = False


class TestRecommendationReport(BaseModel):
    """Test recommendation result."""

    existing_tests: list[TestRecommendation] = Field(default_factory=list)
    missing_tests: list[TestRecommendation] = Field(default_factory=list)
    integration_tests: list[TestRecommendation] = Field(default_factory=list)
    regression_tests: list[TestRecommendation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Breaking Changes (Task 6)
# ---------------------------------------------------------------------------


class BreakingChangeKind(str, Enum):
    REMOVED_METHOD = "removed_method"
    RENAMED_API = "renamed_api"
    CHANGED_SIGNATURE = "changed_signature"
    DELETED_INTERFACE = "deleted_interface"
    CHANGED_CONTRACT = "changed_contract"
    REMOVED_CLASS = "removed_class"


class BreakingChange(BaseModel):
    """A detected breaking change."""

    kind: BreakingChangeKind
    symbol: str
    file_path: str = ""
    description: str = ""
    severity: RiskLevel = RiskLevel.HIGH
    affected_dependents: list[str] = Field(default_factory=list)


class BreakingChangeReport(BaseModel):
    """Breaking change detection result."""

    changes: list[BreakingChange] = Field(default_factory=list)
    total_breaking: int = 0
    risk_level: RiskLevel = RiskLevel.LOW


# ---------------------------------------------------------------------------
# AI Review Comments (Task 7)
# ---------------------------------------------------------------------------


class ReviewCategory(str, Enum):
    BUG_RISK = "bug_risk"
    PERFORMANCE = "performance"
    SECURITY = "security"
    STYLE = "style"
    MAINTAINABILITY = "maintainability"
    MISSING_TESTS = "missing_tests"
    DOCUMENTATION = "documentation"


class ReviewComment(BaseModel):
    """A single AI-generated review comment."""

    file: str = ""
    line: int = 0
    category: ReviewCategory = ReviewCategory.STYLE
    severity: str = "info"
    explanation: str = ""
    confidence: float = 0.0
    suggested_fix: str = ""
    estimated_impact: str = ""


class AIReviewReport(BaseModel):
    """AI review result."""

    comments: list[ReviewComment] = Field(default_factory=list)
    summary: str = ""
    model: str = ""


# ---------------------------------------------------------------------------
# Security Review (Task 8)
# ---------------------------------------------------------------------------


class SecurityIssueKind(str, Enum):
    UNSAFE_DESERIALIZATION = "unsafe_deserialization"
    SQL_INJECTION = "sql_injection"
    PATH_TRAVERSAL = "path_traversal"
    COMMAND_EXECUTION = "command_execution"
    INSECURE_SECRETS = "insecure_secrets"
    WEAK_AUTHENTICATION = "weak_authentication"
    XSS = "xss"
    INSECURE_RANDOM = "insecure_random"


class SecurityIssue(BaseModel):
    """A detected security issue."""

    kind: SecurityIssueKind
    file: str = ""
    line: int = 0
    description: str = ""
    severity: RiskLevel = RiskLevel.HIGH
    confidence: float = 0.0
    recommendation: str = ""
    cwe: str = ""


class SecurityReport(BaseModel):
    """Security review result."""

    issues: list[SecurityIssue] = Field(default_factory=list)
    total_issues: int = 0
    critical_count: int = 0
    high_count: int = 0
    passed: bool = True


# ---------------------------------------------------------------------------
# Performance Review (Task 9)
# ---------------------------------------------------------------------------


class PerformanceIssueKind(str, Enum):
    NESTED_LOOPS = "nested_loops"
    REPEATED_DB_CALLS = "repeated_db_calls"
    DUPLICATE_PARSING = "duplicate_parsing"
    INEFFICIENT_ALGORITHM = "inefficient_algorithm"
    EXPENSIVE_ALLOCATION = "expensive_allocation"
    N_PLUS_ONE = "n_plus_one"
    UNBOUNDED_QUERY = "unbounded_query"


class PerformanceIssue(BaseModel):
    """A detected performance issue."""

    kind: PerformanceIssueKind
    file: str = ""
    line: int = 0
    description: str = ""
    severity: str = "medium"
    confidence: float = 0.0
    recommendation: str = ""


class PerformanceReport(BaseModel):
    """Performance review result."""

    issues: list[PerformanceIssue] = Field(default_factory=list)
    total_issues: int = 0


# ---------------------------------------------------------------------------
# Merge Readiness (Task 10)
# ---------------------------------------------------------------------------


class ReadinessStatus(str, Enum):
    READY = "ready"
    NEEDS_WORK = "needs_work"
    BLOCK_MERGE = "block_merge"


class MergeReadinessReport(BaseModel):
    """Merge readiness assessment."""

    overall_score: float = 0.0
    status: ReadinessStatus = ReadinessStatus.NEEDS_WORK
    review_completeness: float = 0.0
    documentation_score: float = 0.0
    test_coverage_score: float = 0.0
    risk_score: float = 0.0
    architecture_score: float = 0.0
    security_score: float = 0.0
    recommendation: str = ""
    blockers: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Changed Dependency Graph (Task 11)
# ---------------------------------------------------------------------------


class DependencyNode(BaseModel):
    """A node in the changed dependency graph."""

    name: str
    kind: str = "module"
    change_type: str = "unchanged"


class DependencyEdge(BaseModel):
    """An edge in the changed dependency graph."""

    source: str
    target: str
    relationship: str = "imports"


class ChangedDependencyGraph(BaseModel):
    """Visualization of change impact through the dependency graph."""

    changed_modules: list[str] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    impacted_apis: list[str] = Field(default_factory=list)
    recommended_tests: list[str] = Field(default_factory=list)
    nodes: list[DependencyNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AI Change Explanation (Task 12)
# ---------------------------------------------------------------------------


class ChangeExplanation(BaseModel):
    """AI-generated explanation of a change."""

    summary: str = ""
    why_it_matters: str = ""
    downstream_effects: list[str] = Field(default_factory=list)
    migration_concerns: list[str] = Field(default_factory=list)
    architectural_consequences: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    confidence: float = 0.0
