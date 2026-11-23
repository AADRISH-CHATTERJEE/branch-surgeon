"""Serialize service results to plain JSON-friendly data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel


def iso_utc(value: datetime | None) -> str | None:
    """Serialize datetimes as UTC ISO-8601 with a ``Z`` suffix.

    SQLite often returns UTC values as naive datetimes. Emitting them without a
    timezone causes browsers to treat them as local time (e.g. IST ≈ +5:30),
    which makes relative labels like "5h ago" appear incorrectly.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def to_data(value: Any) -> Any:
    """Convert Pydantic models / nested structures for ApiResponse.data."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            return model_dump()
    if isinstance(value, dict):
        return {k: to_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_data(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
