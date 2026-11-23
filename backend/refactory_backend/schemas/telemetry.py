"""Telemetry schemas — operational metadata only (no source code)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Reject payloads that look like source dumps.
_FORBIDDEN_KEYS = frozenset(
    {
        "source_code",
        "source",
        "code",
        "file_contents",
        "repository_contents",
        "diff_full",
    }
)


class TelemetryEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    cli_version: str | None = Field(default=None, max_length=50)
    os_name: str | None = Field(default=None, max_length=50)
    message: str | None = Field(default=None, max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _reject_source_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        lowered = {str(key).lower() for key in value}
        bad = lowered & _FORBIDDEN_KEYS
        if bad:
            raise ValueError(
                "Telemetry payload must not include source/code fields: "
                + ", ".join(sorted(bad))
            )
        # Cap nested size roughly by key count
        if len(value) > 50:
            raise ValueError("Telemetry payload may contain at most 50 keys")
        return value


class TelemetryEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    accepted: bool = True
    received_at: datetime
