"""Telemetry event storage (metadata only — never source code)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from refactory_backend.db.base import Base


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    cli_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Optional free-form note — never used for source storage.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
