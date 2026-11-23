"""Strongly typed models for the Recommendation Engine."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def generate_recommendation_id(
    *,
    file_path: str = "",
    category: str = "",
    symbol: str = "",
    title: str = "",
    repository: str = "",
) -> str:
    """Generate a deterministic recommendation ID from its identifying attributes.

    Stable IDs enable recommendation history tracking, dismissal, and UI persistence.
    """
    key = f"{repository}|{file_path}|{category}|{symbol or title}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:8].upper()
    return f"R-{digest}"


class RecommendationCategory(str, Enum):
    REFACTORING = "refactoring"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    TECHNICAL_DEBT = "technical_debt"
    RELIABILITY = "reliability"
    BEST_PRACTICES = "best_practices"
    RULE_VIOLATIONS = "rule_violations"


class RecommendationPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    # UI backlog vocabulary (RecommendationStatsService buckets)
    RESOLVED = "resolved"
    IGNORED = "ignored"
    # Legacy aliases kept for existing rows / callers
    ACCEPTED = "accepted"
    IMPLEMENTED = "implemented"
    DEFERRED = "deferred"


class TechnicalDebtCategory(str, Enum):
    LARGE_CLASS = "large_class"
    LARGE_METHOD = "large_method"
    GOD_OBJECT = "god_object"
    LONG_PARAMETER_LIST = "long_parameter_list"
    DEEP_NESTING = "deep_nesting"
    DUPLICATE_CODE = "duplicate_code"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    UNUSED_ABSTRACTION = "unused_abstraction"
    FEATURE_ENVY = "feature_envy"
    SHOTGUN_SURGERY = "shotgun_surgery"
    PRIMITIVE_OBSESSION = "primitive_obsession"
    TEMPORARY_FIELD = "temporary_field"
    LARGE_INTERFACE = "large_interface"


class RecommendationExplanation(BaseModel):
    """Detailed explanation for a recommendation."""

    why: str = ""
    benefits: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    estimated_implementation_time: str = ""
    estimated_review_time: str = ""
    confidence_explanation: str = ""


class Recommendation(BaseModel):
    """A single engineering recommendation."""

    id: str = Field(default_factory=lambda: f"R-{uuid.uuid4().hex[:6].upper()}")
    title: str
    description: str = ""
    category: RecommendationCategory = RecommendationCategory.REFACTORING
    severity: str = "medium"
    confidence: float = 0.0
    priority: RecommendationPriority = RecommendationPriority.MEDIUM
    estimated_effort: str = ""
    estimated_risk: str = "low"
    business_impact: str = ""
    technical_impact: str = ""
    affected_files: list[str] = Field(default_factory=list)
    affected_modules: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    explanation: RecommendationExplanation = Field(default_factory=RecommendationExplanation)
    score: float = 0.0
    status: RecommendationStatus = RecommendationStatus.PENDING
    transformation_type: str = ""
    transformation_parameters: dict = Field(default_factory=dict)
    estimated_patch_size: int = 0
    bundle_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecommendationBundle(BaseModel):
    """A group of related recommendations."""

    id: str = Field(default_factory=lambda: f"B-{uuid.uuid4().hex[:6].upper()}")
    title: str
    description: str = ""
    recommendations: list[str] = Field(default_factory=list)
    estimated_total_effort: str = ""
    category: RecommendationCategory = RecommendationCategory.REFACTORING


class TechnicalDebtItem(BaseModel):
    """A single technical debt item."""

    category: TechnicalDebtCategory
    file_path: str = ""
    symbol: str = ""
    description: str = ""
    severity: str = "medium"
    estimated_cleanup_effort: str = ""
    score: float = 0.0


class TechnicalDebtReport(BaseModel):
    """Technical debt analysis result."""

    items: list[TechnicalDebtItem] = Field(default_factory=list)
    total_score: float = 0.0
    categories: dict[str, int] = Field(default_factory=dict)


class HealthScores(BaseModel):
    """Repository health scores."""

    architecture: float = 0.0
    maintainability: float = 0.0
    security: float = 0.0
    performance: float = 0.0
    testing: float = 0.0
    documentation: float = 0.0
    technical_debt: float = 0.0
    overall: float = 0.0


class HealthReport(BaseModel):
    """Repository health dashboard."""

    scores: HealthScores = Field(default_factory=HealthScores)
    trends: dict[str, list[float]] = Field(default_factory=dict)
    recommendations_count: int = 0
    critical_count: int = 0


class TrendItem(BaseModel):
    """A single trend observation."""

    metric_name: str
    direction: str = "stable"
    change_percent: float = 0.0
    period: str = ""
    description: str = ""


class TrendReport(BaseModel):
    """Historical trend analysis."""

    trends: list[TrendItem] = Field(default_factory=list)
    period: str = "30d"
    modules_degrading: list[str] = Field(default_factory=list)
    modules_improving: list[str] = Field(default_factory=list)


class RecommendationReport(BaseModel):
    """Complete recommendation report for CLI output."""

    repository_score: float = 0.0
    total_recommendations: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    recommendations: list[Recommendation] = Field(default_factory=list)
    bundles: list[RecommendationBundle] = Field(default_factory=list)
    reconcile_stats: dict[str, int] = Field(default_factory=dict)
