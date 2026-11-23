"""POST /index and GET /index/status."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.schemas import ApiResponse, IndexBuildRequest, ok
from refactory.api.serialize import to_data

router = APIRouter(prefix="/index", tags=["index"])


@router.post(
    "",
    response_model=ApiResponse,
    summary="Build the repository index",
    description="Delegates to IndexerService.build_index (no embeddings / AI).",
)
def build_index(
    body: IndexBuildRequest,
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    from refactory.api.routes._activity import persist_repo_activity
    from refactory.history.helpers import timed

    meta = container.git_service.get_repository_metadata()
    with timed() as t:
        result = container.indexer_service.build_index(
            meta.root_path,
            repository_name=meta.name,
            force=body.force,
        )
    payload = {
        "summary": to_data(result.summary),
        "statistics": to_data(result.statistics),
    }
    # Activity feed reads analysis_runs — History is mirrored from the same write.
    persist_repo_activity(
        container,
        command="index",
        result_type="repository_index",
        summary="Index built",
        duration_ms=t.duration_ms,
        result_data=payload if isinstance(payload, dict) else {"summary": payload},
    )
    container.recommendation_stats_service.invalidate(repo_root=repo_root)
    return ok(
        payload,
        message="Index built",
        meta={"repo_root": str(repo_root)},
    )


@router.get(
    "/status",
    response_model=ApiResponse,
    summary="Index staleness and last-index summary",
    description="Uses IndexerService.assess_staleness and load_index.",
)
def index_status(container: ContainerDep, repo_root: RepoRootDep) -> ApiResponse:
    root = Path(container.git_service.get_root_path())
    staleness = container.indexer_service.assess_staleness(root)
    last = container.indexer_service.load_index(root) or container.indexer_service.get_last_index()
    return ok(
        {
            "staleness": to_data(staleness),
            "last_index": {
                "summary": to_data(last.summary) if last is not None else None,
                "statistics": to_data(last.statistics) if last is not None else None,
            },
        },
        meta={"repo_root": str(repo_root)},
    )
