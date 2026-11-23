"""Typed models for repository-level intelligence (read-only analysis)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PathSize(BaseModel):
    path: str
    size_bytes: int = 0


class ContributorStat(BaseModel):
    name: str
    email: str
    commits: int = 0


class AnalysisStatistics(BaseModel):
    """Repository-wide statistics for intelligence / dashboards."""

    total_files: int = 0
    tracked_files: int = 0
    ignored_files: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    branch_count: int = 0
    tag_count: int = 0
    commit_count: int = 0
    contributor_count: int = 0
    contributors: list[ContributorStat] = Field(default_factory=list)
    largest_files: list[PathSize] = Field(default_factory=list)
    largest_directories: list[PathSize] = Field(default_factory=list)
    oldest_commit_sha: str | None = None
    oldest_commit_at: datetime | None = None
    newest_commit_sha: str | None = None
    newest_commit_at: datetime | None = None
    average_commits_per_day: float = 0.0


class BranchInsight(BaseModel):
    name: str
    is_active: bool = False
    is_merged: bool = False
    is_stale: bool = False
    ahead: int = 0
    behind: int = 0
    last_commit_sha: str | None = None
    last_commit_message: str | None = None
    last_author: str | None = None
    last_committed_at: datetime | None = None


class BranchAnalysis(BaseModel):
    active_branch: str
    default_branch: str | None = None
    is_detached: bool = False
    branches: list[BranchInsight] = Field(default_factory=list)
    merged_branches: list[str] = Field(default_factory=list)
    stale_branches: list[str] = Field(default_factory=list)


class HotspotEntry(BaseModel):
    path: str
    score: float = 0.0
    modification_count: int = 0
    author_count: int = 0
    recent_modification_count: int = 0
    churn: int = 0
    is_directory: bool = False


class HotspotReport(BaseModel):
    files: list[HotspotEntry] = Field(default_factory=list)
    directories: list[HotspotEntry] = Field(default_factory=list)
    recent_files: list[HotspotEntry] = Field(default_factory=list)
    multi_author_files: list[HotspotEntry] = Field(default_factory=list)
    high_churn_files: list[HotspotEntry] = Field(default_factory=list)


class FileAuthor(BaseModel):
    name: str
    email: str
    commits: int = 0
    insertions: int = 0
    deletions: int = 0


class FileRenameEvent(BaseModel):
    sha: str
    old_path: str
    new_path: str
    committed_at: datetime | None = None


class FileHistoryEvent(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: datetime
    kind: str = "modified"
    insertions: int = 0
    deletions: int = 0


class FileHistory(BaseModel):
    path: str
    exists: bool = True
    creation_sha: str | None = None
    creation_at: datetime | None = None
    last_modification_sha: str | None = None
    last_modification_at: datetime | None = None
    modification_count: int = 0
    authors: list[FileAuthor] = Field(default_factory=list)
    rename_history: list[FileRenameEvent] = Field(default_factory=list)
    was_deleted: bool = False
    was_restored: bool = False
    events: list[FileHistoryEvent] = Field(default_factory=list)


class ActivityEntry(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: datetime
    files_changed: int = 0


class RepositoryHealth(BaseModel):
    very_large_files: list[PathSize] = Field(default_factory=list)
    dead_directories: list[str] = Field(default_factory=list)
    orphan_modules: list[str] = Field(default_factory=list)
    high_churn_files: list[str] = Field(default_factory=list)
    todo_density: float = 0.0
    fixme_density: float = 0.0
    todo_count: int = 0
    fixme_count: int = 0
    average_file_size: float = 0.0
    largest_module: str | None = None
    longest_dependency_chain: int = 0
    longest_dependency_path: list[str] = Field(default_factory=list)


class RepositoryOverview(BaseModel):
    """Full repository intelligence snapshot."""

    name: str
    root_path: str
    current_branch: str
    head_sha: str | None = None
    remote_url: str | None = None
    statistics: AnalysisStatistics = Field(default_factory=AnalysisStatistics)
    branches: BranchAnalysis = Field(
        default_factory=lambda: BranchAnalysis(active_branch="HEAD")
    )
    hotspots: HotspotReport = Field(default_factory=HotspotReport)
    health: RepositoryHealth = Field(default_factory=RepositoryHealth)
    recent_activity: list[ActivityEntry] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)
