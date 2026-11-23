"""Telemetry ingestion service (metadata only)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from refactory_backend.models.telemetry import TelemetryEvent
from refactory_backend.models.user import User
from refactory_backend.schemas.telemetry import TelemetryEventCreate


class TelemetryService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(self, event: TelemetryEventCreate, user: User | None) -> TelemetryEvent:
        row = TelemetryEvent(
            user_id=user.id if user else None,
            event_type=event.event_type,
            cli_version=event.cli_version,
            os_name=event.os_name,
            message=event.message,
            payload=event.payload,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row
