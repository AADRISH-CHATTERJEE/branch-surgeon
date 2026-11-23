"""GET /activity — analysis/history reads."""

from __future__ import annotations

from fastapi import APIRouter, Query

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._helpers import not_found, resolve_repository_record
from refactory.api.schemas import ApiResponse, ok

router = APIRouter(tags=["activity"])


@router.get(
    "/activity",
    response_model=ApiResponse,
    summary="List recent analysis activity for the repository",
    description="Thin read over RepositoryQueryService.get_analyses.",
    responses={404: {"model": ApiResponse}},
)
def list_activity(
    container: ContainerDep,
    repo_root: RepoRootDep,
    command: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    runs = container.query_service.get_analyses(
        repo["id"], command=command, status=status, limit=limit
    )
    return ok(runs, meta={"repo_root": str(repo_root), "count": len(runs)})
