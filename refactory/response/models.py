"""Strongly typed review models produced from raw AI text.

Independent of ``refactory.review.models`` (engine contract) and of AI providers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ReviewSuggestion(BaseModel):
    """One actionable finding extracted from an AI review response."""

    title: str = ""
    explanation: str = ""
    recommendation: str = ""
    severity: str = "info"
    file: str | None = None
    line: int | None = None
    code_snippet: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    category: str | None = None
    estimated_impact: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if number > 1.0 and number <= 100.0:
            number = number / 100.0
        return max(0.0, min(1.0, number))

    @field_validator("line", mode="before")
    @classmethod
    def _coerce_line(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None


class ReviewMetadata(BaseModel):
    """Parse provenance and soft diagnostics (never blocks callers)."""

    source_format: str = "unknown"
    provider: str | None = None
    model: str | None = None
    raw_length: int = 0
    suggestion_count: int = 0
    parse_warnings: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ReviewResult(BaseModel):
    """Fully or mostly successful parse of an AI review response."""

    summary: str = ""
    overall_risk: str = "unknown"
    suggestions: list[ReviewSuggestion] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: ReviewMetadata = Field(default_factory=ReviewMetadata)
    is_partial: Literal[False] = False

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: object) -> float | None:
        return ReviewSuggestion._clamp_confidence(value)

    @property
    def warnings(self) -> list[str]:
        return list(self.metadata.parse_warnings)


class PartialReviewResult(ReviewResult):
    """Degraded parse — best-effort fields plus warnings. Never raises to CLI."""

    is_partial: Literal[True] = True


ParsedReview = ReviewResult | PartialReviewResult
