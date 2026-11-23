"""Typed models for local impact analysis."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ImpactTargetKind(str, Enum):
    FILE = "file"
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    SYMBOL = "symbol"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ImpactedLocation(BaseModel):
    """One estimated impacted file / symbol site."""

    path: str
    symbol: str | None = None
    kind: str = "file"
    distance: int | None = None
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class DependencyChain(BaseModel):
    """Ordered path illustrating how impact propagates."""

    nodes: list[str] = Field(default_factory=list)
    relationship: str = "import"


class ImpactReport(BaseModel):
    """Full impact analysis result for a single target."""

    target: str
    target_kind: ImpactTargetKind = ImpactTargetKind.UNKNOWN
    resolved_paths: list[str] = Field(default_factory=list)
    resolved_symbols: list[str] = Field(default_factory=list)

    direct_dependencies: list[ImpactedLocation] = Field(default_factory=list)
    transitive_dependencies: list[ImpactedLocation] = Field(default_factory=list)
    imports: list[ImpactedLocation] = Field(default_factory=list)
    importers: list[ImpactedLocation] = Field(default_factory=list)
    callers: list[ImpactedLocation] = Field(default_factory=list)
    callees: list[ImpactedLocation] = Field(default_factory=list)
    inheritance: list[ImpactedLocation] = Field(default_factory=list)
    related_files: list[ImpactedLocation] = Field(default_factory=list)
    semantic_neighbors: list[ImpactedLocation] = Field(default_factory=list)

    direct_impact: list[ImpactedLocation] = Field(default_factory=list)
    indirect_impact: list[ImpactedLocation] = Field(default_factory=list)
    dependency_chains: list[DependencyChain] = Field(default_factory=list)
    impacted_files: list[str] = Field(default_factory=list)
    impacted_symbols: list[str] = Field(default_factory=list)

    risk_level: RiskLevel = RiskLevel.LOW
    confidence: float = 0.0
    orphan_target: bool = False
    in_cycle: bool = False
    cycle_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
