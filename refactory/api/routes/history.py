"""GET /history — Analysis History (results memory)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.routes._helpers import not_found, resolve_repository_record
from refactory.api.schemas import ApiResponse, fail, ok

router = APIRouter(prefix="/history", tags=["history"])


class RetentionRequest(BaseModel):
    """Retention policy: null/0 = unlimited; else days to keep."""

    days: int | None = Field(
        None, description="Keep last N days; 0 or null = unlimited"
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get(
    "",
    response_model=ApiResponse,
    summary="List analysis history",
    description="Newest-first historical analyses for the configured repository.",
)
def list_history(
    container: ContainerDep,
    repo_root: RepoRootDep,
    analysis_type: str | None = Query(None),
    status: str | None = Query(None),
    branch: str | None = Query(None),
    search: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ApiResponse | JSONResponse:
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    rows = container.analysis_history_service.list_history(
        repository_id=repo["id"],
        analysis_type=analysis_type,
        status=status,
        branch=branch,
        search=search,
        since=_parse_dt(since),
        until=_parse_dt(until),
        limit=limit,
        offset=offset,
    )
    return ok(
        rows,
        meta={"repo_root": str(repo_root), "count": len(rows)},
    )


@router.get(
    "/metrics",
    response_model=ApiResponse,
    summary="History metrics strip",
)
def history_metrics(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse | JSONResponse:
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    metrics = container.analysis_history_service.metrics(repository_id=repo["id"])
    return ok(metrics, meta={"repo_root": str(repo_root)})


@router.get(
    "/export",
    summary="Export history as JSON, Markdown, or CSV",
)
def export_history(
    container: ContainerDep,
    format: str = Query("json", pattern="^(json|markdown|md|csv)$"),
    limit: int = Query(500, ge=1, le=5000),
):
    repo = resolve_repository_record(container)
    if repo is None:
        return JSONResponse(
            status_code=404,
            content=fail("Repository not found", message="Not found").model_dump(),
        )
    content, media = container.analysis_history_service.export(
        format=format, repository_id=repo["id"], limit=limit
    )
    filename = f"analysis-history.{ 'md' if format in {'markdown', 'md'} else format }"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/retention",
    response_model=ApiResponse,
    summary="Apply history retention policy",
)
def apply_retention(
    body: RetentionRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse | JSONResponse:
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    result = container.analysis_history_service.apply_retention(
        days=body.days, repository_id=repo["id"]
    )
    return ok(
        result,
        message="Retention applied" if result.get("deleted") else "No deletions",
        meta={"repo_root": str(repo_root)},
    )


@router.get(
    "/{history_id}",
    response_model=ApiResponse,
    summary="Get a single history entry",
)
def get_history_item(
    history_id: str, container: ContainerDep, repo_root: RepoRootDep
) -> ApiResponse | JSONResponse:
    repo = resolve_repository_record(container)
    if repo is None:
        return not_found("Not found", "Repository not found in persistence DB")
    row = container.analysis_history_service.get(history_id)
    if row is None:
        return not_found("Not found", f"History item '{history_id}' not found")
    if str(row.get("repository_id") or "") != str(repo["id"]):
        return not_found(
            "Not found",
            f"History item '{history_id}' does not belong to the configured repository",
        )
    return ok(row, meta={"repo_root": str(repo_root)})
