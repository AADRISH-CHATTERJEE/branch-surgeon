"""Strongly typed Git domain models (no GitPython types leak outward)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class WorkingFilePreview(BaseModel):
    """Result of a safe working-tree file content preview."""

    status: Literal["ok", "unsafe", "not_found", "binary", "too_large", "error"]
    path: str = ""
    size: int | None = None
    content: str | None = None
    language: str = "plaintext"
    sha: str | None = None
    truncated: bool = False
    message: str | None = None


class ChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNKNOWN = "unknown"
    UNTRACKED = "untracked"
    STAGED = "staged"


class ChangedPath(BaseModel):
    """A path changed relative to a comparison point."""

    path: str
    kind: ChangeKind = ChangeKind.MODIFIED
    old_path: str | None = None
    staged: bool = False


class GitCommitInfo(BaseModel):
    """Current HEAD commit metadata."""

    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: datetime


class WorkingTreeStatus(BaseModel):
    """Working tree / index status snapshot."""

    is_dirty: bool = False
    modified_files: list[ChangedPath] = Field(default_factory=list)
    deleted_files: list[ChangedPath] = Field(default_factory=list)
    renamed_files: list[ChangedPath] = Field(default_factory=list)
    staged_files: list[ChangedPath] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)
    changed_file_count: int = 0
    ahead: int | None = None
    behind: int | None = None


class BranchInfo(BaseModel):
    """Branch listing and HEAD state."""

    current_branch: str
    is_detached: bool = False
    default_branch: str | None = None
    local_branches: list[str] = Field(default_factory=list)
    remote_branches: list[str] = Field(default_factory=list)


class GitRepositoryInfo(BaseModel):
    """Full local Git snapshot used by GitService callers."""

    root_path: str
    name: str
    current_branch: str
    head_sha: str | None = None
    commit: GitCommitInfo | None = None
    remote_url: str | None = None
    default_branch: str | None = None
    is_dirty: bool = False
    is_detached: bool = False
    owner: str | None = None
    full_name: str | None = None
    local_branches: list[str] = Field(default_factory=list)
    remote_branches: list[str] = Field(default_factory=list)
    working_tree: WorkingTreeStatus = Field(default_factory=WorkingTreeStatus)


class CommitSummary(BaseModel):
    """Lightweight commit row for history listings."""

    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: datetime
    parent_shas: list[str] = Field(default_factory=list)


class CommitDetail(BaseModel):
    """Full commit metadata returned by CommitService.get_commit."""

    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: datetime
    parent_shas: list[str] = Field(default_factory=list)
    is_merge: bool = False


class CommitFileChange(BaseModel):
    """A single path changed by a commit, with optional patch body."""

    path: str
    kind: ChangeKind = ChangeKind.MODIFIED
    old_path: str | None = None
    insertions: int = 0
    deletions: int = 0
    is_binary: bool = False
    patch: str | None = None


class CommitStatistics(BaseModel):
    """Aggregate insertions / deletions / file counts for a commit."""

    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


class CommitDiff(BaseModel):
    """Unified patch plus per-file breakdown for a commit."""

    sha: str
    patch: str = ""
    files: list[CommitFileChange] = Field(default_factory=list)
    statistics: CommitStatistics = Field(default_factory=CommitStatistics)
