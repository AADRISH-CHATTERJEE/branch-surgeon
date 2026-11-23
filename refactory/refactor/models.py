"""Strongly typed models for the Refactoring Engine."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RefactorSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RefactorCategory(str, Enum):
    LARGE_FILE = "large_file"
    LONG_FUNCTION = "long_function"
    DUPLICATE_LOGIC = "duplicate_logic"
    DEAD_CODE = "dead_code"
    UNUSED_IMPORT = "unused_import"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    GOD_CLASS = "god_class"
    LAYER_VIOLATION = "layer_violation"
    NAMING_CONSISTENCY = "naming_consistency"
    DOCUMENTATION_DRIFT = "documentation_drift"


class RefactorPriority(str, Enum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class RefactorKind(str, Enum):
    SPLIT_FILE = "split_file"
    EXTRACT_FUNCTION = "extract_function"
    EXTRACT_CLASS = "extract_class"
    REMOVE_DEAD_CODE = "remove_dead_code"
    REMOVE_UNUSED_IMPORT = "remove_unused_import"
    BREAK_CYCLE = "break_cycle"
    DECOMPOSE_CLASS = "decompose_class"
    MOVE_TO_LAYER = "move_to_layer"
    RENAME = "rename"
    ADD_DOCUMENTATION = "add_documentation"
    CONSOLIDATE_DUPLICATES = "consolidate_duplicates"


class RefactorIssue(BaseModel):
    """A detected code quality issue."""

    category: RefactorCategory
    severity: RefactorSeverity
    title: str
    detail: str = ""
    file: str = ""
    symbol: str = ""
    line: int | None = None
    metrics: dict[str, object] = Field(default_factory=dict)


class RefactorRecommendation(BaseModel):
    """A concrete refactoring action."""

    kind: RefactorKind
    priority: RefactorPriority
    title: str
    detail: str = ""
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    estimated_effort: str = ""


class RefactorMetrics(BaseModel):
    """Aggregate quality metrics for the analysis scope."""

    files_analyzed: int = 0
    total_issues: int = 0
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0
    health_score: int = 100
    grade: str = "A"
    largest_file_lines: int = 0
    longest_function_lines: int = 0
    circular_dependency_count: int = 0
    dead_code_count: int = 0
    unused_import_count: int = 0
    duplicate_candidate_count: int = 0


class RefactorPlan(BaseModel):
    """Ordered implementation plan for refactoring."""

    steps: list[str] = Field(default_factory=list)
    estimated_effort: str = ""
    estimated_risk: str = "low"
    confidence: float = 0.0


class RefactorAnalysis(BaseModel):
    """Complete refactoring analysis result."""

    scope: str = "repository"
    target: str = ""
    issues: list[RefactorIssue] = Field(default_factory=list)
    recommendations: list[RefactorRecommendation] = Field(default_factory=list)
    metrics: RefactorMetrics = Field(default_factory=RefactorMetrics)
    plan: RefactorPlan = Field(default_factory=RefactorPlan)
    notes: list[str] = Field(default_factory=list)
