"""Typed models for local test intelligence (no AI / network)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TestFramework(str, Enum):
    __test__ = False

    PYTEST = "pytest"
    UNITTEST = "unittest"
    UNKNOWN = "unknown"


class TestRiskLevel(str, Enum):
    __test__ = False

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TestMatch(BaseModel):
    """A test file / symbol linked to a production target."""

    __test__ = False

    path: str
    symbol: str | None = None
    framework: TestFramework = TestFramework.UNKNOWN
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class ProductionCoverage(BaseModel):
    """Coverage view for one production file or symbol."""

    path: str
    kind: str = "file"
    symbol: str | None = None
    tests: list[TestMatch] = Field(default_factory=list)
    covered: bool = False
    coverage_confidence: float = 0.0


class DuplicateTestGroup(BaseModel):
    """Likely duplicate tests covering the same target."""

    key: str
    tests: list[TestMatch] = Field(default_factory=list)
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class SlowTestCandidate(BaseModel):
    """Heuristic slow-test candidate (structure / breadth, not runtime)."""

    path: str
    score: float = 0.0
    import_count: int = 0
    symbol_count: int = 0
    reasons: list[str] = Field(default_factory=list)


class TestCoverageMap(BaseModel):
    """Repository-wide production ↔ test coverage map."""

    __test__ = False

    production_files: list[ProductionCoverage] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    uncovered_files: list[str] = Field(default_factory=list)
    uncovered_classes: list[str] = Field(default_factory=list)
    uncovered_functions: list[str] = Field(default_factory=list)
    multi_module_tests: list[str] = Field(default_factory=list)
    orphan_tests: list[str] = Field(default_factory=list)
    duplicate_groups: list[DuplicateTestGroup] = Field(default_factory=list)
    coverage_ratio: float = 0.0


class TestImpactReport(BaseModel):
    """Recommended tests and risk if tests are skipped for a target."""

    __test__ = False

    target: str
    recommended_tests: list[TestMatch] = Field(default_factory=list)
    coverage_confidence: float = 0.0
    risk_if_skipped: TestRiskLevel = TestRiskLevel.LOW
    missing_critical_tests: list[str] = Field(default_factory=list)
    impacted_production_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RelatedTestsReport(BaseModel):
    """Related tests for a file or symbol target."""

    target: str
    tests: list[TestMatch] = Field(default_factory=list)
    coverage_confidence: float = 0.0
    framework_hint: TestFramework = TestFramework.UNKNOWN
    notes: list[str] = Field(default_factory=list)
    target_found: bool = True
