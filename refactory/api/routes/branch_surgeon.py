"""GET /branch-surgeon — orchestrated Branch Surgeon workspace snapshot."""

from __future__ import annotations

from fastapi import APIRouter

from refactory.api.deps import ContainerDep, RepoRootDep
from refactory.api.schemas import ApiResponse, ok
from refactory.api.serialize import to_data

router = APIRouter(tags=["branch-surgeon"])


@router.get(
    "/branch-surgeon",
    response_model=ApiResponse,
    summary="Branch Surgeon workspace snapshot",
    description=(
        "Orchestrates GitService, repository health, graph, recommendations, "
        "reviews, rules, activity, and deterministic merge_conflict_risk into "
        "one Branch Surgeon response. No new analysis engines — gather-only composition."
    ),
)
def get_branch_surgeon(
    container: ContainerDep,
    repo_root: RepoRootDep,
) -> ApiResponse:
    # Drop any in-process stats cache so recommendation fields are live.
    container.recommendation_stats_service.invalidate(repo_root=repo_root)
    workspace = container.branch_surgeon_service.compose_workspace()
    rec = workspace.recommendations
    return ok(
        to_data(workspace),
        message="Branch Surgeon workspace",
        meta={
            "repo_root": str(repo_root),
            "recommendation_source": rec.source,
            "recommendation_version": rec.version,
            "recommendation_total": rec.total,
        },
    )
