"""Review-domain data contracts shared across engine, AI, and presentation layers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Repository(BaseModel):
    name: str
    root_path: str
    current_branch: str
    remote_url: str | None = None
    default_branch: str | None = None
    owner: str | None = None
    full_name: str | None = None
    # Optional so older callers stay valid; GET /repository exposes this for UI parity.
    head_sha: str | None = None


class RepositorySummary(BaseModel):
    repository: Repository
    file_count: int = 0
    languages: list[str] = Field(default_factory=list)
    summary: str = ""


class ReviewSuggestion(BaseModel):
    title: str
    detail: str
    severity: str = "info"
    file_path: str | None = None
    line: int | None = None
    category: str | None = None
    confidence: float | None = None
    suggested_fix: str = ""
    estimated_impact: str = ""


class ReviewResult(BaseModel):
    """Structured review output contract for CLI / callers.

    Core fields are stable. Optional telemetry fields are additive and default
    empty so existing callers remain compatible.
    """

    pull_request_number: int
    summary: str = ""
    risk_level: str = "unknown"
    suggestions: list[ReviewSuggestion] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Optional presentation / observability (populated by ReviewEngine when available)
    provider: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    elapsed_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    estimated_cost_usd: float | None = None
    cache_hit: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
