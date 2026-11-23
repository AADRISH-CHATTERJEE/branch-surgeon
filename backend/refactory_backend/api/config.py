"""Configuration control-plane endpoints (CLI download only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from refactory_backend.core.deps import CurrentUser, DbSession
from refactory_backend.schemas.config import (
    CLIConfigResponse,
    ControlPlaneConfigBundle,
    OrganizationResponse,
    PromptListResponse,
    RepositoryResponse,
    WorkflowListResponse,
)
from refactory_backend.services.config import ConfigService

router = APIRouter(tags=["config"])


def _service(db: DbSession) -> ConfigService:
    return ConfigService(db=db)


@router.get(
    "/config",
    response_model=CLIConfigResponse,
    summary="Download CLI control-plane configuration",
    description=(
        "Returns compact structured configuration for the Refactory CLI: "
        "prompt/workflow versions, AI provider/model preferences, feature flags, "
        "and limits. Configuration distribution only — the backend never receives "
        "repository source code, and does not run AI, parsing, embeddings, or Git."
    ),
)
def get_config(
    _user: CurrentUser,
    db: DbSession,
    organization_id: str | None = Query(
        default=None, description="Organization id or slug (defaults to seed org)"
    ),
    repository_id: str | None = Query(
        default=None, description="Repository id or slug (optional override)"
    ),
) -> CLIConfigResponse:
    return _service(db).get_cli_config(
        organization_id=organization_id,
        repository_id=repository_id,
    )


@router.get(
    "/config/bundle",
    response_model=ControlPlaneConfigBundle,
    summary="Download full configuration bundle",
    description=(
        "Returns the full organization/repository configuration bundle. "
        "CLI startup uses GET /config; this endpoint is for richer clients."
    ),
)
def get_config_bundle(
    _user: CurrentUser,
    db: DbSession,
    organization_id: str | None = Query(default=None),
    repository_id: str | None = Query(default=None),
) -> ControlPlaneConfigBundle:
    return _service(db).get_aggregate_config(
        organization_id=organization_id,
        repository_id=repository_id,
    )


@router.get(
    "/prompts",
    response_model=PromptListResponse,
    summary="List versioned prompt templates",
)
def list_prompts(_user: CurrentUser, db: DbSession) -> PromptListResponse:
    return _service(db).list_prompts()


@router.get(
    "/workflows",
    response_model=WorkflowListResponse,
    summary="List versioned workflow definitions",
)
def list_workflows(_user: CurrentUser, db: DbSession) -> WorkflowListResponse:
    return _service(db).list_workflows()


@router.get(
    "/organizations/{organization_id}",
    response_model=OrganizationResponse,
    summary="Get organization settings",
)
def get_organization(
    organization_id: str,
    _user: CurrentUser,
    db: DbSession,
) -> OrganizationResponse:
    org = _service(db).get_organization(organization_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{organization_id}' not found",
        )
    return org


@router.get(
    "/repositories/{repository_id}",
    response_model=RepositoryResponse,
    summary="Get repository settings (metadata only — no source code)",
)
def get_repository(
    repository_id: str,
    _user: CurrentUser,
    db: DbSession,
) -> RepositoryResponse:
    repo = _service(db).get_repository(repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repository_id}' not found",
        )
    return repo
