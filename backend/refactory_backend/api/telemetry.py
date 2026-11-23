"""Telemetry ingestion endpoint."""

from __future__ import annotations

from fastapi import APIRouter, status

from refactory_backend.core.deps import CurrentUser, DbSession
from refactory_backend.schemas.telemetry import TelemetryEventCreate, TelemetryEventResponse
from refactory_backend.services.telemetry import TelemetryService

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post(
    "",
    response_model=TelemetryEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Accept CLI telemetry (metadata only, never source code)",
)
def post_telemetry(
    body: TelemetryEventCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> TelemetryEventResponse:
    event = TelemetryService(db).record(body, current_user)
    return TelemetryEventResponse(
        id=event.id,
        event_type=event.event_type,
        accepted=True,
        received_at=event.received_at,
    )
