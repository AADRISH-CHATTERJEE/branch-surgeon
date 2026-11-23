"""Shared response envelope and request models for the local REST API."""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard local-API response envelope."""

    status: Literal["success", "error"] = "success"
    message: str = ""
    data: T | None = None
    errors: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


def ok(
    data: Any = None,
    *,
    message: str = "",
    meta: dict[str, Any] | None = None,
) -> ApiResponse[Any]:
    return ApiResponse(status="success", message=message, data=data, meta=meta or {})


def fail(
    *errors: str,
    message: str = "Request failed",
    meta: dict[str, Any] | None = None,
) -> ApiResponse[Any]:
    return ApiResponse(
        status="error",
        message=message,
        data=None,
        errors=list(errors),
        meta=meta or {},
    )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class RulesCheckRequest(BaseModel):
    """Optional overrides for company-rules check."""

    branch: str | None = None
    commit: str | None = None
    base: str | None = None
    changed_files: list[str] | None = None


class ReviewRequest(BaseModel):
    """Start a local PR-scoped review (committed base...head only)."""

    pr_number: int = Field(..., ge=1, description="Pull request or local review target id")
    base_branch: str | None = Field(
        None,
        description="Optional base branch override (default: repository default branch)",
    )
    head_ref: str | None = Field(
        None,
        description="Optional head ref override (default: HEAD). Working tree is never used.",
    )


class RecommendRequest(BaseModel):
    top: int = Field(15, ge=1, le=200)
    category: str | None = None
    priority: str | None = None


class TransformRequest(BaseModel):
    target_file: str = ""
    transformation_type: str = "rename_symbol"
    target_symbol: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Convenience fields merged into parameters by the transform route
    new_name: str | None = None
    method_name: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    destination_file: str | None = None
    param_order: list[str] | None = None
    rename_params: dict[str, str] | None = None
    # Phase 2 — AI Refactoring Planner / multi-file scope
    natural_language: str | None = None
    scope: str | None = None  # file | repository
    ai_assisted: bool | None = None


class GraphBuildRequest(BaseModel):
    force: bool = False


class IndexBuildRequest(BaseModel):
    force: bool = False
