"""JSON schema validation for AI review documents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class FindingSchema(BaseModel):
    """Loose schema for one finding — all fields optional for recovery."""

    title: str | None = None
    name: str | None = None
    explanation: str | None = None
    detail: str | None = None
    details: str | None = None
    description: str | None = None
    recommendation: str | None = None
    fix: str | None = None
    severity: str | None = None
    level: str | None = None
    file: str | None = None
    file_path: str | None = None
    path: str | None = None
    line: int | str | None = None
    code_snippet: str | None = None
    snippet: str | None = None
    category: str | None = None
    confidence: float | str | None = None

    model_config = {"extra": "allow"}


class ReviewDocumentSchema(BaseModel):
    """Schema for structured AI review JSON (tolerant)."""

    summary: str | None = None
    overview: str | None = None
    overall_risk: str | None = None
    risk_level: str | None = None
    risk: str | None = None
    confidence: float | str | None = None
    findings: list[FindingSchema | str | dict[str, Any]] | None = None
    suggestions: list[FindingSchema | str | dict[str, Any]] | None = None

    model_config = {"extra": "allow"}

    @field_validator("findings", "suggestions", mode="before")
    @classmethod
    def _coerce_list(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return [value]


def validate_review_document(
    data: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate and normalize a review JSON object. Never raises."""
    warnings: list[str] = []
    try:
        doc = ReviewDocumentSchema.model_validate(data)
    except ValidationError as exc:
        warnings.append(f"JSON schema validation failed: {exc.error_count()} issue(s)")
        # Keep raw dict for best-effort recovery
        return data, warnings

    normalized = doc.model_dump(exclude_none=True)
    # Prefer canonical keys
    if not normalized.get("summary") and normalized.get("overview"):
        normalized["summary"] = normalized["overview"]
    if not normalized.get("overall_risk"):
        normalized["overall_risk"] = (
            normalized.get("risk_level") or normalized.get("risk") or "unknown"
        )
    findings = normalized.get("suggestions")
    if findings is None:
        findings = normalized.get("findings")
    if findings is not None:
        normalized["suggestions"] = [
            item if isinstance(item, (dict, str)) else item for item in findings
        ]
    warnings.append("JSON schema validated")
    return normalized, warnings
