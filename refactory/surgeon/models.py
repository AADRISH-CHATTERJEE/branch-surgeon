"""Strongly typed models for Branch Surgeon analysis."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueKind(str, Enum):
    LARGE_PR = "large_pr"
    HOTSPOT = "hotspot"
    MISSING_TESTS = "missing_tests"
    BLAST_RADIUS = "blast_radius"
    RISK_CONCENTRATION = "risk_concentration"
    POOR_COMMIT_MESSAGE = "poor_commit_message"
    DUPLICATE_FILE_EDITS = "duplicate_file_edits"
    BRANCH_AGE = "branch_age"
    MERGE_CONFLICT_RISK = "merge_conflict_risk"
    DOCUMENTATION_DRIFT = "documentation_drift"


class RecommendationType(str, Enum):
    SPLIT_PR = "split_pr"
    ADD_TESTS = "add_tests"
    SQUASH_COMMITS = "squash_commits"
    UPDATE_DOCS = "update_docs"
    REDUCE_SCOPE = "reduce_scope"
    REBASE = "rebase"
    REVIEW_SECURITY = "review_security"
    INFORMATIONAL = "informational"


class BranchIssue(BaseModel):
    """A detected structural or quality problem on the branch."""

    kind: IssueKind
    severity: IssueSeverity
    title: str
    detail: str = ""
    files: list[str] = Field(default_factory=list)
    commits: list[str] = Field(default_factory=list)


class BranchRecommendation(BaseModel):
    """A concrete action recommended for the branch."""

    kind: RecommendationType
    title: str
    detail: str = ""
    files: list[str] = Field(default_factory=list)


class BranchCommitSummary(BaseModel):
    """Lightweight per-commit record for surgeon analysis."""

    sha: str
    short_sha: str
    message: str
    author: str
    committed_at: datetime
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


class ChangedFileSummary(BaseModel):
    """Aggregated stats for a file changed on the branch."""

    path: str
    commit_count: int = 0  # how many branch commits touched it
    insertions: int = 0
    deletions: int = 0
    is_test: bool = False
    is_security_sensitive: bool = False


class BranchHealth(BaseModel):
    """Numeric health indicators for the branch."""

    score: int = 100  # 0-100
    grade: str = "A"  # A/B/C/D/F
    commit_count: int = 0
    changed_file_count: int = 0
    total_insertions: int = 0
    total_deletions: int = 0
    branch_age_days: float = 0.0
    merge_conflict_risk: IssueSeverity = IssueSeverity.LOW
    test_coverage_gap: bool = False
    has_poor_commits: bool = False


class BranchAnalysis(BaseModel):
    """Complete Branch Surgeon analysis result."""

    branch: str
    base_branch: str
    repository: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now())
    health: BranchHealth = Field(default_factory=BranchHealth)
    commits: list[BranchCommitSummary] = Field(default_factory=list)
    changed_files: list[ChangedFileSummary] = Field(default_factory=list)
    issues: list[BranchIssue] = Field(default_factory=list)
    recommendations: list[BranchRecommendation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Local API workspace DTO (GET /branch-surgeon) — orchestration snapshot
# ---------------------------------------------------------------------------


class SurgeonBranchSummary(BaseModel):
    name: str = ""
    base_branch: str = ""
    head_sha: str | None = None
    repository: str = ""
    commits: int = 0
    changed_files: int = 0
    insertions: int = 0
    deletions: int = 0


class SurgeonHealthSummary(BaseModel):
    overall: float = 0.0
    architecture: float = 0.0
    security: float = 0.0
    testing: float = 0.0
    maintainability: float = 0.0


class SurgeonScoreSummary(BaseModel):
    score: int = 0
    grade: str = "Unknown"
    formula: str = ""


class SurgeonBlastRadius(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    critical_files: list[str] = Field(default_factory=list)
    most_connected: list[str] = Field(default_factory=list)


class SurgeonRecommendationCounts(BaseModel):
    """Recommendation snapshot — always populated from RecommendationStatsService."""

    total: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    pending: int = 0
    resolved: int = 0
    ignored: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    last_updated: datetime | None = None
    repository_id: str = ""
    repository: str = ""
    repo_root: str = ""
    branch: str = ""
    source: str = "RecommendationStatsService"
    version: str = "1"


class SurgeonReviewSummary(BaseModel):
    completed: int = 0
    pending: int = 0
    latest: dict | None = None


class SurgeonRulesSummary(BaseModel):
    passed: int = 0
    failed: int = 0
    warning_count: int = 0
    outcome: str = "pass"


class SurgeonMergeConflictRisk(BaseModel):
    """Deterministic lightweight merge-conflict risk heuristic for Local API."""

    level: str = "low"  # low | medium | high
    score: float = 0.0  # 0.0–1.0
    reason: str = ""


class SurgeonTimelineEntry(BaseModel):
    id: str = ""
    kind: str = "activity"
    label: str = ""
    status: str = ""
    at: str | None = None
    detail: str | None = None


class BranchSurgeonWorkspace(BaseModel):
    """Single-response Branch Surgeon Local API snapshot."""

    branch: SurgeonBranchSummary = Field(default_factory=SurgeonBranchSummary)
    health: SurgeonHealthSummary = Field(default_factory=SurgeonHealthSummary)
    surgery: SurgeonScoreSummary = Field(default_factory=SurgeonScoreSummary)
    blast_radius: SurgeonBlastRadius = Field(default_factory=SurgeonBlastRadius)
    recommendations: SurgeonRecommendationCounts = Field(
        default_factory=SurgeonRecommendationCounts
    )
    reviews: SurgeonReviewSummary = Field(default_factory=SurgeonReviewSummary)
    rules: SurgeonRulesSummary = Field(default_factory=SurgeonRulesSummary)
    merge_conflict_risk: SurgeonMergeConflictRisk = Field(
        default_factory=SurgeonMergeConflictRisk
    )
    # Convenience mirrors for UI consumers (same values as nested fields).
    confidence: float | None = None
    surgery_score: int = 0
    timeline: list[SurgeonTimelineEntry] = Field(default_factory=list)
