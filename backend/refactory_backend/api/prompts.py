"""Prompt template endpoints (versioned control-plane content)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from refactory_backend.core.deps import CurrentUser, DbSession
from refactory_backend.schemas.prompts import PromptTemplateResponse
from refactory_backend.services.config import ConfigService

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get(
    "/review",
    response_model=PromptTemplateResponse,
    summary="Fetch a review prompt template version",
    description=(
        "Returns the default review prompt when `version` is omitted. "
        "Use GET /prompts to discover available versions."
    ),
)
def get_review_prompt_endpoint(
    _user: CurrentUser,
    db: DbSession,
    version: str | None = Query(
        default=None, description="Prompt version (e.g. 1.0.0). Defaults to latest."
    ),
) -> PromptTemplateResponse:
    prompt = ConfigService(db=db).get_prompt("review", version)
    if prompt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review prompt version '{version}' not found",
        )
    return prompt
