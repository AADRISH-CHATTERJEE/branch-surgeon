"""Workflow definition endpoints (versioned control-plane content)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from refactory_backend.core.deps import CurrentUser, DbSession
from refactory_backend.schemas.workflows import WorkflowDefinitionResponse
from refactory_backend.services.config import ConfigService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get(
    "/review",
    response_model=WorkflowDefinitionResponse,
    summary="Fetch a review workflow definition version",
    description=(
        "Returns the default review workflow when `version` is omitted. "
        "Use GET /workflows to discover available versions."
    ),
)
def get_review_workflow_endpoint(
    _user: CurrentUser,
    db: DbSession,
    version: str | None = Query(
        default=None, description="Workflow version (e.g. 1.0.0). Defaults to latest."
    ),
) -> WorkflowDefinitionResponse:
    workflow = ConfigService(db=db).get_workflow("review", version)
    if workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review workflow version '{version}' not found",
        )
    return workflow
