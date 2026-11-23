"""Provider health-check models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ProviderHealth(BaseModel):
    """Result of a single provider health probe."""

    provider: str
    model: str
    status: HealthStatus = HealthStatus.UNKNOWN
    latency_ms: float | None = None
    message: str = ""
    details: dict[str, object] = Field(default_factory=dict)
