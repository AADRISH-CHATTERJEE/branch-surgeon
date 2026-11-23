"""Models for AI patch generation and application from persisted recommendations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class FilePatchContent(BaseModel):
    """Before/after content for a single file in a generated patch."""

    file_path: str
    original: str = ""
    modified: str = ""


class RecommendationPatchResult(BaseModel):
    """API response payload for POST /recommendations/{id}/patch."""

    id: str = ""
    recommendation_id: str
    explanation: str = ""
    confidence: float = 0.0
    changed_files: list[str] = Field(default_factory=list)
    unified_diff: str = ""
    patches: list[FilePatchContent] = Field(default_factory=list)
    prompt_version: str = ""
    model: str = ""
    provider: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    apply_available: bool = True


class PatchValidationResult(BaseModel):
    """Post-apply validation summary."""

    ok: bool = True
    checked_files: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    rolled_back: bool = False


class PatchApplyResult(BaseModel):
    """API response payload for apply / rollback endpoints."""

    status: Literal[
        "applied",
        "conflict",
        "failed",
        "dry_run",
        "rolled_back",
    ] = "applied"
    applied: bool = False
    patch_id: str = ""
    recommendation_id: str = ""
    changed_files: list[str] = Field(default_factory=list)
    validation: PatchValidationResult = Field(default_factory=PatchValidationResult)
    repository_updated: bool = False
    index_updated: bool = False
    graph_updated: bool = False
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
    failure_code: (
        Literal[
            "conflict",
            "dirty_working_tree",
            "patch_outdated",
            "validation_failed",
            "git_failure",
            "policy_block",
            "missing_file",
            "permission",
            "not_found",
            "already_applied",
            "not_applied",
        ]
        | None
    ) = None
    git_commit: str | None = None
    applied_at: str | None = None
    applied_by: str | None = None
    recommendation_status: str | None = None
    recommendation: dict[str, Any] | None = None
    dry_run: bool = False


class PatchGenerationError(Exception):
    """Raised when a patch cannot be generated for a recommendation."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PatchConflictError(Exception):
    """Raised when the working tree no longer matches the patch baseline."""

    def __init__(self, message: str, *, files: list[str] | None = None) -> None:
        self.message = message
        self.files = files or []
        super().__init__(message)


class PatchApplyError(Exception):
    """Raised when apply fails for a non-conflict reason (validation, IO, missing)."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)
