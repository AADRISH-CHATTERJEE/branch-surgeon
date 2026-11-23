"""Shared helpers for local API route handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from refactory.api.schemas import fail
from refactory.core.container import ServiceContainer


def resolve_repository_record(container: ServiceContainer) -> dict[str, Any] | None:
    """Look up the persisted repository row for the container's git root."""
    root = Path(container.git_service.get_root_path()).resolve()
    return container.query_service.get_repository_by_root(str(root))


def not_found(message: str, *errors: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=fail(*errors, message=message).model_dump(),
    )


def api_error(status_code: int, message: str, *errors: str) -> JSONResponse:
    """Return a non-2xx ApiResponse envelope with an explicit HTTP status."""
    return JSONResponse(
        status_code=status_code,
        content=fail(*errors, message=message).model_dump(),
    )
