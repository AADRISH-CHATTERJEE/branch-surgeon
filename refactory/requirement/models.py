"""Strongly typed models for Requirement Impact Analysis."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class RiskEstimate(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RequirementRequest(BaseModel):
    """Raw user-provided requirement text."""

    raw_text: str


class RequirementSummary(BaseModel):
    """Parsed decomposition of the raw requirement."""

    summary: str = ""
    detected_features: list[str] = Field(default_factory=list)
    detected_keywords: list[str] = Field(default_factory=list)
    sentences: list[str] = Field(default_factory=list)
    file_hints: list[str] = Field(default_factory=list)
    technical_verbs: list[str] = Field(default_factory=list)


class RequirementCandidate(BaseModel):
    """A file likely affected by the requirement."""

    path: str
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class RequirementImpact(BaseModel):
    """One impacted file with severity and rationale."""

    file: str
    severity: str = "medium"
    why: str = ""


class RequirementPlan(BaseModel):
    """Implementation planning output."""

    implementation_order: list[str] = Field(default_factory=list)
    estimated_complexity: Complexity = Complexity.MEDIUM
    estimated_risk: RiskEstimate = RiskEstimate.MEDIUM
    estimated_effort: str = ""


class RequirementAnalysis(BaseModel):
    """Top-level result for a requirement impact analysis."""

    summary: str = ""
    features: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    candidate_files: list[RequirementCandidate] = Field(default_factory=list)
    impacted_files: list[RequirementImpact] = Field(default_factory=list)
    impacted_tests: list[str] = Field(default_factory=list)
    impacted_docs: list[str] = Field(default_factory=list)
    configuration_files: list[str] = Field(default_factory=list)
    database_files: list[str] = Field(default_factory=list)
    complexity: Complexity = Complexity.MEDIUM
    risk: RiskEstimate = RiskEstimate.MEDIUM
    confidence: float = 0.0
    implementation_plan: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
